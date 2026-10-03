"""Backup of everything on the SK hynix drives to a separate drive (v0.2 row 56).

The one deliberate write outside the SK hynix drives, and it is strictly ADD-ONLY
(direct instruction, 2026-10-01: "you can add to that folder, nothing else; no
deleting or replacement"). Baseline may create new files and folders inside
`<destination>/baseline-backups/`. It never deletes, overwrites, renames, replaces or
modifies anything: not its own files, not yours. There is no retention or cleanup code
at all. Real files and real `tar` on a temp directory; only drive identity
(findmnt / lsblk / udevadm) is scripted."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import offdrive_backup as ob


@pytest.fixture(autouse=True)
def _asked_by_the_web_app(monkeypatch):
    """These tests exercise the backup itself; each call carries a genuinely signed web origin."""
    import web_origin_helper as woh
    gate = woh.configured_gate()
    for name in ("run_backup", "main"):
        real = getattr(ob, name)

        def wrapper(*a, _real=real, **kw):
            kw.setdefault("origin", woh.origin_for("backup_offdrive", {"dry_run": kw.get("dry_run", False),
                                                                        "force": kw.get("force", False)}, gate=gate))
            return _real(*a, **kw)
        monkeypatch.setattr(ob, name, wrapper)


ALLOWED = frozenset({"MD89N41071210AP4E", "FD01N6557110C271B"})   # the two SK hynix drives
MEDIA_SERIAL = "JEHBBVWM"
DEFAULT_CHAIN = (("sdj1", "part"), ("sdj", "disk"))


class ScriptedRun:
    """Scripts findmnt / lsblk / udevadm; anything else runs for real."""

    def __init__(self, mountpoint, *, source="/dev/sdj1", fstype="exfat", options="rw,relatime",
                 chain=DEFAULT_CHAIN, serials=None):
        self.mountpoint, self.source, self.fstype, self.options = str(mountpoint), source, fstype, options
        self.chain = list(chain)
        self.serials = serials if serials is not None else {"sdj": MEDIA_SERIAL}

    def __call__(self, argv, timeout=60):
        if argv[0] == "findmnt":
            out = f'TARGET="{self.mountpoint}" SOURCE="{self.source}" FSTYPE="{self.fstype}" OPTIONS="{self.options}"\n'
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if argv[0] == "lsblk":
            return SimpleNamespace(returncode=0, stdout="".join(f"{n} {t}\n" for n, t in self.chain), stderr="")
        if argv[0] == "udevadm":
            name = argv[-1].split("=", 1)[1].rsplit("/", 1)[-1]
            serial = self.serials.get(name)
            return SimpleNamespace(returncode=0, stdout=f"ID_SERIAL_SHORT={serial}\n" if serial else "", stderr="")
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def dest_root(tmp_path):
    """A stand-in for the 10 TB drive's backup folder, with the user's own files already in it."""
    root = tmp_path / "10TB" / "backup"
    (root / "movies").mkdir(parents=True)
    (root / "movies" / "keep.mp4").write_bytes(b"precious media " * 1000)
    (root / "$I4NQOYX.mp4").write_bytes(b"recycle record")
    (root / "notes.txt").write_text("my notes")
    return root


@pytest.fixture
def sources(tmp_path):
    src = tmp_path / "srcvol"
    (src / "state").mkdir(parents=True)
    (src / "state" / "a.txt").write_text("alpha")
    (src / "b.bin").write_bytes(os.urandom(4096))
    return {"baseline-volumes": [str(src)]}


def _dest(dest_root, **kw):
    return ob.resolve_destination(str(dest_root), run=ScriptedRun(dest_root, **kw), allowed_serials=ALLOWED)


def _snapshot(root, *, skip=("baseline-backups",)):
    out = {}
    for p in sorted(root.rglob("*")):
        if any(s in p.parts for s in skip):
            continue
        st = p.stat()
        out[str(p.relative_to(root))] = (p.read_bytes() if p.is_file() else None, st.st_mtime_ns, st.st_mode)
    return out


def _make(d, sources, now=1_800_000_000.0):
    return ob.create_backup_set(d, sources, now=now)


# --- the destination must be a real, separate, safe drive -------------------

def test_a_mounted_separate_drive_is_accepted_and_the_backup_dir_is_inside_it(dest_root):
    d = _dest(dest_root)
    assert str(d.backup_dir) == str(dest_root / "baseline-backups")
    assert d.serial == MEDIA_SERIAL and d.fstype == "exfat"


def test_validating_the_destination_writes_nothing(dest_root):
    before = _snapshot(dest_root)
    _dest(dest_root)
    assert _snapshot(dest_root) == before and not (dest_root / "baseline-backups").exists()


def test_a_plain_directory_on_the_root_filesystem_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="root filesystem"):
        ob.resolve_destination(str(dest_root), run=ScriptedRun("/"), allowed_serials=ALLOWED)


def test_a_read_only_mount_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="read-only"):
        _dest(dest_root, options="ro,relatime")


def test_a_destination_on_an_sk_hynix_drive_is_refused(dest_root):
    for serial in ALLOWED:
        with pytest.raises(ob.BackupError, match="not separate"):
            _dest(dest_root, serials={"sdj": serial})


def test_a_destination_layered_on_an_sk_hynix_drive_is_refused(dest_root):
    """e.g. an LVM volume whose underlying disk is one of the SK hynix drives."""
    with pytest.raises(ob.BackupError, match="not separate"):
        _dest(dest_root, source="/dev/mapper/pve-data", chain=(("dm-3", "lvm"), ("sdc", "disk")),
              serials={"sdc": "FD01N6557110C271B"})


def test_a_destination_on_an_enrolled_drive_is_refused_like_an_sk_hynix_drive(dest_root):
    """A drive enrolled for Baseline to manage (drive_enrollment.py) is never also its separate backup drive."""
    import drive_enrollment
    drive_enrollment.enroll("S6WRNS0TA12638A", size_bytes=1, model="m", now=0.0)
    with pytest.raises(ob.BackupError, match="not separate"):
        _dest(dest_root, serials={"sdj": "S6WRNS0TA12638A"})


def test_a_drive_whose_identity_cannot_be_read_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="identity"):
        _dest(dest_root, serials={})


def test_a_source_with_no_underlying_disk_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="identity"):
        _dest(dest_root, chain=(("loop0", "loop"),))


def test_the_running_boot_drive_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="boot"):
        ob.resolve_destination(str(dest_root), run=ScriptedRun(dest_root), allowed_serials=ALLOWED,
                               boot_serial=MEDIA_SERIAL)


def test_a_network_or_non_block_source_is_refused(dest_root):
    with pytest.raises(ob.BackupError, match="local"):
        _dest(dest_root, source="server:/export", fstype="nfs")


@pytest.mark.parametrize("bad", ["relative/path", "", "/mnt/../etc", "/does/not/exist-at-all"])
def test_bad_destination_paths_are_refused(bad):
    with pytest.raises(ob.BackupError):
        ob.resolve_destination(bad, run=ScriptedRun("/mnt"), allowed_serials=ALLOWED)


def test_a_symlinked_destination_is_refused(tmp_path, dest_root):
    link = tmp_path / "link"
    link.symlink_to(dest_root)
    with pytest.raises(ob.BackupError, match="symlink"):
        ob.resolve_destination(str(link), run=ScriptedRun(dest_root), allowed_serials=ALLOWED)


def test_a_file_is_not_a_destination(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(ob.BackupError):
        ob.resolve_destination(str(f), run=ScriptedRun(tmp_path), allowed_serials=ALLOWED)


# --- space (nothing can be deleted to make room, so the guard matters) ------

def test_not_enough_free_space_is_refused(dest_root, monkeypatch):
    d = _dest(dest_root)
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (10 * 2**30, 9 * 2**40))
    with pytest.raises(ob.BackupError, match="space"):
        ob.check_space(d, needed_bytes=50 * 2**30)


def test_a_backup_that_would_leave_the_drive_nearly_full_is_refused(dest_root, monkeypatch):
    d = _dest(dest_root)
    total = 9 * 2**40
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (int(total * 0.05), total))
    with pytest.raises(ob.BackupError, match="space"):
        ob.check_space(d, needed_bytes=int(total * 0.03))      # would leave 2% free


def test_enough_space_passes(dest_root, monkeypatch):
    d = _dest(dest_root)
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    ob.check_space(d, needed_bytes=100 * 2**30)


# --- creating a backup set --------------------------------------------------

def test_a_set_is_created_verified_and_named_by_time(dest_root, sources):
    d = _dest(dest_root)
    s = _make(d, sources)
    assert ob.SET_RE.match(s.name) and s.path.parent == d.backup_dir and s.path.is_dir()
    manifest = json.loads((s.path / ob.MANIFEST_NAME).read_text())
    assert manifest["kind"] == ob.MANIFEST_KIND
    for entry in manifest["archives"]:
        data = (s.path / entry["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"]
    assert ob.verify_set(s.path) is True


def test_the_archive_restores_the_original_content(dest_root, sources, tmp_path):
    import tarfile
    s = _make(_dest(dest_root), sources)
    out = tmp_path / "restored"
    out.mkdir()
    with tarfile.open(s.path / "baseline-volumes.tar.gz") as tf:
        tf.extractall(out, filter="data")
    assert (out / sources["baseline-volumes"][0].lstrip("/") / "state" / "a.txt").read_text() == "alpha"


def test_nothing_in_the_folder_is_touched_only_new_things_appear_inside_baseline_backups(dest_root, sources):
    before = _snapshot(dest_root)
    d = _dest(dest_root)
    _make(d, sources)
    assert _snapshot(dest_root) == before            # same bytes, same mtimes, same modes, nothing else added
    assert sorted(p.name for p in dest_root.iterdir() if p.name not in before and "/" not in p.name) == ["baseline-backups"]


def test_the_manifest_is_written_last_so_an_unfinished_set_never_looks_complete(dest_root, sources, monkeypatch):
    d = _dest(dest_root)
    during = []
    real = ob._stream_tar

    def spy(argv, out_file, timeout=None, **kw):
        set_dir = Path(out_file.name).parent
        during.append((set_dir / ob.MANIFEST_NAME).exists())
        return real(argv, out_file, timeout, **kw)

    monkeypatch.setattr(ob, "_stream_tar", spy)
    s = _make(d, sources)
    assert during and not any(during)                      # never present while archives were being written
    assert (s.path / ob.MANIFEST_NAME).exists()


def test_a_set_whose_read_back_checksum_is_wrong_never_gets_a_manifest(dest_root, sources, monkeypatch):
    d = _dest(dest_root)
    monkeypatch.setattr(ob, "_sha256_file", lambda path: "0" * 64)
    with pytest.raises(ob.BackupError, match="checksum"):
        _make(d, sources)
    (failed,) = list(d.backup_dir.iterdir())
    assert not (failed / ob.MANIFEST_NAME).exists() and (failed / ob.INCOMPLETE_NAME).exists()


def test_a_failed_backup_leaves_an_incomplete_marked_set_and_touches_nothing_else(dest_root, sources, monkeypatch):
    d = _dest(dest_root)
    first = _make(d, sources)
    before = _snapshot(dest_root)
    first_files = {p.name: p.read_bytes() for p in first.path.iterdir()}

    def failing_stream(argv, out_file, timeout=None, **kw):
        out_file.write(b"half an archive")
        raise ob.BackupError("tar failed: No space left on device")

    monkeypatch.setattr(ob, "_stream_tar", failing_stream)
    with pytest.raises(ob.BackupError, match="tar"):
        _make(d, sources, now=1_800_000_100.0)
    sets = sorted(p.name for p in d.backup_dir.iterdir())
    assert len(sets) == 2 and first.name in sets                       # the old set is intact, the failed one stays
    failed = d.backup_dir / [s for s in sets if s != first.name][0]
    assert (failed / ob.INCOMPLETE_NAME).exists() and not (failed / ob.MANIFEST_NAME).exists()
    assert {p.name: p.read_bytes() for p in first.path.iterdir()} == first_files
    assert _snapshot(dest_root) == before
    with pytest.raises(ob.BackupError):
        ob.verify_set(failed)                                          # an incomplete set never verifies


def test_a_later_backup_works_after_a_failed_one_and_never_reuses_its_folder(dest_root, sources, monkeypatch):
    d = _dest(dest_root)
    real = ob._stream_tar
    monkeypatch.setattr(ob, "_stream_tar", lambda argv, out_file, timeout=None, **kw: (_ for _ in ()).throw(ob.BackupError("boom")))
    with pytest.raises(ob.BackupError):
        _make(d, sources)
    monkeypatch.setattr(ob, "_stream_tar", real)
    ok = _make(d, sources)                                             # the SAME timestamp second
    assert ob.verify_set(ok.path) is True
    assert len(list(d.backup_dir.iterdir())) == 2


def test_a_colliding_set_name_gets_a_new_name_and_the_existing_set_is_untouched(dest_root, sources):
    d = _dest(dest_root)
    a = _make(d, sources)
    snap = {p.name: p.read_bytes() for p in a.path.iterdir()}
    b = _make(d, sources)                                              # exactly the same second
    assert b.name != a.name and ob.SET_RE.match(b.name)
    assert {p.name: p.read_bytes() for p in a.path.iterdir()} == snap


def test_nothing_is_ever_deleted_renamed_or_replaced_during_a_backup(dest_root, sources, monkeypatch):
    """The strongest check of 'no deleting or replacement': every call that could do either
    raises, and a full backup still succeeds."""
    d = _dest(dest_root)

    def forbidden(*a, **k):
        raise AssertionError("a delete / rename / replace was attempted")

    for target in (os, shutil, Path):
        for name in ("remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "rmtree", "move",
                     "truncate"):
            if hasattr(target, name):
                monkeypatch.setattr(target, name, forbidden)
    s = _make(d, sources)
    assert ob.verify_set(s.path) is True


def test_the_module_contains_no_deletion_rename_or_overwrite_calls_at_all():
    src = Path(ob.__file__).read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for banned in (r"\.unlink\(", r"\.rmdir\(", r"rmtree", r"os\.remove", r"os\.rename", r"os\.replace",
                   r"shutil\.move", r"\.rename\(", r"\.replace\(", r"\.truncate\(", r"removedirs",
                   r"open\([^)]*[\"'](w|a|r\+|wb|ab|w\+)[\"']"):
        assert not re.search(banned, code), f"banned call present: {banned}"
    assert not hasattr(ob, "prune")


def test_files_are_created_exclusively_so_an_existing_file_is_never_overwritten(dest_root, tmp_path):
    existing = tmp_path / "already.txt"
    existing.write_text("original")
    with pytest.raises(FileExistsError):
        ob._create_new_file(existing)
    assert existing.read_text() == "original"


# --- verification -----------------------------------------------------------

def test_verify_detects_a_tampered_archive_without_modifying_anything(dest_root, sources):
    d = _dest(dest_root)
    s = _make(d, sources)
    archive = s.path / "baseline-volumes.tar.gz"
    data = archive.read_bytes()
    os.chmod(archive, 0o666)
    with open(archive, "r+b") as fh:                                   # the TEST tampers; the module never does
        fh.seek(len(data) - 20)
        fh.write(b"X" * 20)
    tampered = archive.read_bytes()
    with pytest.raises(ob.BackupError, match="checksum"):
        ob.verify_set(s.path)
    assert archive.read_bytes() == tampered


def test_verify_fails_when_the_manifest_or_an_archive_is_missing(dest_root, sources):
    s = _make(_dest(dest_root), sources)
    (s.path / "baseline-volumes.tar.gz").unlink()
    with pytest.raises(ob.BackupError):
        ob.verify_set(s.path)
    (s.path / ob.MANIFEST_NAME).unlink()
    with pytest.raises(ob.BackupError, match="manifest"):
        ob.verify_set(s.path)


# --- finding the last good backup (read-only) --------------------------------

def test_list_sets_returns_only_complete_verified_sets_newest_first(dest_root, sources):
    d = _dest(dest_root)
    a = _make(d, sources, now=1_800_000_000.0)
    b = _make(d, sources, now=1_800_100_000.0)
    (d.backup_dir / "baseline-20300101T000000Z").mkdir()               # incomplete lookalike
    (d.backup_dir / "my-own-folder").mkdir()
    names = [s.name for s in ob.list_sets(d)]
    assert names == [b.name, a.name]


def test_is_due_respects_the_minimum_interval_since_the_last_good_set(dest_root, sources):
    d = _dest(dest_root)
    _make(d, sources, now=1_800_000_000.0)
    assert ob.is_due(d, now=1_800_000_000.0 + 3600, min_interval_hours=168) is False
    assert ob.is_due(d, now=1_800_000_000.0 + 169 * 3600, min_interval_hours=168) is True


def test_is_due_is_true_when_there_is_no_backup_yet(dest_root):
    assert ob.is_due(_dest(dest_root), now=1_800_000_000.0, min_interval_hours=168) is True


# --- the whole job ----------------------------------------------------------

def test_the_job_refuses_when_no_destination_is_configured():
    with pytest.raises(ob.BackupError, match="no backup destination"):
        ob.run_backup(destination="", run=ScriptedRun("/mnt"), sources={"x": ["/tmp"]}, now=1.0, allowed_serials=ALLOWED)


def test_the_job_does_everything_in_order_and_records_freshness(dest_root, sources, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    recorded = []
    result = ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources=sources,
                           now=1_800_000_000.0, allowed_serials=ALLOWED, min_interval_hours=0,
                           record_success=lambda targets, now: recorded.append((targets, now)))
    assert result.verified is True and result.set_path.parent == dest_root / "baseline-backups"
    assert recorded == [(sources["baseline-volumes"], 1_800_000_000.0)]


def test_the_job_skips_quietly_when_a_recent_backup_exists(dest_root, sources, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    kw = dict(destination=str(dest_root), run=ScriptedRun(dest_root), sources=sources, allowed_serials=ALLOWED,
              min_interval_hours=168)
    first = ob.run_backup(now=1_800_000_000.0, **kw)
    second = ob.run_backup(now=1_800_000_000.0 + 3600, **kw)
    assert first.skipped is False and second.skipped is True and second.set_path is None
    assert len(list((dest_root / "baseline-backups").iterdir())) == 1


def test_the_job_creates_nothing_when_the_destination_is_refused(dest_root, sources):
    before = _snapshot(dest_root)
    with pytest.raises(ob.BackupError):
        ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root, serials={"sdj": "MD89N41071210AP4E"}),
                      sources=sources, now=1.0, allowed_serials=ALLOWED)
    assert _snapshot(dest_root) == before and not (dest_root / "baseline-backups").exists()


def test_freshness_is_not_recorded_when_the_backup_fails(dest_root, sources, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    monkeypatch.setattr(ob, "_stream_tar", lambda argv, out_file, timeout=None, **kw: (_ for _ in ()).throw(ob.BackupError("boom")))
    recorded = []
    with pytest.raises(ob.BackupError):
        ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources=sources, now=1.0,
                      allowed_serials=ALLOWED, min_interval_hours=0, record_success=lambda t, n: recorded.append(t))
    assert recorded == []


def test_a_source_that_does_not_exist_is_refused_before_anything_is_written(dest_root):
    d = _dest(dest_root)
    with pytest.raises(ob.BackupError, match="source"):
        ob.create_backup_set(d, {"x": ["/definitely/not/here"]}, now=1.0)
    assert not d.backup_dir.exists() or list(d.backup_dir.iterdir()) == []


# --- dry run: the first real run should write nothing --------------------------

def test_a_dry_run_validates_sizes_and_checks_space_but_writes_nothing(dest_root, sources, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    before = _snapshot(dest_root, skip=())
    result = ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources=sources,
                           now=1_800_000_000.0, allowed_serials=ALLOWED, min_interval_hours=0, dry_run=True)
    assert result.set_path is None and result.verified is False and result.skipped is False
    assert "dry run" in result.detail and "nothing was written" in result.detail
    assert _snapshot(dest_root, skip=()) == before and not (dest_root / "baseline-backups").exists()


def test_a_dry_run_still_refuses_a_bad_destination(dest_root, sources):
    with pytest.raises(ob.BackupError, match="not separate"):
        ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root, serials={"sdj": "MD89N41071210AP4E"}),
                      sources=sources, now=1.0, allowed_serials=ALLOWED, dry_run=True)


def test_a_dry_run_does_not_record_freshness(dest_root, sources, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    recorded = []
    ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources=sources, now=1.0,
                  allowed_serials=ALLOWED, min_interval_hours=0, dry_run=True,
                  record_success=lambda t, n: recorded.append(t))
    assert recorded == []



# --- empty space is never backed up; the backup can never exceed the data -----

def _make_sparse(path, apparent=2 * 2**30, data=b"real data"):
    with open(path, "wb") as fh:
        fh.write(data)
        fh.truncate(apparent)


def _du_allocated(path):
    return int(subprocess.run(["du", "-s", "--block-size=1", "--", str(path)], capture_output=True, text=True).stdout.split()[0])


def test_the_size_estimate_counts_data_actually_stored_not_apparent_size(tmp_path):
    vol = tmp_path / "vol"
    vol.mkdir()
    _make_sparse(vol / "vm-disk.raw")                       # looks like 2 GiB, holds a few KB
    est = ob.estimate_bytes({"v": [str(vol)]}, run=ob._default_run)
    assert est < 10 * 2**20, f"estimated {est} bytes for a sparse file of almost no real data"


def test_a_sparse_file_is_archived_without_its_empty_holes_and_restores_sparse(dest_root, tmp_path):
    import tarfile
    vol = tmp_path / "vol"
    vol.mkdir()
    _make_sparse(vol / "vm-disk.raw")
    s = _make(_dest(dest_root), {"vol": [str(vol)]})
    archive = s.path / "vol.tar.gz"
    assert archive.stat().st_size < 1 * 2**20               # not 2 GiB of zeros, even compressed
    out = tmp_path / "restored"
    out.mkdir()
    with tarfile.open(archive) as tf:
        tf.extractall(out, filter="data")
    restored = out / str(vol).lstrip("/") / "vm-disk.raw"
    assert restored.stat().st_size == 2 * 2**30             # same apparent size
    assert restored.stat().st_blocks * 512 < 10 * 2**20     # and still sparse: no space invented
    with open(restored, "rb") as fh:
        assert fh.read(9) == b"real data"


def test_tar_is_asked_for_sparse_handling_and_to_stay_on_one_filesystem(dest_root, sources, monkeypatch):
    seen = []
    real = ob._stream_tar
    monkeypatch.setattr(ob, "_stream_tar", lambda argv, out_file, timeout=None, **kw: seen.append(list(argv)) or real(argv, out_file, timeout, **kw))
    _make(_dest(dest_root), sources)
    argv = seen[0]
    assert "--sparse" in argv and "--one-file-system" in argv and "-czf" in argv


def test_the_archive_is_compressed(dest_root, tmp_path):
    vol = tmp_path / "vol"
    vol.mkdir()
    (vol / "compressible.txt").write_bytes(b"baseline " * 2_000_000)      # 18 MB of repetitive real data
    s = _make(_dest(dest_root), {"vol": [str(vol)]})
    assert (s.path / "vol.tar.gz").stat().st_size < 1 * 2**20


def test_a_backup_can_never_grow_past_the_data_it_is_backing_up(dest_root, tmp_path):
    vol = tmp_path / "vol"
    vol.mkdir()
    (vol / "random.bin").write_bytes(os.urandom(2 * 2**20))              # incompressible: archive is ~2 MiB
    d = _dest(dest_root)
    with pytest.raises(ob.BackupError, match="larger than the data"):
        ob.create_backup_set(d, {"vol": [str(vol)]}, now=1_800_000_000.0, budgets={"vol": 1000})
    (failed,) = list(d.backup_dir.iterdir())
    assert not (failed / ob.MANIFEST_NAME).exists()
    assert (failed / "vol.tar.gz").stat().st_size <= 1000 + 2 * ob._CHUNK    # stopped early, did not run on


def test_a_normal_backup_stays_within_its_budget(dest_root, tmp_path):
    vol = tmp_path / "vol"
    vol.mkdir()
    (vol / "random.bin").write_bytes(os.urandom(2 * 2**20))
    s = _make(_dest(dest_root), {"vol": [str(vol)]})
    assert (s.path / "vol.tar.gz").stat().st_size <= _du_allocated(vol) * 1.02 + 64 * 2**20


def test_the_job_budgets_each_archive_from_the_real_data_and_reports_it(dest_root, tmp_path, monkeypatch):
    vol = tmp_path / "vol"
    vol.mkdir()
    (vol / "random.bin").write_bytes(os.urandom(1 * 2**20))
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    seen = {}
    real = ob.create_backup_set
    monkeypatch.setattr(ob, "create_backup_set", lambda dest, sources, now, budgets=None, **kw: seen.update(b=budgets) or real(dest, sources, now=now, budgets=budgets, **kw))
    ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources={"vol": [str(vol)]}, now=1_800_000_000.0,
                  allowed_serials=ALLOWED, min_interval_hours=0)
    assert set(seen["b"]) == {"vol"} and 1 * 2**20 <= seen["b"]["vol"] < 200 * 2**20


def test_the_dry_run_reports_the_real_data_size_and_that_empty_space_is_not_copied(dest_root, tmp_path, monkeypatch):
    vol = tmp_path / "vol"
    vol.mkdir()
    _make_sparse(vol / "vm-disk.raw")
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    r = ob.run_backup(destination=str(dest_root), run=ScriptedRun(dest_root), sources={"vol": [str(vol)]}, now=1.0,
                      allowed_serials=ALLOWED, min_interval_hours=0, dry_run=True)
    assert "empty space is never copied" in r.detail and r.bytes_written < 10 * 2**20



# --- the installer cache is backed up changes-only ----------------------------

import tarfile as _tarfile

CHANGES = frozenset({"installer-cache"})


@pytest.fixture
def cache(tmp_path):
    """A stand-in for INSTALLER_CACHE: a few big, unchanging installers, a subfolder, a symlink, an empty dir."""
    root = tmp_path / "cache"
    (root / "isos").mkdir(parents=True)
    (root / "isos" / "proxmox.iso").write_bytes(os.urandom(300_000))
    (root / "isos" / "debian.iso").write_bytes(os.urandom(200_000))
    (root / "packages").mkdir()
    (root / "packages" / "lm-sensors.deb").write_bytes(os.urandom(50_000))
    (root / "empty-dir").mkdir()
    (root / "latest.iso").symlink_to("isos/proxmox.iso")
    return root


def _inc(d, cache, now):
    return ob.create_backup_set(d, {"installer-cache": [str(cache)]}, now=now, changes_only=CHANGES)


def _members(set_obj, archive="installer-cache.tar.gz"):
    with _tarfile.open(set_obj.path / archive) as tf:
        return {m.name: m for m in tf.getmembers()}


def _files(members):
    return {n for n, m in members.items() if m.isfile()}


def test_the_first_backup_of_the_cache_copies_everything_once(dest_root, cache):
    d = _dest(dest_root)
    s = _inc(d, cache, 1_800_000_000.0)
    names = _files(_members(s))
    assert {n.rsplit("/", 1)[-1] for n in names} == {"proxmox.iso", "debian.iso", "lm-sensors.deb"}
    entry = s.manifest["archives"][0]
    assert entry["mode"] == "changes-only" and entry["base_set"] is None and entry["changed"] == 3


def test_a_second_backup_with_nothing_changed_copies_no_file_data_at_all(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    assert _files(_members(second)) == set()
    assert (second.path / "installer-cache.tar.gz").stat().st_size < 4096
    entry = second.manifest["archives"][0]
    assert entry["changed"] == 0 and entry["unchanged"] == 3 and entry["base_set"] == first.name
    assert second.manifest["depends_on"] == [first.name]
    files_only = [f for f in entry["files"].values() if f["kind"] == "file"]
    assert len(files_only) == 3 and all(f["stored_in"]["set"] == first.name for f in files_only)


def test_only_new_and_modified_files_are_copied(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    (cache / "isos" / "new.iso").write_bytes(os.urandom(10_000))                       # new
    (cache / "packages" / "lm-sensors.deb").write_bytes(os.urandom(60_000))            # changed size
    second = _inc(d, cache, 1_800_100_000.0)
    assert {n.rsplit("/", 1)[-1] for n in _files(_members(second))} == {"new.iso", "lm-sensors.deb"}
    entry = second.manifest["archives"][0]
    assert entry["changed"] == 2 and entry["unchanged"] == 2


def test_a_file_with_a_new_modification_time_is_treated_as_changed(dest_root, cache):
    d = _dest(dest_root)
    _inc(d, cache, 1_800_000_000.0)
    os.utime(cache / "isos" / "debian.iso", (1_700_000_000, 1_700_000_000))
    second = _inc(d, cache, 1_800_100_000.0)
    assert {n.rsplit("/", 1)[-1] for n in _files(_members(second))} == {"debian.iso"}


def test_an_unchanged_installer_exists_in_exactly_one_set_across_many_backups(dest_root, cache):
    d = _dest(dest_root)
    for i in range(4):
        _inc(d, cache, 1_800_000_000.0 + i * 100_000)
    holders = 0
    for s in ob.list_sets(d):
        holders += sum(1 for n in _files(_members(s)) if n.endswith("proxmox.iso"))
    assert holders == 1


def test_a_file_deleted_from_the_cache_leaves_old_sets_alone_and_drops_out_of_the_new_table(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    first_bytes = (first.path / "installer-cache.tar.gz").read_bytes()
    (cache / "packages" / "lm-sensors.deb").unlink()
    second = _inc(d, cache, 1_800_100_000.0)
    assert not any(k.endswith("lm-sensors.deb") for k in second.manifest["archives"][0]["files"])
    assert (first.path / "installer-cache.tar.gz").read_bytes() == first_bytes        # old set untouched


def test_the_set_verifies_and_so_does_the_whole_chain(dest_root, cache):
    d = _dest(dest_root)
    _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    assert ob.verify_set(second.path) is True
    assert ob.verify_chain(d, second.name) is True


def test_a_chain_with_a_missing_dependency_fails_verification(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    (first.path / "installer-cache.tar.gz").unlink()                                   # the TEST removes it, as a user might
    with pytest.raises(ob.BackupError, match="depend"):
        ob.verify_chain(d, second.name)


def test_if_an_old_set_was_deleted_by_hand_the_next_backup_recopies_those_files(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    shutil_rmtree = __import__("shutil").rmtree
    shutil_rmtree(first.path)                                                          # the user clears an old set
    second = _inc(d, cache, 1_800_100_000.0)
    entry = second.manifest["archives"][0]
    assert entry["changed"] == 3 and entry["unchanged"] == 0 and entry["base_set"] is None
    assert second.manifest.get("depends_on", []) == []
    assert ob.verify_chain(d, second.name) is True


def test_the_cache_can_be_rebuilt_from_the_chain_exactly(dest_root, cache, tmp_path):
    d = _dest(dest_root)
    _inc(d, cache, 1_800_000_000.0)
    (cache / "isos" / "new.iso").write_bytes(os.urandom(10_000))
    (cache / "packages" / "lm-sensors.deb").write_bytes(os.urandom(60_000))
    last = _inc(d, cache, 1_800_100_000.0)
    out = tmp_path / "restored"
    out.mkdir()
    ob.restore_label(d, last.name, "installer-cache", out)
    base = out / str(cache).lstrip("/")
    for p in cache.rglob("*"):
        q = base / p.relative_to(cache)
        if p.is_symlink():
            assert q.is_symlink() and os.readlink(q) == os.readlink(p)
        elif p.is_file():
            assert q.read_bytes() == p.read_bytes(), p.name
        else:
            assert q.is_dir()


def test_restore_never_writes_into_the_backup_drive(dest_root, cache, tmp_path):
    d = _dest(dest_root)
    last = _inc(d, cache, 1_800_000_000.0)
    before = _snapshot(dest_root, skip=())
    with pytest.raises(ob.BackupError):
        ob.restore_label(d, last.name, "installer-cache", dest_root / "movies")        # inside the backup drive: refused
    assert _snapshot(dest_root, skip=()) == before


def test_other_volumes_are_still_backed_up_in_full_each_time(dest_root, sources, cache):
    d = _dest(dest_root)
    srcs = {**sources, "installer-cache": [str(cache)]}
    ob.create_backup_set(d, srcs, now=1_800_000_000.0, changes_only=CHANGES)
    second = ob.create_backup_set(d, srcs, now=1_800_100_000.0, changes_only=CHANGES)
    full = _files(_members(second, "baseline-volumes.tar.gz"))
    assert {n.rsplit("/", 1)[-1] for n in full} == {"a.txt", "b.bin"}                  # full copy again
    assert _files(_members(second)) == set()                                           # cache: changes only


def test_the_job_estimates_only_the_changes_and_the_dry_run_says_so(dest_root, cache, monkeypatch):
    monkeypatch.setattr(ob, "_free_and_total", lambda path: (2 * 2**40, 9 * 2**40))
    kw = dict(destination=str(dest_root), run=ScriptedRun(dest_root), sources={"installer-cache": [str(cache)]},
              allowed_serials=ALLOWED, min_interval_hours=0, changes_only=CHANGES)
    ob.run_backup(now=1_800_000_000.0, **kw)
    r = ob.run_backup(now=1_800_100_000.0, dry_run=True, **kw)
    assert r.bytes_written < 64 * 1024 and "unchanged" in r.detail


def test_the_size_cap_for_a_changes_only_archive_is_based_on_the_changes(dest_root, cache):
    d = _dest(dest_root)
    _inc(d, cache, 1_800_000_000.0)
    (cache / "isos" / "new.iso").write_bytes(os.urandom(500_000))
    with pytest.raises(ob.BackupError, match="larger than the data"):
        ob.create_backup_set(d, {"installer-cache": [str(cache)]}, now=1_800_100_000.0, changes_only=CHANGES,
                             budgets={"installer-cache": 1000})


def test_a_newer_set_pointing_at_a_deleted_older_set_makes_the_next_backup_recopy_those_files(dest_root, cache):
    """set1 holds the data, set2 only points at it, then the user deletes set1 by hand: set3 must not trust set2's
    references (that would silently produce a backup with missing data)."""
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    assert second.manifest["depends_on"] == [first.name]
    __import__("shutil").rmtree(first.path)                                              # the TEST plays the user
    third = _inc(d, cache, 1_800_200_000.0)
    entry = third.manifest["archives"][0]
    assert entry["changed"] == 3 and entry["unchanged"] == 0
    assert third.manifest["depends_on"] == [] and ob.verify_chain(d, third.name) is True
    assert {n.rsplit("/", 1)[-1] for n in _files(_members(third))} == {"proxmox.iso", "debian.iso", "lm-sensors.deb"}


def test_verify_chain_fails_when_a_whole_dependency_set_is_gone(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    __import__("shutil").rmtree(first.path)
    with pytest.raises(ob.BackupError, match="depends on"):
        ob.verify_chain(d, second.name)


def test_deep_chain_verification_detects_a_changed_dependency(dest_root, cache):
    d = _dest(dest_root)
    first = _inc(d, cache, 1_800_000_000.0)
    second = _inc(d, cache, 1_800_100_000.0)
    archive = first.path / "installer-cache.tar.gz"
    data = archive.read_bytes()
    with open(archive, "r+b") as fh:                                                      # the TEST tampers
        fh.seek(len(data) - 10)
        fh.write(b"Z" * 10)
    assert ob.verify_chain(d, second.name) is True                                        # shallow: size unchanged
    with pytest.raises(ob.BackupError, match="checksum"):
        ob.verify_chain(d, second.name, deep=True)
