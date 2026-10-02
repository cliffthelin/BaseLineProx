"""Configuration-only recipes and locks. No installation or runtime apply.

Strict allowlists deliberately support only the initial Ubuntu/Chromium contract.
A source hash locks bytes; it does not establish publisher trust or availability.
"""
import hashlib
import json
import re


class RecipeError(ValueError):
    pass


def validate(recipe):
    if not isinstance(recipe,dict) or set(recipe)!={'format','kind','id','platform','source','configuration','state'}:
        raise RecipeError('recipe fields must match the configuration-only contract')
    if recipe['format']!='baseline.recipe/v1' or recipe['kind'] not in ('os','app'):
        raise RecipeError('unsupported recipe format or kind')
    expected_kind={'ubuntu-desktop':'os','ubuntu-server':'os','chromium':'app'}
    if not isinstance(recipe['id'],str) or expected_kind.get(recipe['id'])!=recipe['kind']:
        raise RecipeError('unsupported recipe identity')
    platform=recipe['platform']
    if platform!={'os':'ubuntu','release':'24.04','arch':'amd64'}:
        raise RecipeError('unsupported platform')
    source=recipe['source']
    if (not isinstance(source,dict) or set(source)!={'sha256'}
            or not isinstance(source['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',source['sha256'])):
        raise RecipeError('source requires exactly a lowercase SHA256')
    configuration=recipe['configuration']
    if not isinstance(configuration,dict):raise RecipeError('configuration must be an object')
    if recipe['kind']=='os':
        if set(configuration)!={'locale'} or configuration['locale'] not in ('en_US.UTF-8','en_GB.UTF-8','C.UTF-8'):
            raise RecipeError('unsupported OS configuration')
        allowed=[{'path':'/home','role':'documents','retention':'retained'}]
    else:
        if configuration!={'homepage_role':'environment_console'}:
            raise RecipeError('unsupported application configuration')
        allowed=[{'path':'~/.config/chromium','role':'app_private','retention':'retained'}]
    if recipe['state']!=allowed:
        raise RecipeError('unsupported or incomplete declared state contract')
    return recipe


def export(recipe):
    return json.dumps(validate(recipe),sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n'


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise RecipeError('duplicate JSON field')
        result[key]=value
    return result


def read_document(text):
    if not isinstance(text,str) or len(text)>65536:
        raise RecipeError('recipe document exceeds supported size')
    try:return json.loads(text,object_pairs_hook=_pairs)
    except (ValueError,RecursionError) as exc:
        raise RecipeError('invalid or ambiguous JSON document') from exc


def load(text):
    return validate(read_document(text))


def digest(recipe):
    return hashlib.sha256(export(recipe).encode('ascii')).hexdigest()


def compose(os_recipe, apps):
    validate(os_recipe)
    if os_recipe['kind']!='os' or not isinstance(apps,list):
        raise RecipeError('stack requires an OS and an application list')
    seen=set()
    for app in apps:
        validate(app)
        if app['kind']!='app' or app['id'] in seen:
            raise RecipeError('duplicate or invalid application in stack')
        if app['platform']!=os_recipe['platform']:
            raise RecipeError('incompatible application platform')
        seen.add(app['id'])
    # Copy validated values: later caller mutation cannot silently change this lock.
    return json.loads(json.dumps({'format':'baseline.stack/v1',
            'os':{'recipe':os_recipe,'digest':digest(os_recipe)},
            'apps':[{'recipe':app,'digest':digest(app)} for app in apps], 'runtime_applied':False}))


def verify_stack(stack):
    if (not isinstance(stack,dict) or set(stack)!={'format','os','apps','runtime_applied'}
            or stack['format']!='baseline.stack/v1' or stack['runtime_applied'] is not False
            or not isinstance(stack['apps'],list)):
        raise RecipeError('unsupported stack envelope')
    for item in [stack['os'],*stack['apps']]:
        if not isinstance(item,dict) or set(item)!={'recipe','digest'} or digest(item['recipe'])!=item['digest']:
            raise RecipeError('stack recipe digest mismatch')
    return compose(stack['os']['recipe'],[item['recipe'] for item in stack['apps']])
