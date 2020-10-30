#!/usr/bin/python3
#############################################################################
# zbxgit2tpl.py - Import templates from a Git repo into Zabbix
#
# Author: Robin Roevens (at) uantwerpen.be
# Version: 0.1
#
# Requires: Python 3
#           PyZabbix python module: https://github.com/lukecyca/pyzabbix
#           pygit2 python module: https://www.pygit2.org/
#
# Install required python modules using: pip install -r requirements.txt
#
# Configure parameters using the zbxgit2tpl.conf configfile
# Make sure the configured git repository exists and the configured user
# has developer access to it. (Master-access is required during first commit
# if it is a new repo wihout any commits as this will create configured branch)
#

import sys
import logging
import os
from shutil import rmtree
import pygit2
from zbxtpltools import zbxtpltools

def main():
    global LOGGER

    # Enable logging
    #logging.basicConfig(level=logging.DEBUG)
    LOGGER = logging.getLogger(__name__)

    LOGGER.info("Zabbix Template Importer started")

    # Read configuration
    try:
        zbxtpltools.read_configfile("zbxgit2tpl")
    except KeyError as err:
        sys.exit(f'Unable to read configfile: Could not find required key {str(err)}')
    except Exception as err:
        sys.exit(f'Unable to read configfile: {str(err)}')

    # Login to Zabbix
    try:
        zbxtpltools.zabbix_login()
    except Exception as err:
        sys.exit('Unable to connect: %s' % err)

    export_path = os.path.join(zbxtpltools.TEMP_PATH, 'repository')
    LOGGER.debug('Export path: %s', export_path)

    # Remove delete export path if it already exists
    try:
        LOGGER.info('Ensuring export path %s does not exist', export_path)
        rmtree(export_path)
    except FileNotFoundError:
        LOGGER.debug('Directory did not exist.')
        pass
    except Exception as err:
        sys.exit('Unable to delete old version of export path %s: %s' % (export_path, str(err)))

    # Clone Git repository
    LOGGER.info('Git: Cloning remote Git repository from %s', zbxtpltools.GIT_URL)
    try:
        repo = zbxtpltools.git_clone_repo(export_path)
    except Exception as err:
        sys.exit('Unable to clone git repository %s to %s: %s' % \
            (zbxtpltools.GIT_URL, export_path, str(err)))

    # Clean up files in cloned repository
    LOGGER.info('Cleaning up files')
    zbxtpltools.clear_dir(export_path)

    try:
        zbxtpltools.zabbix_get_and_export_templates(export_path)
    except Exception as err:
        sys.exit('Failed to get and export Zabbix templates from group %s to %s: %s', \
                 zbxtpltools.ZABBIX_TEMPLATE_EXPORT_GROUP, export_path, str(err))

    # Find changed files according to git
    LOGGER.info('Checking for changes.')
    changes = [(filepath, flags) \
        for filepath, flags in repo.status().items() \
            if flags != pygit2.GIT_STATUS_CURRENT]
    LOGGER.debug('Changes:\n %s', changes)

    if changes:
        # Delete removed templates from Zabbix
        templates_to_remove = [os.path.join(export_path, filepath) \
            for filepath, flags in changes \
                if flags == pygit2.GIT_STATUS_WT_NEW]
        if templates_to_remove:
            zbxtpltools.zabbix_remove_templates(templates_to_remove)

        # Revert Git so that we have the new and/or modified template files back
        LOGGER.debug('Resetting repo to commit %s', repo.head.target.hex)
        repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)

        # Import modified or new templates
        # Note: since we check changes between git and templates in Zabbix,
        #       new templates are flagged as deleted by git, since they do not yet exist in Zabbix
        templates_to_import = [os.path.join(export_path, filepath) \
            for filepath, flags in changes \
                if flags in (pygit2.GIT_STATUS_WT_MODIFIED, \
                             pygit2.GIT_STATUS_WT_DELETED)]
        if templates_to_import:
            zbxtpltools.zabbix_import_templates(templates_to_import)
    else:
        LOGGER.info('No changes where found. Nothing to be done..')

if __name__ == "__main__":
    main()
