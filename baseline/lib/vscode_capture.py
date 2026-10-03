"""Portable VS Code settings preview; never reads accounts, projects or profiles.

Input is a user-selected settings.json document, not an entire .vscprofile export.
Unknown values are excluded, not echoed. No install or app-runtime proof.
"""
import json
import environment_recipes as er

RULES={
    'editor.fontSize':lambda v:type(v) is int and 6<=v<=72,
    'editor.tabSize':lambda v:type(v) is int and 1<=v<=16,
    'editor.insertSpaces':lambda v:type(v) is bool,
    'editor.wordWrap':lambda v:v in ('off','on','wordWrapColumn','bounded'),
    'files.autoSave':lambda v:v in ('off','afterDelay','onFocusChange','onWindowChange'),
}


def _jsonc(text):
    if not isinstance(text,str) or len(text)>65536:
        raise er.RecipeError('settings document exceeds supported size')
    output=[];i=0;quoted=False;escaped=False
    while i<len(text):
        c=text[i]
        if quoted:
            output.append(c)
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
            i+=1;continue
        if c=='"':quoted=True;output.append(c);i+=1;continue
        if text.startswith('//',i):
            end=text.find('\n',i+2);i=len(text) if end<0 else end;output.append(' ');continue
        if text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0:raise er.RecipeError('unterminated settings comment')
            output.append(' ');i=end+2;continue
        if c==',':
            # Remove trailing commas after stripping comments in a second pass.
            output.append(c);i+=1;continue
        output.append(c);i+=1
    text=''.join(output);output=[];quoted=False;escaped=False
    for i,c in enumerate(text):
        if not quoted and c==',' and text[i+1:].lstrip().startswith(('}',']')):continue
        output.append(c)
        if escaped:escaped=False
        elif quoted and c=='\\':escaped=True
        elif c=='"':quoted=not quoted
    return ''.join(output)


def capture(text):
    settings=er.read_document(_jsonc(text))
    if not isinstance(settings,dict):raise er.RecipeError('settings must be a JSON object')
    approved={}
    for key,value in settings.items():
        if key in RULES:
            if not RULES[key](value):raise er.RecipeError('unsupported value for '+key)
            approved[key]=value
    document={'format':'baseline.vscode-settings/v1','settings':approved}
    return {'document':document,'excluded_count':len(settings)-len(approved),
            'sources_verified':False,'test_install_verified':False,'runtime_applied':False}


def export(document):
    if not isinstance(document,dict) or set(document)!={'format','settings'} or document['format']!='baseline.vscode-settings/v1':
        raise er.RecipeError('unsupported VS Code settings envelope')
    checked=capture(json.dumps(document['settings']))
    if checked['excluded_count']:raise er.RecipeError('unapproved settings in exported artifact')
    return json.dumps(checked['document'],sort_keys=True,separators=(',',':'))+'\n'


def stage_fresh(document,target):
    """Stage native settings in a new user-data directory. Not app readiness."""
    from pathlib import Path
    import os
    approved=json.loads(export(document))['settings']
    target=Path(target)
    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise er.RecipeError('requires a new profile with no redirected ancestors')
    try:target.mkdir(mode=0o700)
    except FileExistsError as exc:raise er.RecipeError('profile already exists') from exc
    user=target/'User';user.mkdir(mode=0o700)
    settings=user/'settings.json'
    with settings.open('x') as stream:
        os.chmod(settings,0o600);json.dump(approved,stream,sort_keys=True,indent=2)
        stream.flush();os.fsync(stream.fileno())
    return settings
