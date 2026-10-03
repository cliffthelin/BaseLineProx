import json
import pytest
import vscode_capture as vc
import environment_recipes as er


def test_settings_capture_accepts_jsonc_and_exports_only_portable_values():
    text='''{ // preferences
    "editor.fontSize": 16,
    "editor.insertSpaces": false,
    "editor.wordWrap": "on", /* display */
    "private.token": "must-not-export",
    "terminal.integrated.cwd": "/home/private/project",
    }'''
    result=vc.capture(text)
    assert result['document']['settings']=={'editor.fontSize':16,'editor.insertSpaces':False,'editor.wordWrap':'on'}
    assert result['excluded_count']==2
    assert 'must-not-export' not in json.dumps(result) and '/home/private' not in json.dumps(result)
    assert not result['test_install_verified'] and not result['sources_verified']


@pytest.mark.parametrize('text',[
    '{"editor.fontSize":true}', '{"editor.fontSize":1000}',
    '{"editor.wordWrap":"private-secret"}',
    '{"editor.tabSize":2,"editor.tabSize":4}',
    '{/* unfinished', '{"editor.wordWrap":"on"', '[]',
])
def test_invalid_or_ambiguous_settings_are_refused(text):
    with pytest.raises(er.RecipeError):vc.capture(text)


def test_comment_markers_inside_strings_do_not_change_parsing_or_leak_values():
    result=vc.capture('{"unknown":"https://private/*text*/", "editor.tabSize":4}')
    assert result['excluded_count']==1 and result['document']['settings']=={'editor.tabSize':4}
    assert 'private' not in vc.export(result['document'])


def test_human_web_preview_exports_only_approved_settings():
    from test_recipe_web import case
    c=case()
    try:
        assert b'Preview VS Code settings' in c.get('/recipes')[1]
        status,result=c.post_json('/recipes/action',{'action':'capture_vscode','document':'{"editor.fontSize":18,"secret":"private-value"}'})
        assert status==200,result
        assert json.loads(result['export_json'])['settings']=={'editor.fontSize':18}
        assert result['excluded_count']==1 and 'private-value' not in json.dumps(result)
    finally:c.close()


def test_settings_can_be_staged_into_exclusively_new_profile_without_overwriting_original(tmp_path):
    original=tmp_path/'original';original.mkdir();(original/'keep').write_text('original content')
    artifact=vc.capture('{"editor.fontSize":18,"editor.insertSpaces":false}')['document']
    target=tmp_path/'fresh'
    settings=vc.stage_fresh(artifact,target)
    assert json.loads(settings.read_text())==artifact['settings']
    with pytest.raises(er.RecipeError):vc.stage_fresh(artifact,original)
    assert (original/'keep').read_text()=='original content'


def test_capture_and_fresh_stage_are_available_without_developer_python(tmp_path):
    import subprocess
    from pathlib import Path
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-vscode-settings'
    source=tmp_path/'settings.json';source.write_text('{"editor.tabSize":4,"secret":"excluded"}')
    captured=subprocess.run(['python3',str(cli),'capture',str(source)],capture_output=True,text=True)
    assert captured.returncode==0,captured.stderr
    artifact=tmp_path/'artifact.json';artifact.write_text(json.dumps(json.loads(captured.stdout)['document']))
    result=subprocess.run(['python3',str(cli),'stage',str(artifact),str(tmp_path/'fresh')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads((tmp_path/'fresh/User/settings.json').read_text())=={'editor.tabSize':4}
