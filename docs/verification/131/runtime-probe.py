from pathlib import Path
import json,subprocess,time
root=Path('/tmp/baseline-vscode-proof131/fresh')
settings=root/'profile/User/settings.json';local=json.loads(settings.read_text());local['telemetry.telemetryLevel']='off';local['update.mode']='none';settings.write_text(json.dumps(local))
ext=root/'probe';ext.mkdir();out=root/'effective.json'
(ext/'package.json').write_text(json.dumps({'name':'baseline-settings-proof','publisher':'baseline-proof','version':'0.0.1','engines':{'vscode':'^1.90.0'},'activationEvents':['*'],'main':'./extension.js'}))
(ext/'extension.js').write_text("const vscode=require('vscode');const fs=require('fs');exports.activate=()=>{const editor=vscode.workspace.getConfiguration('editor');const files=vscode.workspace.getConfiguration('files');fs.writeFileSync("+json.dumps(str(out))+",JSON.stringify({fontSize:editor.get('fontSize'),tabSize:editor.get('tabSize'),insertSpaces:editor.get('insertSpaces'),wordWrap:editor.get('wordWrap'),autoSave:files.get('autoSave')}));setTimeout(()=>vscode.commands.executeCommand('workbench.action.quit'),2000)};")
with (root/'runtime.log').open('w') as log:
    process=subprocess.Popen(['xvfb-run','-a',str(root/'application/VSCode-linux-x64/bin/code'),'--user-data-dir',str(root/'profile'),'--extensions-dir',str(root/'empty-extensions'),'--extensionDevelopmentPath',str(ext),'--new-window','--disable-gpu','--wait'],stdout=log,stderr=log)
    for _ in range(90):
        if out.exists():break
        if process.poll() is not None:raise RuntimeError('VS Code exited before effective-settings proof; inspect '+str(root/'runtime.log'))
        time.sleep(1)
    else:raise RuntimeError('No actual VS Code settings proof; inspect '+str(root/'runtime.log'))
    effective=json.loads(out.read_text());assert effective=={'fontSize':18,'tabSize':4,'insertSpaces':False,'wordWrap':'on','autoSave':'off'},effective
    process.wait(timeout=30)
proof={'environment':'Fresh publisher Linux archive installation, separate profile and Xvfb; not managed VM or isolation proof',
       'version':subprocess.check_output([str(root/'application/VSCode-linux-x64/bin/code'),'--version'],text=True).splitlines(),
       'effective_settings':effective,
       'probe':'Temporary development extension read actual workspace configuration API and quit application',
       'scope':'No original user profile read; no account login; Spotify/VM rebuild/isolation unverified'}
folder=Path('docs/verification/131');folder.mkdir(exist_ok=True);(folder/'live-vscode.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
