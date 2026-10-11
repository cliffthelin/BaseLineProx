"""Grow a role volume when it is actually used and needs more (operator, 2026-10-11: "1 GB each volume only grows if actually used and needed").

Role volumes start small (storage plan v3) and the rest of the drive stays free in the volume group. This module decides, from measured usage,
which volumes to extend and by how much, and does it with `lvextend -r` (volume and ext4 together, online). It never shrinks anything, never
touches a volume that is not a Baseline role, never takes the last GiB of the group, and never grows a role past its ceiling.

`plan` is pure. `collect` reads usage; `execute` runs the extensions; `ensure_room` is what a writer calls before a large copy.
"""
from __future__ import annotations

import json

import drive_installer as di

GIB = 1024 ** 3
THRESHOLD = 0.80          # a volume this full wants more room
HEADROOM = 1.5            # grown to this multiple of what it holds now
KEEP_FREE = 1 * GIB       # the volume group always keeps this much unallocated


class GrowthError(RuntimeError):
    pass


def _ceil_gib(value: float) -> int:
    return int(-(-value // GIB))


def plan(rows: list, vg_free_bytes: int, *, threshold: float = THRESHOLD, headroom: float = HEADROOM) -> list:
    """rows: [{"label", "name", "size_bytes", "used_bytes", "max_gib"}]. Returns [{"label", "name", "add_gib"}] for each volume that is at
    least `threshold` full, fullest first, limited by each volume's ceiling and by the free space left after KEEP_FREE."""
    budget = max(vg_free_bytes - KEEP_FREE, 0) // GIB
    wanted = []
    for row in rows:
        size, used = row["size_bytes"], row["used_bytes"]
        if size <= 0 or used / size < threshold:
            continue
        current = _ceil_gib(size)
        target = max(current + 1, _ceil_gib(used * headroom))
        add = min(target - current, row["max_gib"] - size // GIB)
        if add > 0:
            wanted.append((used / size, {"label": row["label"], "name": row["name"], "add_gib": add}))
    out = []
    for _, item in sorted(wanted, key=lambda w: -w[0]):
        item = dict(item, add_gib=min(item["add_gib"], budget))
        if item["add_gib"] > 0:
            budget -= item["add_gib"]
            out.append(item)
    return out


def room_needed(row: dict, needed_bytes: int, vg_free_bytes: int) -> dict | None:
    """The extension that gives `row` at least `needed_bytes` of free space, or None when it already has it. Refuses (GrowthError) when the
    group, or the volume's ceiling, cannot provide it: a copy must never start that cannot finish."""
    free = row["size_bytes"] - row["used_bytes"]
    if free >= needed_bytes:
        return None
    add = _ceil_gib(needed_bytes - free)
    if add > max(vg_free_bytes - KEEP_FREE, 0) // GIB:
        raise GrowthError(f"{row['label']} needs {add} GiB more but the volume group has only {max(vg_free_bytes - KEEP_FREE, 0) // GIB} GiB unallocated")
    if row["size_bytes"] // GIB + add > row["max_gib"]:
        raise GrowthError(f"{row['label']} would exceed its {row['max_gib']} GiB ceiling")
    return {"label": row["label"], "name": row["name"], "add_gib": add}


def lvextend_argv(vg: str, name: str, add_gib: int) -> list:
    if not isinstance(add_gib, int) or add_gib < 1:
        raise GrowthError("growth must be a whole number of GiB")
    return ["lvextend", "-L", f"+{add_gib}G", "-r", f"/dev/{vg}/{name}"]


def _json(runner, argv):
    proc = runner.run(argv, timeout=60)
    try:
        if proc.returncode:
            raise ValueError
        return json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise GrowthError(f"{argv[0]} could not be read") from None


def volume_group(runner) -> str:
    rows = _json(runner, ["lvs", "--reportformat", "json", "-o", "vg_name,lv_name"])["report"][0]["lv"]
    groups = {r["vg_name"] for r in rows if r["lv_name"] == "root"}
    if len(groups) != 1:
        raise GrowthError("the volume group holding the host root could not be identified")
    return groups.pop()


def collect(runner, vg: str, personas=di.DEFAULT_PERSONAS) -> tuple:
    """(rows, vg_free_bytes) for every Baseline role volume that exists."""
    lvs = _json(runner, ["lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size", vg])["report"][0]["lv"]
    sizes = {r["lv_name"]: int(r["lv_size"]) for r in lvs}
    free = int(_json(runner, ["vgs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "vg_free", vg])["report"][0]["vg"][0]["vg_free"])
    rows = []
    for name, _, max_gib, label, mountpoint in di.baseline_volumes_for(tuple(personas)):
        if name not in sizes:
            continue
        proc = runner.run(di.df_argv(mountpoint), timeout=30)
        usage = di.parse_df_output(proc.stdout) if proc.returncode == 0 else None
        if usage is None:
            continue
        rows.append({"label": label, "name": name, "size_bytes": sizes[name], "used_bytes": usage["used_bytes"], "max_gib": max_gib})
    return rows, free


def execute(runner, vg: str, items: list) -> list:
    done = []
    for item in items:
        proc = runner.run(lvextend_argv(vg, item["name"], item["add_gib"]), timeout=600)
        if proc.returncode:
            raise GrowthError(f"{item['label']} could not be extended: {(proc.stderr or '').strip()[-200:]}")
        done.append(item)
    return done


def ensure_room(runner, label: str, needed_bytes: int, personas=di.DEFAULT_PERSONAS) -> dict | None:
    """Make sure the `label` volume has `needed_bytes` free, extending it if the group can. Returns what it did, or None."""
    vg = volume_group(runner)
    rows, free = collect(runner, vg, personas)
    row = next((r for r in rows if r["label"] == label), None)
    if row is None:
        raise GrowthError(f"{label} is not a mounted Baseline volume")
    item = room_needed(row, needed_bytes, free)
    if item is None:
        return None
    execute(runner, vg, [item])
    return item


def run_once(runner, personas=di.DEFAULT_PERSONAS) -> list:
    """The timer's job: grow whatever is nearly full."""
    vg = volume_group(runner)
    rows, free = collect(runner, vg, personas)
    return execute(runner, vg, plan(rows, free))
