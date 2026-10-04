"""Row 60: dumps of the Proxmox VMs and containers that live on the PC601's local-lvm are added to a NEW set on the
backup drive with vzdump. Add-only like every backup. All Proxmox commands here are scripted fakes; the vzdump fake
writes its dumps into the set folder it was pointed at."""
import hashlib
import json
from types import SimpleNamespace

import pytest

import offdrive_backup as ob
import web_gate as wg
import web_origin_helper as woh
from test_offdrive_backup import ALLOWED, ScriptedRun, dest_root  # noqa: F401

QM_LIST = "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n       100 web                  running    2048              32.00 1234\n       101 tv                   stopped    1024              16.00 0\n"
PCT_LIST = "VMID       Status     Lock         Name\n200        running                 dns\n"
CONFIGS = {
    ("qm", "100"): "scsi0: local-lvm:vm-100-disk-0,size=32G\nmemory: 2048\n",
    ("qm", "101"): "scsi0: INSTALLER_CACHE:101/vm-101-disk-0.qcow2,size=16G\n",     # lives on the cache: covered elsewhere
    ("pct", "200"): "rootfs: local-lvm:subvol-200-disk-0,size=8G\nhostname: dns\n",
}


@pytest.fixture(autouse=True)
def _backup_destination_capacity(monkeypatch):
    """Capacity belongs to the fake destination, not this machine's /tmp."""
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))


def ok(out=""):
    return SimpleNamespace(returncode=0, stdout=out, stderr="")


class FakeProxmox:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, argv, timeout=60):
        self.calls.append(argv)
        if argv[:2] == ["qm", "list"]:
            return ok(QM_LIST)
        if argv[:2] == ["pct", "list"]:
            return ok(PCT_LIST)
        if argv[0] in ("qm", "pct") and argv[1] == "config":
            return ok(CONFIGS[(argv[0], argv[2])])
        if argv[0] == "vzdump":
            if self.fail:
                return SimpleNamespace(returncode=1, stdout="", stderr="vzdump failed")
            dumpdir = argv[argv.index("--dumpdir") + 1]
            from pathlib import Path
            for vmid in argv[1:argv.index("--dumpdir")]:
                kind = "lxc" if vmid == "200" else "qemu"
                ext = "tar.zst" if kind == "lxc" else "vma.zst"
                (Path(dumpdir) / f"vzdump-{kind}-{vmid}-2026_10_01-12_00_00.{ext}").write_bytes(f"dump of {vmid}".encode() * 100)
                (Path(dumpdir) / f"vzdump-{kind}-{vmid}-2026_10_01-12_00_00.log").write_text("log")
            return ok()
        raise AssertionError(f"unexpected command {argv}")


def run_guests(dest_root, fake=None, **kw):
    fake = fake or FakeProxmox()
    gate = woh.configured_gate()
    dry = kw.get("dry_run", False)
    origin = kw.pop("origin", None) or woh.origin_for("backup_guests", {"dry_run": dry}, gate=gate)
    result = ob.run_guest_backup(destination=str(dest_root), run=ScriptedRun(dest_root), guest_run=fake, now=1_800_000_000.0,
                                 allowed_serials=ALLOWED, origin=origin, **kw)
    return result, fake


def test_only_guests_with_a_disk_on_local_lvm_are_dumped(dest_root):
    result, fake = run_guests(dest_root)
    vz = next(c for c in fake.calls if c[0] == "vzdump")
    assert sorted(vz[1:vz.index("--dumpdir")]) == ["100", "200"]          # 101 lives on the cache
    assert "--dumpdir" in vz and "--all" not in vz and "--prune-backups" not in vz and "--remove" not in vz
    assert result.verified and result.set_path.parent == dest_root / "baseline-backups"


def test_guest_backup_still_refuses_insufficient_destination_capacity(dest_root, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (10 * 2**30, 9 * 2**40))
    fake = FakeProxmox()
    with pytest.raises(ob.BackupError, match="not enough free space"):
        run_guests(dest_root, fake)
    assert not any(c[0] == "vzdump" for c in fake.calls)
    assert not (dest_root / "baseline-backups").exists()


def test_the_set_is_new_verifiable_and_lists_every_dump_with_a_checksum(dest_root):
    result, _ = run_guests(dest_root)
    manifest = json.loads((result.set_path / "MANIFEST.json").read_text())
    assert manifest["content"] == "guests"
    names = {a["name"] for a in manifest["archives"]}
    assert names == {"vzdump-qemu-100-2026_10_01-12_00_00.vma.zst", "vzdump-lxc-200-2026_10_01-12_00_00.tar.zst"}
    for a in manifest["archives"]:
        data = (result.set_path / a["name"]).read_bytes()
        assert a["bytes"] == len(data) and a["sha256"] == hashlib.sha256(data).hexdigest()
    assert ob.verify_set(result.set_path) is True


def test_the_users_own_files_are_untouched(dest_root):
    before = {p: p.read_bytes() for p in dest_root.rglob("*") if p.is_file()}
    run_guests(dest_root)
    assert all(p.read_bytes() == data for p, data in before.items())


def test_a_dry_run_runs_no_vzdump_and_writes_nothing(dest_root):
    result, fake = run_guests(dest_root, dry_run=True)
    assert not any(c[0] == "vzdump" for c in fake.calls)
    assert not (dest_root / "baseline-backups").exists() and "dry run" in result.detail


def test_no_guests_on_local_lvm_means_nothing_to_do(dest_root):
    class Empty(FakeProxmox):
        def __call__(self, argv, timeout=60):
            if argv[:2] in (["qm", "list"], ["pct", "list"]):
                return ok("VMID NAME STATUS\n")
            return super().__call__(argv, timeout)
    result, fake = run_guests(dest_root, Empty())
    assert result.skipped and not (dest_root / "baseline-backups").exists()


def test_a_failed_vzdump_raises_and_nothing_is_cleaned_up(dest_root):
    with pytest.raises(ob.BackupError, match="vzdump"):
        run_guests(dest_root, FakeProxmox(fail=True))
    sets = list((dest_root / "baseline-backups").iterdir())
    assert len(sets) == 1 and (sets[0] / "INCOMPLETE.txt").exists() and not (sets[0] / "MANIFEST.json").exists()


def test_a_guest_set_does_not_make_the_volume_backup_look_recent(dest_root):
    dest = ob.resolve_destination(str(dest_root), run=ScriptedRun(dest_root), allowed_serials=ALLOWED)
    run_guests(dest_root)
    assert ob.is_due(dest, now=1_800_000_000.0 + 60) is True


def test_it_needs_the_web_app(dest_root):
    woh.configured_gate()
    with pytest.raises(wg.NotFromWebApp):
        ob.run_guest_backup(destination=str(dest_root), run=ScriptedRun(dest_root), guest_run=FakeProxmox(), now=1.0,
                            allowed_serials=ALLOWED, origin=None)
    gate = woh.configured_gate()
    wrong = woh.origin_for("backup_offdrive", {"dry_run": False}, gate=gate)
    with pytest.raises(wg.NotFromWebApp):
        ob.run_guest_backup(destination=str(dest_root), run=ScriptedRun(dest_root), guest_run=FakeProxmox(), now=1.0,
                            allowed_serials=ALLOWED, origin=wrong)


def test_a_destination_on_an_sk_hynix_drive_is_still_refused(dest_root):
    with pytest.raises(ob.BackupError):
        ob.run_guest_backup(destination=str(dest_root), run=ScriptedRun(dest_root, serials={"sdj": "MD89N41071210AP4E"}),
                            guest_run=FakeProxmox(), now=1.0, allowed_serials=ALLOWED,
                            origin=woh.origin_for("backup_guests", {"dry_run": False}))


@pytest.mark.parametrize("bad", ["1; rm -rf /", "../x", "", "10a"])
def test_a_guest_id_that_is_not_plain_digits_is_never_passed_to_vzdump(dest_root, bad):
    class Weird(FakeProxmox):
        def __call__(self, argv, timeout=60):
            if argv[:2] == ["qm", "list"]:
                return ok(f"VMID NAME\n{bad or ' '} x\n")
            if argv[:2] == ["pct", "list"]:
                return ok("VMID\n")
            return super().__call__(argv, timeout)
    result, fake = run_guests(dest_root, Weird())
    assert not any(c[0] == "vzdump" for c in fake.calls)
