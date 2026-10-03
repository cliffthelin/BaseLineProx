"""Registered Ansible roles, configuration-only templates and scoped run evidence.

Expected compatibility is a declaration. Native observations are recorded only
from the registered role's successful execution; injected test runners stay unit.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
import application_bundle as ab
import environment_recipes as er

COMPONENT='baseline.environment.native_suite'
RUNTIME_COMPONENT='baseline.environment.native_runtime'


def collection_root():
    deployed=Path('/opt/baseline/automation')
    return deployed if deployed.is_dir() else Path(__file__).resolve().parents[2]/'automation'


def backend_hashes():
    lib=Path(ab.__file__).parent
    files={'baseline-apps':lib.parent/'bin/baseline-apps',**{name:lib/name for name in ('application_bundle.py','environment_recipes.py','vscode_capture.py','vscode_build.py')}}
    return {name:hashlib.sha256(file.read_bytes()).hexdigest() for name,file in files.items()}


def catalog():
    root=collection_root();role=root/'ansible_collections/baseline/environment'
    expected=[{'os':os_name,'release':release,'arch':'amd64','applications':list(ab.APPS)}
              for os_name,release in [('ubuntu','24.04'),('ubuntu','26.04'),('debian','13')]]
    components=[]
    for component,capability in ((COMPONENT,'materialized'),(RUNTIME_COMPONENT,'dependencies-installed')):
        name=component.rsplit('.',1)[1]
        files=[role/('roles/'+name+'/tasks/main.yml'),role/('roles/'+name+'/meta/argument_specs.yml'),
               role/('plugins/modules/'+name+'.py'),role/'plugins/module_utils/backend.py',Path(ab.__file__),Path(ab.__file__).parent.parent/'bin/baseline-apps']
        digest=hashlib.sha256()
        for file in files:digest.update(file.name.encode());digest.update(file.read_bytes())
        digest.update(json.dumps(backend_hashes(),sort_keys=True).encode())
        variables=({'baseline_suite':'dict','baseline_cache':'absolute-path','baseline_generation':'absolute-path','baseline_data':'absolute-path'}
                   if component==COMPONENT else {'baseline_platform':'dict','baseline_runtime_update':'bool'})
        components.append({'id':component,'revision':digest.hexdigest(),'executor':'ansible-role',
            'classification':['native-deb','native-tar','retained-private-home'] if component==COMPONENT else ['native-prerequisites','administrator-task'],
            'argument_spec':str(role/('roles/'+name+'/meta/argument_specs.yml')),'variables':variables,
            'backend_sha256':backend_hashes(),
            'expected':expected,'capabilities':[capability],
            'limitations':['no GUI/account/recovery proof','system dependencies not byte-locked']})
    return {'format':'baseline.task-catalog/v1','components':components}


def template(suite,*,cache,generation,data,run_as='baseline-admin',with_runtime=False):
    suite=ab.validate_suite(suite)
    literal=json.dumps([suite,cache,generation,data],sort_keys=True)
    if any(token in literal for token in ('{{','{%','{#')):
        raise er.RecipeError('recipe variables must be literal values; registered roles own templating')
    if not isinstance(run_as,str) or not re.fullmatch('[a-z_][a-z0-9_-]{0,31}',run_as) or run_as=='root':
        raise er.RecipeError('application tasks require a named non-root account')
    paths=[]
    for value in (cache,generation,data):
        if not isinstance(value,str) or not Path(value).is_absolute() or any(ord(c)<32 for c in value) or '..' in Path(value).parts:
            raise er.RecipeError('task storage paths must be absolute and contain no control characters')
        paths.append(Path(value))
    for i,path in enumerate(paths):
        if any(path==other or path in other.parents or other in path.parents for other in paths[i+1:]):
            raise er.RecipeError('task cache, generation and data paths overlap')
    if not isinstance(with_runtime,bool):raise er.RecipeError('runtime choice must be boolean')
    plays=[{'name':'Baseline locked native application build','hosts':'baseline_target',
             'gather_facts':False,'become':True,'become_user':run_as,
             'vars':{'baseline_backend_sha256':backend_hashes(),'baseline_suite':suite,'baseline_cache':cache,'baseline_generation':generation,'baseline_data':data},
             'roles':[{'role':COMPONENT}]}]
    if with_runtime:
        plays.insert(0,{'name':'Baseline native runtime prerequisites','hosts':'baseline_target','gather_facts':False,
            'become':True,'become_user':'root','vars':{'baseline_backend_sha256':backend_hashes(),'baseline_platform':suite['platform'],'baseline_runtime_update':False},
            'roles':[{'role':RUNTIME_COMPONENT}]})
    return plays


def validate_playbook(value):
    if not isinstance(value,list) or len(value) not in (1,2) or not all(isinstance(p,dict) for p in value):
        raise er.RecipeError('requires registered Baseline plays')
    play=value[-1]
    if set(play)!={'name','hosts','gather_facts','become','become_user','vars','roles'}:
        raise er.RecipeError('unregistered playbook fields or tasks')
    if (play['hosts']!='baseline_target' or play['gather_facts'] is not False or play['become'] is not True
            or play['roles']!=[{'role':COMPONENT}] or not isinstance(play['vars'],dict)
            or set(play['vars'])!={'baseline_backend_sha256','baseline_suite','baseline_cache','baseline_generation','baseline_data'}):
        raise er.RecipeError('unregistered component, role or variable')
    variables=play['vars']
    canonical=template(variables['baseline_suite'],cache=variables['baseline_cache'],
        generation=variables['baseline_generation'],data=variables['baseline_data'],run_as=play['become_user'],with_runtime=len(value)==2)
    if value!=canonical:raise er.RecipeError('unsupported play fields or prerequisite role variables')
    return canonical


def _database(path):
    path=ab._path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.exists() and not path.is_file():raise er.RecipeError('registry must be a regular file')
    db=sqlite3.connect(path);os.chmod(path,0o600)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('CREATE TABLE IF NOT EXISTS components(id TEXT, revision TEXT, metadata TEXT, PRIMARY KEY(id,revision))')
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started REAL, status TEXT, level TEXT, recipe_digest TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS observations(run_id TEXT REFERENCES runs(id), component TEXT, revision TEXT, payload TEXT)')
    return db


def register_catalog(path):
    value=catalog()
    with _database(path) as db:
        for component in value['components']:
            db.execute('INSERT OR IGNORE INTO components VALUES(?,?,?)',(component['id'],component['revision'],json.dumps(component,sort_keys=True)))
    return value


def compatibility(path):
    with _database(path) as db:
        components=[json.loads(row[0]) for row in db.execute('SELECT metadata FROM components ORDER BY id,revision')]
        observations=[]
        for run,component,revision,payload,level in db.execute('SELECT o.run_id,o.component,o.revision,o.payload,r.level FROM observations o JOIN runs r ON o.run_id=r.id ORDER BY r.started'):
            observations.append({'run_id':run,'component':component,'revision':revision,'level':level,**json.loads(payload)})
        runs=[dict(zip(['id','status','level','recipe_digest'],row)) for row in db.execute('SELECT id,status,level,recipe_digest FROM runs ORDER BY started')]
    current={c['id']:c['revision'] for c in catalog()['components']}
    proven=[o for o in observations if o['level']=='native-install']
    return {'components':components,'observations':observations,
            'proven':proven,'proven_current':[o for o in proven if current.get(o['component'])==o['revision']],
            'runs':runs,'scope':'proven materialization is not GUI, account authentication, full confinement or recovery'}


def execute(playbook,inventory,registry,workspace,*,runner=None,check=False):
    playbook=validate_playbook(playbook);workspace=ab._path(workspace)
    if workspace.exists():raise er.RecipeError('requires a new task workspace')
    value=register_catalog(registry);components={c['id']:c for c in value['components']}
    level='unit-test' if runner is not None else ('check-mode' if check else 'native-install')
    if runner is None:
        try:import ansible_runner
        except ImportError as exc:raise er.RecipeError('Ansible Runner is not installed; use the documented tasker environment') from exc
        runner=ansible_runner.run
    workspace.mkdir(mode=0o700,parents=True);project=workspace/'project';project.mkdir(mode=0o700)
    (project/'recipe.json').write_text(json.dumps(playbook));(project/'recipe.json').chmod(0o600)
    run_id=uuid.uuid4().hex;recipe_digest=hashlib.sha256(json.dumps(playbook,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with _database(registry) as db:db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(run_id,time.time(),'running',level,recipe_digest))
    try:
        environment={'ANSIBLE_COLLECTIONS_PATH':str(collection_root()),'ANSIBLE_HOST_KEY_CHECKING':'True'}
        bindir=Path(sys.executable).parent
        if (bindir/'ansible-playbook').is_file() and os.access(bindir/'ansible-playbook',os.X_OK):
            environment['PATH']=str(bindir)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin')
        result=runner(private_data_dir=str(workspace),playbook='recipe.json',inventory=str(inventory),quiet=True,
                      cmdline='--check' if check else '',envvars=environment)
        current={c['id']:c['revision'] for c in catalog()['components']}
        if any(current.get(name)!=component['revision'] for name,component in components.items()):
            raise er.RecipeError('registered component revision changed during execution; rerun against stable software')
        status='successful' if result.status=='successful' and result.rc==0 else 'failed'
        reports=[];suite=playbook[-1]['vars']['baseline_suite']
        if status=='successful' and not check:
            for event in result.events:
                if event.get('event')!='runner_on_ok':continue
                event_data=event.get('event_data',{})
                report=event_data.get('res',{}).get('compatibility')
                if not report:continue
                if level=='native-install' and report.get('backend_sha256')!=backend_hashes():
                    raise er.RecipeError('target backend evidence differs from registered source')
                if report.get('component')==RUNTIME_COMPONENT:
                    if (len(playbook)!=2 or report.get('platform')!=suite['platform']
                            or report.get('capability')!='dependencies-installed' or report.get('runtime_verified') is not False
                            or not isinstance(report.get('dependencies'),list) or not report['dependencies']):
                        raise er.RecipeError('invalid prerequisite evidence')
                    reports.append({'component':RUNTIME_COMPONENT,'platform':suite['platform'],'application':None,
                        'backend_sha256':report.get('backend_sha256',{}),
                        'instance':event_data.get('host','unclassified-target'),'environment':report.get('environment',{}),
                        'dependencies':report['dependencies'],'capability':'dependencies-installed','runtime_verified':False})
                    continue
                expected={r['app']:r['source'] for r in suite['applications']}
                if (report.get('component')!=COMPONENT or report.get('platform')!=suite['platform']
                        or report.get('suite_digest')!=suite['digest'] or report.get('capability')!='materialized'
                        or report.get('runtime_verified') is not False or set(report.get('applications',{}))!=set(expected)):
                    raise er.RecipeError('task evidence differs from requested OS/application lock')
                for app,observed in report['applications'].items():
                    source=expected[app]
                    if observed.get('version')!=source['version'] or observed.get('source_sha256')!=source['sha256']:
                        raise er.RecipeError('task application evidence differs from source lock')
                    reports.append({'component':COMPONENT,'platform':suite['platform'],'application':app,'version':source['version'],
                        'backend_sha256':report.get('backend_sha256',{}),
                        'instance':event_data.get('host','unclassified-target'),'environment':report.get('environment',{}),
                        'source_sha256':source['sha256'],'medium':source['medium'],'suite_digest':suite['digest'],
                        'capability':'materialized','runtime_verified':False})
            if not reports:raise er.RecipeError('successful runner supplied no verified component evidence')
        with _database(registry) as db:
            db.execute('UPDATE runs SET status=? WHERE id=?',(status,run_id))
            for report in reports:
                component=components[report['component']]
                db.execute('INSERT INTO observations VALUES(?,?,?,?)',(run_id,component['id'],component['revision'],json.dumps(report,sort_keys=True)))
        return {'run_id':run_id,'status':status,'level':level,'observations':len(reports),'runtime_verified':False,'workspace':str(workspace)}
    except Exception:
        with _database(registry) as db:db.execute('UPDATE runs SET status=? WHERE id=?',('failed',run_id))
        raise
