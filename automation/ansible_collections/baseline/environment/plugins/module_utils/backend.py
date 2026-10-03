"""Verify the deployed backend used by a registered task."""
import hashlib
import re
from pathlib import Path

PATHS={'baseline-apps':Path('/opt/baseline/bin/baseline-apps'),
       **{name:Path('/opt/baseline/lib')/name for name in ('application_bundle.py','environment_recipes.py','vscode_capture.py','vscode_build.py')}}


def verify_backend(module,expected,*,paths=None,require_root=True):
    paths=PATHS if paths is None else paths
    if not isinstance(expected,dict) or set(expected)!=set(paths):module.fail_json(msg='Backend fingerprint fields differ')
    actual={}
    for name,path in paths.items():
        if not isinstance(expected[name],str) or not re.fullmatch('[0-9a-f]{64}',expected[name]):module.fail_json(msg='Invalid backend fingerprint')
        path=Path(path)
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file():
            module.fail_json(msg='Missing or redirected Baseline backend file')
        if require_root:
            for entry in (path,*path.parents):
                st=entry.stat()
                if st.st_uid!=0 or st.st_mode&0o022:module.fail_json(msg='Baseline backend is not protected by administrator ownership')
        with path.open('rb') as stream:actual[name]=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual[name]!=expected[name]:module.fail_json(msg='Baseline backend revision differs from recipe; deploy matching software first')
    return actual
