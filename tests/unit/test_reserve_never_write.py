"""Space is reserved, never written out as if something were in it (operator 2026-10-16: "as long as you're just reserving space that is fine; I do
not want to have to write 48GB as if there is anything in it").

A VM disk is a sparse qcow2 whose size is only a limit; a role volume grows by extending its extents. Nothing in the product may pre-fill, zero or
preallocate space, with ONE named exception: the swap file on the thin SESSION_TEMP volume, written once at a small fixed size so swap can never find
a missing block when the pool is full (host_layout.py). The cap on that exception is part of the rule."""
import re
from pathlib import Path

import pytest

import host_layout
import vm_host as vh
from test_vm_host import FakeHost

REPO = Path(__file__).resolve().parents[2]
SCANNED = [*sorted((REPO / "baseline/lib").glob("*.py")), *sorted(p for p in (REPO / "baseline/bin").iterdir() if p.is_file()),
           REPO / "boot/provision.sh"]
FORBIDDEN = re.compile(r"if=/dev/zero|fallocate|preallocation\s*=|lazy_itable_init\s*=\s*0|lazy_journal_init\s*=\s*0|conv=notrunc")


def _offending():
    found = {}
    for path in SCANNED:
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0]
            if FORBIDDEN.search(code) and "re.compile" not in code:
                found.setdefault(str(path.relative_to(REPO)), []).append(number)
    return found


def test_the_only_pre_filling_writes_in_the_product_are_the_swap_file_makers():
    """Two named sites, one write each: first boot's swap file (host_layout) and the user-chosen `file` kind (swap_config, never run for `reserved`)."""
    offenders = _offending()
    assert sorted(offenders) == ["baseline/lib/host_layout.py", "baseline/lib/swap_config.py"], \
        f"space is being written or preallocated outside the swap file makers: {offenders}"
    assert all(len(lines) == 1 for lines in offenders.values())


def test_the_swap_exception_stays_small_and_fixed():
    assert host_layout.SWAP_SIZE_GIB <= 4, "the first-boot pre-filled file must stay small; reserve space instead of writing it"
    text = (REPO / "baseline/lib/host_layout.py").read_text()
    assert "SESSION_TEMP is a thin volume" in text        # the reason for the exception stays written next to it


@pytest.mark.parametrize("disk_gb", [4, 48, 512])
def test_a_vm_disk_is_a_bare_sparse_qcow2_of_the_requested_size(tmp_path, disk_gb):
    fake = FakeHost(tmp_path / "store")
    fake.host.create_from_iso("vm1", iso="/x.iso", disk_gb=disk_gb, memory_mb=1024, cpus=1)
    creates = [argv for argv in fake.run.calls if argv[:2] == ["qemu-img", "create"]]
    assert len(creates) == 1
    argv = creates[0]
    assert argv[2:4] == ["-f", "qcow2"] and argv[-1] == f"{disk_gb}G"
    assert not [a for a in argv if "prealloc" in a or a == "-o"], f"the disk is preallocated: {argv}"


def test_an_overlay_and_its_user_disk_are_sparse_too(tmp_path):
    fake = FakeHost(tmp_path / "store")
    fake.host.create_from_iso("base-src", iso="/x.iso", disk_gb=4, memory_mb=1024, cpus=1)
    fake.run.calls.clear()
    base = tmp_path / "store" / "bases"
    base.mkdir(parents=True, exist_ok=True)
    (base / "b.qcow2").write_bytes(b"q")
    try:
        fake.host.create_overlay("ov", base="b", memory_mb=1024, cpus=1, persistence_gb=48)
    except vh.VmError:
        pass                                           # the point is the commands issued, not whether this fake base is complete
    for argv in (c for c in fake.run.calls if c[:2] == ["qemu-img", "create"]):
        assert not [a for a in argv if "prealloc" in a], f"preallocated: {argv}"
        assert "-o" not in argv


def test_growing_a_volume_only_extends_it():
    import volume_growth
    argv = volume_growth.lvextend_argv("vg", "baseline_user_personal", 10)
    assert argv == ["lvextend", "-L", "+10G", "-r", "/dev/vg/baseline_user_personal"]
    assert not [a for a in argv if "zero" in a or "wipe" in a]
