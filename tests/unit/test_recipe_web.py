import json
import settings_web as sw
from test_baseline_web import _RealServerCase, _base_deps
from test_environment_recipes import os_recipe, app_recipe
import environment_recipes as er


def case(role='admin'):
    sessions=sw.SessionStore();sessions.create('test-user',1700000000.0,role=role)
    return _RealServerCase(_base_deps(sessions=sessions))


def test_admin_can_validate_export_and_compose_through_actual_http():
    c=case()
    try:
        status,page=c.get('/recipes')
        assert status==200 and b'Validate recipe' in page and b'Export validated JSON' in page
        assert b'not deployed' in page and b'Sources have not been verified' in page
        status,result=c.post_json('/recipes/action',{'action':'validate','document':er.export(os_recipe())})
        assert status==200 and result['digest']==er.digest(os_recipe())
        assert er.load(result['export_json'])==os_recipe()
        status,result=c.post_json('/recipes/action',{'action':'compose','document':er.export(os_recipe()),'app_document':er.export(app_recipe())})
        assert status==200 and er.verify_stack(json.loads(result['export_json']))['runtime_applied'] is False
    finally:c.close()


def test_recipe_controls_refuse_limited_and_anonymous_sessions():
    c=case('operator')
    try:
        assert c.get('/recipes')[0]==403
        assert c.post_json('/recipes/action',{'action':'validate','document':er.export(os_recipe())})[0]==403
        c.token='not-a-session'
        assert c.post_json('/recipes/action',{'action':'validate','document':er.export(os_recipe())})[0]==401
    finally:c.close()


def test_http_rejects_private_fields_ambiguous_input_and_stack_tampering():
    c=case()
    try:
        private=os_recipe();private['password']='must-not-export'
        for body in ({'action':'validate','document':json.dumps(private)},
                     {'action':'validate','document':'{"kind":"os","kind":"app"}'},
                     {'action':'validate','document':[]},
                     {'action':'build','document':er.export(os_recipe())}):
            status,result=c.post_json('/recipes/action',body)
            assert status==400 and not result['ok'] and 'export_json' not in result
            assert 'must-not-export' not in json.dumps(result)
        stack=er.compose(os_recipe(),[app_recipe()]);stack['os']['digest']='0'*64
        assert c.post_json('/recipes/action',{'action':'verify','document':json.dumps(stack)})[0]==400
        valid=er.compose(os_recipe(),[app_recipe()])
        status,result=c.post_json('/recipes/action',{'action':'verify','document':json.dumps(valid)})
        assert status==200 and not result['sources_verified'] and not result['runtime_applied']
    finally:c.close()
