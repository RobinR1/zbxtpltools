#!/usr/bin/python3
#############################################################################
# zbxtpl2git.py - Export a selected set of templates from Zabbix and commits
#                 them to Git.
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
# Configure parameters using the zbxtpl2git.ini configfile
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
    LOGGER = logging.getLogger(__name__)

    LOGGER.info("Zabbix Templates to GIT transporter started")

    # Read configuration
    try:
        zbxtpltools.read_configfile("zbxtpl2git")
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

    # Add exported templates to Git index
    LOGGER.info('Git: Adding exported templates')
    repo.index.add_all()
    repo.index.write()

    # Commit and then push the changes
    try:
        zbxtpltools.git_commit_and_push(repo)
    except Exception as err:
        sys.exit('Failed during commit and push: %s', str(err))

if __name__ == "__main__":
    main()
