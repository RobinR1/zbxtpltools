#!/usr/bin/python3

import os
import json
import logging
import configparser
import re
from shutil import rmtree
from glob import glob
from datetime import datetime
import pygit2
from pyzabbix import ZabbixAPI
from pkg_resources import resource_filename

# Enable logging
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

class GitRemoteCallbacks(pygit2.RemoteCallbacks):
    """ Callback to catch errors """
    LOGGER = logging.getLogger(__name__)

    def push_update_reference(self, refname, message):
        if message is not None:
            self.LOGGER.critical('Error pushing to %s: %s', refname, message)
            return -7
        return 0

def find_file(path):
    """ Check if a file exists as given, in current working directory or in script-directory.
        Returns the full path the file when found. """

    logging.debug('Looking for file %s', path)
    if os.path.isfile(path):
        fullpath = path
    elif os.path.isfile(os.path.abspath(path)):
        fullpath = os.path.abspath(path)
    elif os.path.join(os.path.dirname(os.path.realpath(__file__)), path):
        fullpath = os.path.join(os.path.dirname(os.path.realpath(__file__)), path)
    else:
        raise Exception('Unable to find file %s' % path)

    logging.debug('Found file: %s', fullpath)

    return fullpath

def clear_dir(path):
    """ Removes all files and subdirectory from a given path """

    files = glob(os.path.join(path, '') + '*')
    for f in files:
        LOGGER.debug('Deleting old file or directory %s', f)
        rmtree(f) if os.path.isdir(f) else os.remove(f)


def read_configfile(config_filename):
    """ Read and parse given configfile """

    global TEMP_PATH
    global ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD, ZABBIX_TEMPLATE_EXPORT_GROUP, \
           ZABBIX_TEMPLATE_ROOT_GROUP
    global GIT_URL, GIT_BRANCH, GIT_CALLBACKS, GIT_SIGNATURE

    # Find and read configfile
    config = configparser.ConfigParser()
    configfile = '%s.conf' % config_filename
    print(f'Reading configfile {configfile}')

    for loc in os.path.join(os.curdir, configfile), \
        os.path.join(os.path.expanduser('~'), configfile), \
        resource_filename(__name__,
                          os.path.join("../../../../etc/zbxtpltools/",
                          configfile)):
        try:
            with open(loc) as source:
                config.read_file(source)
                break
        except IOError:
            pass

    if not config.has_option('zabbix', 'url'):
        raise Exception('Could not read configfile ' + loc)

    TEMP_PATH = config['general']['temp_path']
    ZABBIX_URL = config['zabbix']['url']
    ZABBIX_USER = config['zabbix']['user']
    ZABBIX_PASSWORD = config['zabbix']['password']
    LOGGER.info("Zabbix URL: %s - API user: %s", ZABBIX_URL, ZABBIX_USER)

    ZABBIX_TEMPLATE_EXPORT_GROUP = config['zabbix']['template_export_group']
    ZABBIX_TEMPLATE_ROOT_GROUP = config['zabbix']['template_root_group']

    GIT_URL = config['git']['url']
    GIT_BRANCH = config['git']['branch']
    GIT_USER = re.search(r'(?:https?|ssh)://([^@?/:]+)', GIT_URL).group(1)
    GIT_CALLBACKS = GitRemoteCallbacks(
        credentials=pygit2.Keypair(GIT_USER,
                                   find_file(config['git']['ssh_pubkey']),
                                   find_file(config['git']['ssh_privkey']),
                                   ''))
    GIT_SIGNATURE = pygit2.Signature(config['git']['author_name'], config['git']['author_email'])
    LOGGER.info("Git URL: %s - branch: %s", GIT_URL, GIT_BRANCH)

def zabbix_login():
    """ Initiate a Zabbix API session """
    global ZAPI

    ZAPI = ZabbixAPI(ZABBIX_URL)
    LOGGER.info('Zabbix: Logging in into Zabbix API %s as %s', ZABBIX_URL, ZABBIX_USER)
    ZAPI.login(ZABBIX_USER, ZABBIX_PASSWORD)
    LOGGER.info('Connected to Zabbix API Version %s', ZAPI.api_version())

def get_hostgroup_id(hostgroup_name):
    """ Retrieve ID for a template hostgroup-name """

    LOGGER.debug('ZabbixAPI: Retrieve ID for hostgroup "%s"', hostgroup_name)
    hostgroups = ZAPI.hostgroup.get(filter={'name': hostgroup_name},
                                    templated_hosts=True)
    if len(hostgroups) != 1:
        raise Exception('Found %d hostgroups matching name %s. This should be 1.' % \
                (len(hostgroups), hostgroup_name))

    hostgroup_id = hostgroups.pop()['groupid']
    LOGGER.debug('Resolved hostgroup "%s" into ID %s', hostgroup_name, hostgroup_id)

    return hostgroup_id

def get_templates(hostgroup):
    """ Retrieve list of templates that are defined to the given groupID or -name """

    # Look up hostgroup id if a hostname was given
    hostgroup_id = get_hostgroup_id(hostgroup) if not hostgroup.isnumeric() else hostgroup

    LOGGER.debug('ZabbixAPI: Retrieving templates, member of group with id %s', hostgroup_id)
    templates = ZAPI.template.get(groupids=hostgroup_id,
                                  selectGroups=['groupid', 'name'],
                                  output=['templateid', 'name'])

    return templates

def export_template(template_id, filename):
    """ Exports a template to a JSON file """

    # Create path if not already exists
    path = os.path.dirname(filename)
    try:
        LOGGER.debug('Creating export path: %s', path)
        os.makedirs(path)
    except FileExistsError:
        LOGGER.debug('Export Path %s already exists.', path)

    # Export template in JSON format
    LOGGER.debug('Zabbix API: Exporting template id %s as JSON', template_id)
    template_json = json.loads(ZAPI.configuration.export(format='json',
                                                         options={'templates':[template_id]}))

    # Clear export date to prevent unnecessary git changes
    template_json['zabbix_export']['date'] = ''

    # Write template into file
    LOGGER.debug('Writing template JSON into file: %s', filename)
    with open(filename, 'w+') as f:
        f.write(json.dumps(template_json, indent=4))

def zabbix_get_and_export_templates(path):
    """ Retrieves and exports all templates assigned to 
        ZABBIX_TEMPLATE_EXPORT_GROUP to a given path """

   # Retrieve templates to be exported from Zabbix
    LOGGER.info('Zabbix: Retrieve templates to be exported')
    templates = get_templates(ZABBIX_TEMPLATE_EXPORT_GROUP)

    if not templates:
        raise Exception('No templates found in hostgroup %s', ZABBIX_TEMPLATE_EXPORT_GROUP)

    # Export found templates
    LOGGER.info('Zabbix: Export %d templates', len(templates))
    for t in templates:
        for g in t['groups']:
            if g['name'] != ZABBIX_TEMPLATE_EXPORT_GROUP and \
               g['groupid'] != ZABBIX_TEMPLATE_EXPORT_GROUP:
                filename = os.path.join(path,
                                        os.path.normpath(
                                            g['name'].replace(ZABBIX_TEMPLATE_ROOT_GROUP + '/',
                                                              '')),
                                        t['name'] + '.json')
                LOGGER.debug('Exporting template %s as %s', t['templateid'], t['name'])
                export_template(t['templateid'], filename)
                pass

def import_template(filename):
    """ Imports a JSON template file """

    # Read the file
    LOGGER.debug('Reading template JSON file: %s', filename)
    with open(filename, 'r') as f:
        template_json = json.load(f)

    # Put current date as export date
    template_json['zabbix_export']['date'] = datetime.today().strftime('%Y-%m-%dT%H:%M:%SZ')

    # Import file in Zabbix
    LOGGER.debug('Content of %s:\n%s', filename, json.dumps(template_json))
    ZAPI.confimport(confformat='json', \
                    source=json.dumps(template_json), \
                    rules={'applications': {'createMissing': True,
                                            'deleteMissing': True},
                           'discoveryRules': {'createMissing': True,
                                              'updateExisting': True,
                                              'deleteMissing': True},
                           'graphs': {'createMissing': True,
                                      'updateExisting': True,
                                      'deleteMissing': True},
                           'groups': {'createMissing': True},
                           'hosts': {'createMissing': False,
                                     'updateExisting': False},
                           'httptests': {'createMissing': True,
                                         'updateExisting': True,
                                         'deleteMissing': True},
                           'images': {'createMissing': True,
                                      'updateExisting': True},
                           'items': {'createMissing': True,
                                     'updateExisting': True,
                                     'deleteMissing': True},
                           'maps': {'createMissing': True,
                                    'updateExisting': True},
                           'screens': {'createMissing': True,
                                       'updateExisting': True},
                           'templateLinkage': {'createMissing': True,
                                               'deleteMissing': True},
                           'templates': {'createMissing': True,
                                         'updateExisting': True},
                           'templateScreens': {'createMissing': True,
                                               'updateExisting': True,
                                               'deleteMissing': True},
                           'triggers': {'createMissing': True,
                                        'updateExisting': True,
                                        'deleteMissing': True},
                           'valueMaps': {'createMissing': True,
                                         'updateExisting': True}
                          }
                   )

def zabbix_import_templates(template_files):
    """ imports template json-files from list 'template_files' """

    LOGGER.info('Resolving template dependencies and import order...')
    dependencies = dict()
    filepaths = dict()

    # Read template files and build dependency map
    for template_file in template_files:
        with open(template_file, 'r') as f:
            template_json = json.load(f)

        for template in template_json['zabbix_export']['templates']:
            filepaths.update({template['name']: template_file})
            if "templates" in template:
                dependencies.update({template['name']: \
                    {v for d in template['templates'] \
                        for k, v in d.items() if k == 'name'}})
            else:
                dependencies.update({template['name']: {}})

    LOGGER.debug('Template filepaths:\n %s', filepaths)
    LOGGER.debug('Dependency list:\n %s', dependencies)

    import_order = resolve_dependencies(dependencies)
    LOGGER.debug('Import order:\n %s', import_order)
    for templates in import_order:
        for template in templates:
            try:
                LOGGER.info('Importing template %s', filepaths[template])
                import_template(filepaths[template])
            except KeyError as err:
                LOGGER.warning(
                    'Skipping dependent template %s, ' + \
                    'as it was not changed or included in export group %s',
                    err,
                    ZABBIX_TEMPLATE_EXPORT_GROUP)
                pass
            except Exception as err:
                LOGGER.error('Failed importing template %s due to error: %s. Skipping template.',
                             template, err)
                pass

def zabbix_remove_templates(template_files):
    """ removes given 'templates' list from Zabbix """

    # Build list of template names
    templates = dict()
    for template_file in template_files:
        with open(template_file, 'r') as f:
            template_json = json.load(f)
        templates.update({template['name']: template_file \
            for template in template_json['zabbix_export']['templates']})

    logging.debug('Looking up template ID\'s...')
    templateinfo = ZAPI.template.get(filter={'name': [k for k, v in templates.items()]},
                                     output=['templateid', 'name'])
    LOGGER.debug('Deleting templates %s from Zabbix', [t['name'] for t in templateinfo])
    #ZAPI.template.delete(*[ t['templateid'] for t in templateinfo ])

def merge_templates(templates, filename):
    """ Merges all template-files in list to a single template-file """

    merged_template = None

    # Read all templates
    for t in templates:
        LOGGER.debug('Merging template %s', t)
        with open(t, 'r') as f:
            template_json = json.load(f)

        if not merged_template:
            merged_template = template_json
        else:
            merged_template['zabbix_export']['groups'] += \
                [g for g in template_json['zabbix_export']['groups'] \
                    if g not in merged_template['zabbix_export']['groups']]
            merged_template['zabbix_export']['templates'] += \
                template_json['zabbix_export']['templates']
            merged_template['zabbix_export']['triggers'] += \
                template_json['zabbix_export']['triggers']
            merged_template['zabbix_export']['value_maps'] += \
                [v for v in template_json['zabbix_export']['value_maps'] \
                    if v not in merged_template['zabbix_export']['value_maps']]

    # write merged export-file
    with open(filename, 'w') as f:
        f.write(json.dumps(merged_template, indent=4))

def resolve_dependencies(deplist):
    """ Sorts the dependency dictionary 'deplist',
        where the values are the dependencies of their respective keys. """

    d = dict((k, set(deplist[k])) for k in deplist)
    r = []
    while d:
        # values not in keys (items without dep)
        t = set(i for v in d.values() for i in v)-set(d.keys())
        # and keys without value (items without dep)
        t.update(k for k, v in d.items() if not v)
        # can be done right away
        r.append(t)
        # and cleaned up
        d = dict(((k, v-t) for k, v in d.items() if v))
    return r

def git_clone_repo(path):
    """ Clones a remote repository locally and does a branch
        checkout. If the specified branch does not exist,
        it will be created and committed. """

    repo = pygit2.clone_repository(GIT_URL, path, callbacks=GIT_CALLBACKS)

    repo.branches = pygit2.repository.Branches(repo)
    LOGGER.debug('Git: Branches: %s', list(repo.branches))
    if not f'{GIT_BRANCH}' in repo.branches:
        if not f'origin/{GIT_BRANCH}' in repo.branches:
            LOGGER.warning('Git: Branch %s does not exist. Creating branch...', GIT_BRANCH)
            treeoid = repo.TreeBuilder().write()
            repo.create_commit(f'refs/heads/{GIT_BRANCH}', \
                               GIT_SIGNATURE, GIT_SIGNATURE, 'Initial commit', treeoid, [])
        else:
            LOGGER.warning(
                'Git: Local Branch {0} does not exist. ' + \
                'Creating local branch {0} referencing to origin/{0}...'.format(GIT_BRANCH))
            repo.branches.local.create(
                GIT_BRANCH, 
                repo.branches[f'origin/{GIT_BRANCH}'].peel(pygit2.Commit))
    LOGGER.debug('Git: Branches: %s', list(repo.branches))

    LOGGER.info('Git: Checking out branch %s', GIT_BRANCH)
    repo.checkout(repo.branches[GIT_BRANCH])

    return repo

def construct_commit_msg(changes):
    """ Try to formulate a meaningfull commit message based on given changes """

    # Construct commit message
    status_str = {pygit2.GIT_STATUS_INDEX_NEW: "Added ", \
                  pygit2.GIT_STATUS_INDEX_MODIFIED: "Updated ", \
                  pygit2.GIT_STATUS_INDEX_DELETED: "Removed "}
    status_str2 = {pygit2.GIT_STATUS_INDEX_NEW: " additions", \
                   pygit2.GIT_STATUS_INDEX_MODIFIED: " updates", \
                   pygit2.GIT_STATUS_INDEX_DELETED: " removals"}

    commit_msg = ''
    if len(changes) > 1:
        commit_msg = "Performed %d" % len(changes)
        commit_msg += status_str2[changes[0][1]] \
                      if len(set([flags for filepath, flags in changes])) == 1 \
                      else " changes"
        common_path = os.path.commonpath([filepath for filepath, flags in changes])
        commit_msg += " in %s hostgroup\n\n" % common_path if common_path else "\n\n"
    for c in changes:
        commit_msg += status_str[c[1]] + os.path.basename(c[0]).replace('.json', '') + '\n'

    return commit_msg

def git_commit_and_push(repo):
    """ Commits all pending changes and pushes the branch to origin """

    # Check for changes in the templates
    changes = [(filepath, flags) \
        for filepath, flags in repo.status().items() \
            if flags != pygit2.GIT_STATUS_CURRENT]
    LOGGER.debug('Changes: %s', changes)

    if changes:
        commit_msg = construct_commit_msg(changes)
        LOGGER.debug('Commit message: %s', commit_msg)

        # Commit and push changes
        LOGGER.info('Git: Committing %d changes' % len(changes))
        branch = repo.lookup_branch(GIT_BRANCH)
        treeoid = repo.index.write_tree()
        repo.create_commit(f'refs/heads/{GIT_BRANCH}', GIT_SIGNATURE,
                           GIT_SIGNATURE, commit_msg, treeoid, [branch.target])

        LOGGER.info('Git: Pushing changes to origin')
        repo.remotes['origin'].push([f'refs/heads/{GIT_BRANCH}'], callbacks=GIT_CALLBACKS)
    else:
        LOGGER.info('No changes where found. Nothing to commit.')
