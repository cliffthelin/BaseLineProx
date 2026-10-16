"""Host swap as a setting the user can change, applied safely on a running machine (operator 2026-10-16).

kind "file":     a swap file in SESSION_TEMP, written once at the requested size. SESSION_TEMP is a thin volume, and swap must never find a block
                 missing from a full pool, so this one is written (host_layout's original choice, and still the default).
kind "reserved": a regular volume in the volume group. The space is reserved; none of it is written (operator: "as long as you're just
                 reserving space that is fine"). It does take that space out of what the other volumes can grow into.

A change brings the new swap up before the old one is released, so the host never runs without it in between. If the old one cannot be
released (memory in use), the new one stays, fstab lists only the new one, and the old one is kept until the next restart. Swap this product
does not manage (any other device) is never touched. Nothing here chooses a size for the person: `validate` only refuses what cannot work.
"""
from __future__ import annotations

import re

import drive_installer as di
import volume_growth

GIB = 1024 ** 3
MAX_GIB = 64
KINDS = ("file", "reserved")
SWAP_DIR = "/mnt/SESSION_TEMP"
LEGACY_FILE = f"{SWAP_DIR}/swapfile"          # the file host_layout made at first boot
FSTAB = "/etc/fstab"
_FILE = re.compile(rf"^{re.escape(SWAP_DIR)}/swapfile(-\d+G)?$")


class SwapError(RuntimeError):
    pass


def validate(gib, kind) -> tuple:
    if isinstance(gib, bool) or not isinstance(gib, int) or not 0 <= gib <= MAX_GIB:
        raise ValueError(f"swap must be a whole number of GiB from 0 to {MAX_GIB}")
    if kind not in KINDS:
        raise ValueError("kind must be file or reserved")
    return gib, kind


def file_path(gib: int) -> str:
    return f"{SWAP_DIR}/swapfile-{gib}G"


def lv_name(gib: int) -> str:
    return f"baseline_swap_{gib}g"


def lv_path(vg: str, gib: int) -> str:
    return f"/dev/{vg}/{lv_name(gib)}"


def _managed_lv(vg: str, lv: str) -> bool:
    return lv == "swap" or re.fullmatch(r"baseline_swap_\d+g", lv) is not None


def _logical_name(name: str, vg: str, minors: dict) -> str:
    """/proc/swaps lists a logical volume as /dev/dm-N; map it back to /dev/<vg>/<lv> through the kernel minor numbers."""
    return f"/dev/{vg}/{minors[name]}" if name in minors else name


def _managed(name: str, vg: str) -> bool:
    if _FILE.match(name):
        return True
    m = re.fullmatch(rf"/dev/(?:mapper/)?{re.escape(vg)}[/-](.+)", name)
    return bool(m) and _managed_lv(vg, m.group(1))


def _minors(runner, vg: str) -> dict:
    proc = runner.run(["lvs", "--noheadings", "--separator", ",", "-o", "lv_name,lv_kernel_minor", vg], timeout=30)
    out = {}
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[1].isdigit():
                out[f"/dev/dm-{parts[1]}"] = parts[0]
    return out


def _active(runner, vg: str) -> list:
    proc = runner.run(["swapon", "--noheadings", "--show=NAME,SIZE", "--bytes"], timeout=30)
    if proc.returncode != 0:
        raise SwapError(f"swap devices could not be read: {(proc.stderr or '').strip()[-120:]}")
    minors = _minors(runner, vg)
    rows = []
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1].isdigit():
            rows.append((_logical_name(fields[0], vg, minors), int(fields[1])))
    return rows


def current(runner, vg: str) -> dict:
    ours = [(n, s) for n, s in _active(runner, vg) if _managed(n, vg)]
    if not ours:
        return {"kind": None, "gib": 0, "names": []}
    biggest = max(ours, key=lambda row: row[1])[0]
    kind = "file" if _FILE.match(biggest) else ("proxmox-default" if biggest.endswith("/swap") or biggest.endswith("-swap") else "reserved")
    return {"kind": kind, "gib": round(sum(s for _, s in ours) / GIB), "names": [n for n, _ in ours]}


def _fstab_with(text: str, vg: str, target: str | None) -> str:
    kept = [line for line in text.splitlines()
            if not (line.split() and not line.lstrip().startswith("#") and _managed(line.split()[0], vg))]
    if target:
        kept.append(f"{target} none swap sw 0 0")
    return "\n".join(kept) + "\n"


def _leftovers(runner, vg: str, active: set) -> list:
    """Managed swap files and volumes that exist but are not active (an earlier release that could not finish)."""
    found = []
    try:
        names = runner.listdir(SWAP_DIR)
    except OSError:
        names = []
    for entry in names:
        path = f"{SWAP_DIR}/{entry}"
        if _FILE.match(path) and path not in active:
            found.append(path)
    proc = runner.run(["lvs", "--noheadings", "-o", "lv_name", vg], timeout=30)
    for lv in (proc.stdout.split() if proc.returncode == 0 else []):
        path = f"/dev/{vg}/{lv}"
        if _managed_lv(vg, lv) and path not in active:
            found.append(path)
    return found


def _delete_backing(runner, vg: str, name: str) -> None:
    if name.startswith("/dev/"):
        done = runner.run(["lvremove", "-y", f"{vg}/{name.split('/')[-1]}"], timeout=120)
        if done.returncode != 0:
            raise SwapError(f"{name} could not be removed: {(done.stderr or '').strip()[-120:]}")
    else:
        runner.remove(name)


def _create(runner, vg: str, gib: int, kind: str, ensure_room) -> str:
    if kind == "file":
        target = file_path(gib)
        ensure_room(runner, "SESSION_TEMP", gib * GIB + GIB // 4)
        done = runner.run(["dd", "if=/dev/zero", f"of={target}", "bs=1M", f"count={gib * 1024}", "conv=fsync", "status=none"], timeout=3600)
        if done.returncode != 0:
            runner.remove(target)
            raise SwapError(f"the swap file could not be written: {(done.stderr or '').strip()[-120:]}")
        runner.run(["chmod", "600", target], timeout=15)
    else:
        target = lv_path(vg, gib)
        proc = runner.run(["vgs", "--noheadings", "--units", "b", "--nosuffix", "-o", "vg_free", vg], timeout=30)    # runs as root, like volume_growth
        free = di.parse_vg_free_bytes(proc.stdout) if proc.returncode == 0 else None
        if free is None:
            raise SwapError("the free space of the volume group could not be read")
        if free < gib * GIB + volume_growth.KEEP_FREE:
            have = max(free - volume_growth.KEEP_FREE, 0) // GIB
            raise SwapError(f"not enough room: {gib} GiB wanted but only {have} GiB of the volume group can be reserved")
        done = runner.run(["lvcreate", "-y", "-L", f"{gib}G", "-n", lv_name(gib), vg], timeout=120)
        if done.returncode != 0:
            raise SwapError(f"the swap volume could not be created: {(done.stderr or done.stdout or '').strip()[-120:]}")
    for argv in (["mkswap", target], ["swapon", target]):
        done = runner.run(argv, timeout=120)
        if done.returncode != 0:
            try:
                _delete_backing(runner, vg, target)
            finally:
                raise SwapError(f"{argv[0]} failed: {(done.stderr or done.stdout or '').strip()[-120:]}")
    return target


def apply(runner, vg: str, gib: int, kind: str, *, ensure_room=volume_growth.ensure_room, fstab: str = FSTAB) -> dict:
    gib, kind = validate(gib, kind)
    state = current(runner, vg)
    target = None if gib == 0 else (file_path(gib) if kind == "file" else lv_path(vg, gib))
    notes, retired = [], []
    active_names = set(state["names"])
    # the same kind at the same size is already what was asked for, whatever the file or volume is called (first boot's file is `swapfile`)
    already = target is not None and len(active_names) == 1 and state["kind"] == kind and state["gib"] == gib
    if already:
        target = next(iter(active_names))
    leftovers = [n for n in _leftovers(runner, vg, active_names) if n != target]
    if already and not leftovers:
        return {"changed": False, "gib": gib, "kind": kind, "retired": [], "notes": ["already set"]}
    changed = False
    for name in leftovers:                               # an earlier release that could not finish
        _delete_backing(runner, vg, name)
        retired.append(name)
        changed = True
    if target is not None and target not in active_names:
        target = _create(runner, vg, gib, kind, ensure_room)
        changed = True
    text = runner.read_text(fstab)
    new = _fstab_with(text, vg, target)
    if new != text:
        runner.write_text_atomic(fstab, new)
        changed = True
    for name in sorted(active_names - {target}):
        done = runner.run(["swapoff", name], timeout=600)
        if done.returncode != 0:
            notes.append(f"{name} is still in use and could not be released; it is kept until the next restart "
                         f"({(done.stderr or '').strip()[-80:]})")
            continue
        _delete_backing(runner, vg, name)
        retired.append(name)
        changed = True
    return {"changed": changed, "gib": gib, "kind": kind, "active": target, "retired": retired, "notes": notes}
