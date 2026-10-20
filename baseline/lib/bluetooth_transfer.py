"""Explicit, opaque transfer of parent BlueZ state to an offline child's USER_ADMIN.

Controller addresses are preserved: imported pairings require the original controller.
Never print or parse pairing keys. Existing different child state is refused.
"""
from pathlib import Path
import filecmp
import os
import shutil
import tempfile


class TransferError(RuntimeError):
    pass


def _files(root):
    if root.is_symlink() or not root.is_dir():
        raise TransferError('Bluetooth source or destination is not a plain directory')
    files = set()
    for base, dirs, names in os.walk(root):
        for name in dirs + names:
            path = Path(base) / name
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise TransferError('Bluetooth state contains a link or special file; transfer refused')
        files.update((Path(base) / name).relative_to(root) for name in names)
    return files


def seed(source, user_admin):
    source, admin = Path(source), Path(user_admin)
    if admin.is_symlink() or not admin.is_dir():
        raise TransferError('the mounted USER_ADMIN directory is required')
    files = _files(source)
    if not any(p.name == 'info' and len(p.parts) == 3 for p in files):
        raise TransferError('parent has no stored Bluetooth devices to transfer')
    dest = admin / 'var-lib-bluetooth'
    if dest.exists() or dest.is_symlink():
        if _files(dest) == files and all(filecmp.cmp(source / p, dest / p, shallow=False) for p in files):
            return {'state': 'already present'}
        raise TransferError('child has different Bluetooth state; existing settings were preserved')
    with tempfile.TemporaryDirectory(prefix='.bluetooth-transfer-', dir=admin) as work:
        staged = Path(work) / 'state'
        shutil.copytree(source, staged, symlinks=True)
        if _files(staged) != files or any(not filecmp.cmp(source / p, staged / p, shallow=False) for p in files):
            raise TransferError('parent Bluetooth state changed during transfer; retry')
        for base, dirs, names in os.walk(staged):
            os.chmod(base, 0o700)
            for name in names:
                os.chmod(Path(base) / name, 0o600)
        # Refuse a concurrently created destination, including an empty directory.
        if dest.exists() or dest.is_symlink():
            raise TransferError('child Bluetooth state appeared during transfer; retry')
        staged.rename(dest)
    return {'state': 'copied', 'controller_identity_preserved': True}
