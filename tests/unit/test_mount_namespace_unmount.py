import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "baseline/bin/baseline-independent-drive-install"
LOADER = SourceFileLoader("baseline_independent_drive_install", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_unmount_uses_nsenter_for_the_recorded_mount_namespace(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return "result"

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.unmount_in_mount_namespace("1224", "/tmp/baseline-pc401-target")

    assert result == "result"
    assert calls == [(
        ["nsenter", "--target", "1224", "--mount", "--root=/proc/1/root", "--", "/usr/bin/python3", "-c",
         "import ctypes,os,sys; libc=ctypes.CDLL(None,use_errno=True); result=libc.umount2(os.fsencode(sys.argv[1]),0); errno=ctypes.get_errno(); print('umount2 errno='+str(errno)+' '+os.strerror(errno) if result else 'unmounted'); sys.exit(0 if result==0 else 1)",
         "/tmp/baseline-pc401-target"],
        {"capture_output": True, "text": True, "timeout": 30},
    )]


def test_collapse_holders_keeps_each_namespace_and_mountpoint_once():
    class Namespace:
        def __init__(self, inode):
            self.st_ino = inode

    identities = {"10": 100, "11": 100, "20": 200}
    holders = [
        {"pid": "10", "mountpoint": "/target"},
        {"pid": "11", "mountpoint": "/target"},
        {"pid": "20", "mountpoint": "/target"},
        {"pid": "20", "mountpoint": "/target/boot"},
    ]

    result = MODULE.collapse_mount_namespace_holders(
        holders, lambda path: Namespace(identities[path.split("/")[2]])
    )

    assert result == [
        {"pid": "10", "mountpoint": "/target"},
        {"pid": "20", "mountpoint": "/target"},
        {"pid": "20", "mountpoint": "/target/boot"},
    ]


def test_mount_probe_enters_target_namespace_and_root(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return MODULE.subprocess.CompletedProcess(argv, 0, "probe", "")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.probe_mount_namespace("1224", "/tmp/baseline-pc401-target")

    assert result == "probe"
    assert calls == [[
        "nsenter", "--target", "1224", "--mount", "--root", "--",
        "findmnt", "-rn", "-M", "/tmp/baseline-pc401-target",
        "-o", "ID,PARENT,PROPAGATION,FSROOT,MAJ:MIN,TARGET,SOURCE,FSTYPE",
    ]]
