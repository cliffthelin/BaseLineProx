"""Real-hardware LVM-thin persistence pool setup.

**SUPERSEDED as of decision record 46/47 (2026-09-26) - the real
`/dev/sdb` was repartitioned to plain ext4 (`USER`/
`INSTALLER_CACHE`/`SESSION_TEMP`), not an LVM-thin pool. This module's
design no longer matches the physical disk's current state.** Kept
because its Runner-injected argv-building logic and its 16 unit tests
remain real and correct *for the LVM-thin design specifically*, in
case that design is ever revisited for a different disk - not because
it's the current intended path for `/dev/sdb`. An audit
(decision record 47) found this module's own docstring didn't say so,
and flagged it as exactly the kind of stale reference this project's
own `AGENTS.md` now exists to prevent recurring.

Track A2 described building an LVM-thin pool once, for real, on
`/dev/sdb` - deactivating a stale duplicate `pve` volume group by
exact UUID, wiping signatures, building the pool, and registering it
with Proxmox as the `baseline-persist` storage backend - but via ad
hoc, manually-typed commands, narrated only in prose
(`docs/SESSION_HANDOFF.md`), with no reusable code left behind. This
module was a reconstruction of that intended procedure, not a recovery
of the exact original commands - and decision record 45 already
flagged that even that reconstruction was never run against real
hardware before `/dev/sdb` was repartitioned to ext4 instead.

Every function here is Runner-injectable and unit-tested against
fakes only. No destructive helper here ever accepts a bare device
path - only `physical_device_safety`'s validated dict, matching that
module's own established discipline.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


DEFAULT_VG_NAME = "baselinepersistvg"
DEFAULT_POOL_NAME = "persist_pool"
DEFAULT_STORAGE_ID = "baseline-persist"


@dataclass
class CommandResult:
    ok: bool
    detail: str


# ---------------------------------------------------------------------------
# Pure argv builders and output parsers
# ---------------------------------------------------------------------------

def list_volume_groups_argv() -> list:
    return ["vgs", "--noheadings", "-o", "vg_name,vg_uuid"]


def parse_volume_groups(text: str) -> list:
    """Each line: `<name>   <uuid>` (vgs --noheadings output, extra
    leading/trailing whitespace stripped)."""
    groups = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            groups.append((parts[0], parts[1]))
    return groups


def find_stale_vg_uuids(groups: list, *, name: str, keep_uuid: str) -> list:
    """Every VG sharing `name` whose UUID isn't `keep_uuid` - the
    exact-UUID disambiguation Track A2's own narration described,
    never a name-alone match (two VGs can share a name)."""
    return [uuid for vg_name, uuid in groups if vg_name == name and uuid != keep_uuid]


def deactivate_vg_by_uuid_argv(vg_uuid: str) -> list:
    """Deactivates a specific VG by exact UUID - never by name alone,
    since a stale duplicate-named VG (e.g. a leftover `pve` VG from a
    prior install) can share a name with a different, currently-active
    VG. Requires a real LVM version supporting `--select` on
    `vgchange` - not independently re-verified against the real
    installed LVM version on any target."""
    return ["vgchange", "-an", "--select", f"vg_uuid={vg_uuid}"]


def create_thin_pool_argvs(validated: dict, *, vg_name: str = DEFAULT_VG_NAME,
                            pool_name: str = DEFAULT_POOL_NAME) -> list:
    """The ordered pvcreate -> vgcreate -> lvcreate sequence, against
    the exact validated device path only."""
    device = validated["path"]
    return [
        ["pvcreate", device],
        ["vgcreate", vg_name, device],
        ["lvcreate", "-T", f"{vg_name}/{pool_name}", "-l", "100%FREE"],
    ]


def register_with_proxmox_argv(*, vg_name: str = DEFAULT_VG_NAME,
                                pool_name: str = DEFAULT_POOL_NAME,
                                storage_id: str = DEFAULT_STORAGE_ID) -> list:
    return ["pvesm", "add", "lvmthin", storage_id,
            "--vgname", vg_name, "--thinpool", pool_name]


# ---------------------------------------------------------------------------
# Runner-executed operations
# ---------------------------------------------------------------------------

def deactivate_stale_vgs(runner: Runner, *, name: str, keep_uuid: str) -> CommandResult:
    proc = runner.run(list_volume_groups_argv(), timeout=15)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"vgs exited {proc.returncode}")

    groups = parse_volume_groups(proc.stdout)
    stale = find_stale_vg_uuids(groups, name=name, keep_uuid=keep_uuid)
    if not stale:
        return CommandResult(True, f"nothing stale to deactivate for VG {name!r}")

    for vg_uuid in stale:
        deactivate_proc = runner.run(deactivate_vg_by_uuid_argv(vg_uuid), timeout=15)
        if deactivate_proc.returncode != 0:
            return CommandResult(
                False,
                f"failed to deactivate stale VG {name!r} (uuid {vg_uuid}): "
                f"{deactivate_proc.stderr.strip()}",
            )
    return CommandResult(True, f"deactivated {len(stale)} stale VG(s) named {name!r}: {stale}")


def create_thin_pool(runner: Runner, validated: dict, *, vg_name: str = DEFAULT_VG_NAME,
                      pool_name: str = DEFAULT_POOL_NAME) -> CommandResult:
    for argv in create_thin_pool_argvs(validated, vg_name=vg_name, pool_name=pool_name):
        proc = runner.run(argv, timeout=30)
        if proc.returncode != 0:
            return CommandResult(False, f"{argv[0]} failed: {proc.stderr.strip()}")
    return CommandResult(True, f"thin pool {vg_name}/{pool_name} created on {validated['path']}")


def register_with_proxmox(runner: Runner, *, vg_name: str = DEFAULT_VG_NAME,
                           pool_name: str = DEFAULT_POOL_NAME,
                           storage_id: str = DEFAULT_STORAGE_ID) -> CommandResult:
    proc = runner.run(register_with_proxmox_argv(vg_name=vg_name, pool_name=pool_name,
                                                  storage_id=storage_id), timeout=15)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"pvesm add exited {proc.returncode}")
    return CommandResult(True, f"registered {storage_id!r} with Proxmox ({vg_name}/{pool_name})")
