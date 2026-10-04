"""The installer's plan: what is on these drives, what should become of each, and what to install on top (queue
rows 72/76, 2026-10-03).

Four pure steps over one read-only `lsblk -J -b` listing, so the plan an operator edits is bound to the hardware
actually in front of them:

1. `discover` - drives by serial (never by kernel name), Baseline volumes by GPT partition name and PARTUUID. Only
   drives Baseline may act on (`drive_admin.allowed_target_serials()`, which includes deliberately enrolled ones) are
   described; any other drive is listed by serial, model and size only, so it can be enrolled. The boot drive is
   never listed at all.
2. `autofill` - an editable plan: keep an existing Proxmox drive or install onto an empty one, retain a Baseline
   drive's volumes PARTUUID by PARTUUID or lay out an empty one, and default OS/application choices. It never
   chooses a drive holding anything else, and never guesses between two candidates: it leaves the choice empty and
   says why in `notes`.
3. `validate` - every edit, against FRESH discovery, reporting every problem. A plan from before a drive was swapped
   or re-laid-out no longer matches its PARTUUIDs and is refused.
4. `compile_plan` - the parameters the existing stages already take (`drive_admin`'s `build_self_installer` and
   `lay_out_baseline_drive` actions, `ubuntu_environment.create`, `tasker.template`). Nothing here runs them; each
   destructive stage still goes through drive_admin's own gates (enrolled serial, drive_guard, backup freshness,
   human confirmation) when it is run.

Mounts compile to `PARTUUID=` rather than the `LABEL=` that `persist_bind_mounts` writes today: a filesystem label
is not unique - a second drive laid out by Baseline carries the same labels - while a PARTUUID belongs to one
partition on one drive.

Unit-tested against fakes only. Not verified on real hardware, and not yet connected to a provisioning run.
"""
from __future__ import annotations

import json
import re

import application_bundle as ab
import drive_guard
import drive_installer as di
import environment_recipes as er
import tasker
import ubuntu_environment as ue

FORMAT = "baseline.install-plan/v1"
STAGES_FORMAT = "baseline.install-stages/v1"
LSBLK_COLUMNS = "NAME,TYPE,SIZE,MODEL,SERIAL,PTUUID,PARTUUID,PARTLABEL,FSTYPE,UUID,LABEL,MOUNTPOINT"

SUPPORTED_OS = {"ubuntu-24.04": ue.BASE_NAME}         # the only OS ubuntu_environment can provision today
VARIANTS = ("desktop", "server")
DEFAULT_ENVIRONMENT = {"os": "ubuntu-24.04", "variant": "desktop", "name": "baseline-desktop"}
DEFAULT_APPLICATIONS = {"run_as": "baseline-admin", "cache": "/var/lib/baseline-app-cache",
                        "generation_root": "/var/lib/baseline-apps/generations",
                        "data": "/home/baseline-admin/baseline-managed-apps"}

_KEYS = {"format", "storage", "environment", "applications", "notes"}
_SUBSTRATE_KEYS = {"serial", "action"}
_BASELINE_KEYS = {"serial", "action", "personas", "volumes", "erase_existing"}
_PERSONA_RE = re.compile(r"^[a-z][a-z0-9]{0,7}$")     # APPDATA_<PERSONA> must fit an ext4 label (16 characters)
_HOSTNAME_RE = re.compile(r"^[a-z]([a-z0-9-]{0,30}[a-z0-9])?$")

NOT_YET_CONNECTED = (
    "running the stages: each one is still started separately (Drive Administration, /vms, baseline-tasker)",
    "writing the compiled PARTUUID mounts into /etc/fstab (persist_bind_mounts still mounts by LABEL)",
    "real-hardware verification of any of this",
)


class PlanError(ValueError):
    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = list(errors or [message])


def lsblk_argv() -> list:
    return ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS]


# --- discovery ---------------------------------------------------------------------------------

def _walk(node: dict):
    yield node
    for child in node.get("children") or ():
        yield from _walk(child)


def _state(disk: dict, parts: list) -> str:
    if not parts and not disk.get("fstype"):
        return "empty"
    if disk.get("fstype"):
        return "data"
    if all(drive_guard.is_own_label(p.get("partlabel")) for p in parts):
        return "baseline"
    for p in parts:
        if p.get("fstype") == "LVM2_member" and any(str(c.get("name", "")).startswith("pve-")
                                                    for c in p.get("children") or ()):
            return "proxmox"
    return "data"


def _volume(p: dict) -> dict:
    return {"name": di.canonical_name(p["partlabel"]), "partlabel": p["partlabel"], "partuuid": p.get("partuuid"),
            "fs_uuid": p.get("uuid"), "fstype": p.get("fstype"), "size_bytes": p.get("size")}


def _describe(disk: dict, is_installer_uuid) -> dict:
    parts = [c for c in disk.get("children") or () if c.get("type") == "part"]
    state = _state(disk, parts)
    ptuuid = disk.get("ptuuid")
    return {"serial": disk["serial"], "model": disk.get("model") or "", "size_bytes": disk.get("size"),
            "path_now": f"/dev/{disk.get('name')}", "ptuuid": ptuuid, "state": state,
            "installer_made": bool(ptuuid) and bool(is_installer_uuid(ptuuid)),
            "mounted": any(n.get("mountpoint") for n in _walk(disk)),
            "volumes": [_volume(p) for p in parts] if state == "baseline" else []}


def _parse(lsblk_json: str) -> list:
    try:
        value = json.loads(lsblk_json)
    except (TypeError, ValueError):
        raise PlanError("the drive listing could not be read") from None
    disks = value.get("blockdevices") if isinstance(value, dict) else None
    if not isinstance(disks, list) or not all(isinstance(d, dict) for d in disks):
        raise PlanError("the drive listing could not be read")
    return [d for d in disks if d.get("type") == "disk"]


def discover(lsblk_json: str, *, allowed_serials, boot_serial, is_installer_uuid=drive_guard.is_installer_uuid) -> dict:
    drives, unenrolled, unidentified = [], [], 0
    for disk in _parse(lsblk_json):
        serial = (disk.get("serial") or "").strip()
        if serial and serial == boot_serial:
            continue
        if not serial:
            unidentified += 1
        elif serial in allowed_serials:
            drives.append(_describe({**disk, "serial": serial}, is_installer_uuid))
        else:
            unenrolled.append({"serial": serial, "model": disk.get("model") or "", "size_bytes": disk.get("size")})
    return {"drives": drives, "unenrolled": unenrolled, "unidentified": unidentified}


# --- autofill ----------------------------------------------------------------------------------

def _only(drives: list, label: str, notes: list):
    if len(drives) == 1:
        return drives[0]
    if len(drives) > 1:
        notes.append(f"choose the {label}: drives {', '.join(d['serial'] for d in drives)} all qualify")
    return None


def autofill(discovery: dict, *, personas=di.DEFAULT_PERSONAS) -> dict:
    drives, notes = discovery["drives"], []
    empty = [d for d in drives if d["state"] == "empty" and not d["mounted"]]
    pve = _only([d for d in drives if d["state"] == "proxmox"], "Proxmox drive", notes)
    base = _only([d for d in drives if d["state"] == "baseline"], "Baseline drive", notes)
    ambiguous_base = base is None and any(d["state"] == "baseline" for d in drives)
    if base is None and not ambiguous_base and empty:
        base = empty.pop()
        notes.append(f"autofilled: lay out Baseline's volumes on empty drive {base['serial']}; edit if wrong")
    if pve is None and empty:
        pve = empty.pop(0)
        notes.append(f"autofilled: install Proxmox on empty drive {pve['serial']}; edit if wrong")
    if pve is None:
        notes.append("choose the Proxmox drive: no drive holds Proxmox and no empty drive is free")
    if base is None and not ambiguous_base:
        notes.append("choose the Baseline drive: no drive holds Baseline volumes and no empty drive is free")
    if discovery["unenrolled"]:
        notes.append("drives not yet enrolled are not offered: " + ", ".join(d["serial"] for d in discovery["unenrolled"]))
    retain = base is not None and base["state"] == "baseline"
    return {
        "format": FORMAT,
        "storage": {
            "substrate": {"serial": pve and pve["serial"],
                          "action": pve and ("keep" if pve["state"] == "proxmox" else "install")},
            "baseline": {"serial": base and base["serial"], "action": base and ("retain" if retain else "lay_out"),
                         "personas": list(personas), "erase_existing": False,
                         "volumes": [{"name": v["name"], "partuuid": v["partuuid"]} for v in base["volumes"]]
                         if retain else []},
        },
        "environment": dict(DEFAULT_ENVIRONMENT),
        "applications": {"apps": list(ab.APPS), **DEFAULT_APPLICATIONS},
        "notes": notes,
    }


# --- validation --------------------------------------------------------------------------------

def _exact_keys(value, keys: set, where: str, errors: list) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return False
    if set(value) != keys:
        missing, extra = sorted(keys - set(value)), sorted(set(value) - keys)
        errors.append(f"{where}: " + "; ".join(filter(None, [missing and f"missing {', '.join(missing)}",
                                                              extra and f"unknown {', '.join(extra)}"])))
        return False
    return True


def _drive(discovery: dict, serial, role: str, errors: list):
    if not isinstance(serial, str) or not serial:
        errors.append(f"{role}: choose a drive by serial")
        return None
    if serial.startswith("/"):
        errors.append(f"{role}: drives are chosen by serial, never by a device path like {serial}")
        return None
    for drive in discovery["drives"]:
        if drive["serial"] == serial:
            return drive
    errors.append(f"{role}: drive {serial} is not present or not enrolled")
    return None


def _check_substrate(spec: dict, discovery: dict, errors: list):
    drive = _drive(discovery, spec["serial"], "Proxmox drive", errors)
    if drive is None:
        return None
    if spec["action"] == "keep":
        if drive["state"] != "proxmox":
            errors.append(f"Proxmox drive {drive['serial']}: 'keep' needs a drive that holds Proxmox; it is {drive['state']}")
    elif spec["action"] == "install":
        if drive["state"] != "empty" and not (drive["state"] == "proxmox" and drive["installer_made"]):
            errors.append(f"Proxmox drive {drive['serial']}: installing would erase what it holds ({drive['state']}); "
                          "only an empty drive or an installer-made Proxmox drive may be installed over")
        if drive["mounted"]:
            errors.append(f"Proxmox drive {drive['serial']}: it is mounted, so nothing is installed over it")
    else:
        errors.append("Proxmox drive: action must be 'keep' or 'install'")
    return drive


def _check_personas(personas, errors: list) -> bool:
    if (not isinstance(personas, list) or not all(isinstance(p, str) and _PERSONA_RE.match(p) for p in personas)
            or len(set(personas)) != len(personas) or "admin" not in personas):
        errors.append("personas: a list of distinct lowercase names of up to 8 letters/digits, including 'admin'")
        return False
    return True


def _required_names(personas) -> list:
    return [volume[3] for volume in di.baseline_volumes_for(tuple(personas))]


def _check_retain(spec: dict, drive: dict, personas_ok: bool, errors: list) -> None:
    if drive["state"] != "baseline":
        errors.append(f"Baseline drive {drive['serial']}: 'retain' needs a drive with Baseline volumes; it is {drive['state']}")
        return
    found = {v["name"]: v["partuuid"] for v in drive["volumes"]}
    listed = spec["volumes"]
    if not isinstance(listed, list) or not all(isinstance(v, dict) and set(v) == {"name", "partuuid"} for v in listed):
        errors.append("Baseline drive: volumes must be a list of {name, partuuid}")
        return
    for volume in listed:
        if found.get(volume["name"]) != volume["partuuid"]:
            errors.append(f"Baseline drive {drive['serial']}: volume {volume['name']} with PARTUUID {volume['partuuid']} "
                          "is not on this drive now; discover again")
    if personas_ok:
        missing = [name for name in _required_names(spec["personas"]) if name not in found]
        if missing:
            errors.append(f"Baseline drive {drive['serial']}: missing volumes {', '.join(missing)}; run repair on it "
                          "or lay it out")
        unlisted = [name for name in _required_names(spec["personas"]) if name in found
                    and name not in {v["name"] for v in listed}]
        if unlisted:
            errors.append(f"Baseline drive {drive['serial']}: volumes {', '.join(unlisted)} must be listed to be retained")


def _check_lay_out(spec: dict, drive: dict, errors: list) -> None:
    if spec["volumes"] != []:
        errors.append("Baseline drive: a drive being laid out has no volumes to list yet")
    if tuple(spec["personas"]) != di.DEFAULT_PERSONAS:
        errors.append("Baseline drive: lay_out_baseline_drive lays out only the default personas "
                      f"({', '.join(di.DEFAULT_PERSONAS)}) so far")
    if drive["mounted"]:
        errors.append(f"Baseline drive {drive['serial']}: it is mounted, so it is not laid out")
    if drive["state"] == "empty":
        return
    if drive["state"] != "baseline":
        errors.append(f"Baseline drive {drive['serial']}: it holds {drive['state']}, which is never laid out over")
    elif spec["erase_existing"] is not True:
        errors.append(f"Baseline drive {drive['serial']}: laying out would erase its existing Baseline volumes, "
                      "including USER and AppData; set erase_existing to true only if that is intended")
    elif not drive["installer_made"]:
        errors.append(f"Baseline drive {drive['serial']}: it does not carry an installer identity, so it is not "
                      "erased; stamp it first (stamp_installer_identity)")


def _check_baseline(spec: dict, discovery: dict, substrate, errors: list) -> None:
    drive = _drive(discovery, spec["serial"], "Baseline drive", errors)
    personas_ok = _check_personas(spec["personas"], errors)
    if not isinstance(spec["erase_existing"], bool):
        errors.append("Baseline drive: erase_existing must be true or false")
    if drive is None:
        return
    if substrate is not None and substrate["serial"] == drive["serial"]:
        errors.append(f"drive {drive['serial']} cannot be both the Proxmox drive and the Baseline drive")
        return
    if spec["action"] == "retain":
        _check_retain(spec, drive, personas_ok, errors)
    elif spec["action"] == "lay_out":
        if personas_ok:
            _check_lay_out(spec, drive, errors)
    else:
        errors.append("Baseline drive: action must be 'retain' or 'lay_out'")


def _check_environment(env, errors: list) -> None:
    if not _exact_keys(env, set(DEFAULT_ENVIRONMENT), "environment", errors):
        return
    if env["os"] not in SUPPORTED_OS:
        errors.append(f"environment: os must be one of {', '.join(SUPPORTED_OS)} (the only ones provisioned so far)")
    if env["variant"] not in VARIANTS:
        errors.append(f"environment: variant must be one of {', '.join(VARIANTS)}")
    if not isinstance(env["name"], str) or not _HOSTNAME_RE.match(env["name"]):
        errors.append("environment: name must be a lowercase host name")


def _check_applications(apps, errors: list) -> None:
    if not _exact_keys(apps, {"apps", *DEFAULT_APPLICATIONS}, "applications", errors):
        return
    chosen = apps["apps"]
    if (not isinstance(chosen, list) or not chosen or len(set(map(str, chosen))) != len(chosen)
            or not all(a in ab.APPS for a in chosen)):
        errors.append(f"applications: apps must be a non-empty list of distinct choices from {', '.join(ab.APPS)}")
    try:
        tasker.validate_task_storage(cache=apps["cache"], generation=apps["generation_root"], data=apps["data"],
                                     run_as=apps["run_as"])
    except er.RecipeError as exc:
        errors.append(f"applications: {exc}")


def validate(plan, discovery: dict) -> list:
    """Every problem with `plan` against `discovery` (which should be fresh), as plain sentences. Empty means valid."""
    errors = []
    if not isinstance(plan, dict) or not {"format", "storage", "environment", "applications"} <= set(plan) <= _KEYS:
        return ["the plan must have exactly format, storage, environment, applications and optional notes"]
    if plan["format"] != FORMAT:
        errors.append(f"format must be {FORMAT}")
    storage = plan["storage"]
    if _exact_keys(storage, {"substrate", "baseline"}, "storage", errors):
        substrate = None
        if _exact_keys(storage["substrate"], _SUBSTRATE_KEYS, "storage.substrate", errors):
            substrate = _check_substrate(storage["substrate"], discovery, errors)
        if _exact_keys(storage["baseline"], _BASELINE_KEYS, "storage.baseline", errors):
            _check_baseline(storage["baseline"], discovery, substrate, errors)
    _check_environment(plan["environment"], errors)
    _check_applications(plan["applications"], errors)
    return errors


# --- compilation -------------------------------------------------------------------------------

def _mounts(spec: dict, drive: dict) -> list:
    fstypes = {v["name"]: v["fstype"] or "ext4" for v in drive["volumes"]}
    mountpoints = {volume[3]: volume[4] for volume in di.baseline_volumes_for(tuple(spec["personas"]))}
    mounts = []
    for volume in spec["volumes"]:
        if volume["name"] not in mountpoints:
            continue
        mountpoint, options = mountpoints[volume["name"]], di.mount_options_for(volume["name"])
        mounts.append({"name": volume["name"], "partuuid": volume["partuuid"], "mountpoint": mountpoint,
                       "options": options,
                       "fstab": f"PARTUUID={volume['partuuid']} {mountpoint} {fstypes[volume['name']]} {options} 0 2"})
    return mounts


def compile_plan(plan, discovery: dict) -> dict:
    errors = validate(plan, discovery)
    if errors:
        raise PlanError("the plan is not valid", errors)
    storage, env, apps = plan["storage"], plan["environment"], plan["applications"]
    substrate, baseline = storage["substrate"], storage["baseline"]
    drive = next(d for d in discovery["drives"] if d["serial"] == baseline["serial"])
    after = []
    if substrate["action"] == "install":
        substrate_stage = {"action": "install", "drive_action": "build_self_installer",
                           "params": {"expected_serial": substrate["serial"]}}
    else:
        substrate_stage = {"action": "keep"}
    if baseline["action"] == "lay_out":
        baseline_stage = {"action": "lay_out", "drive_action": "lay_out_baseline_drive",
                          "expected_serial": baseline["serial"], "personas": list(baseline["personas"]), "mounts": []}
        after.append("after the layout, discover again and compile a retain plan to bind the new PARTUUIDs to mounts")
    else:
        baseline_stage = {"action": "retain", "expected_serial": baseline["serial"],
                          "mounts": _mounts(baseline, drive)}
    return {
        "format": STAGES_FORMAT,
        "executed": False,
        "substrate": substrate_stage,
        "baseline_drive": baseline_stage,
        "environment": {"name": env["name"], "desktop": env["variant"] == "desktop", "base": SUPPORTED_OS[env["os"]]},
        "applications": {"apps": list(apps["apps"]), **{k: apps[k] for k in DEFAULT_APPLICATIONS}},
        "after": after,
        "not_yet_connected": list(NOT_YET_CONNECTED),
    }


# --- baseline-install-plan ---------------------------------------------------------------------

def _read_plan(path: str):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise PlanError(f"{path} could not be read as a plan: not JSON or not readable ({exc})") from None


def main(argv: list, *, read_listing, boot_serial, allowed_serials, is_installer_uuid=drive_guard.is_installer_uuid,
         print_fn=print) -> int:
    """`discover`, `autofill`, `validate PLAN` or `compile PLAN`. Every command discovers afresh; none writes
    anything. Returns 0, or 1 with every problem printed."""
    command, *rest = argv or ["help"]
    if command not in ("discover", "autofill", "validate", "compile") or len(rest) != (command in ("validate", "compile")):
        print_fn("usage: baseline-install-plan discover | autofill | validate PLAN.json | compile PLAN.json")
        return 2
    try:
        found = discover(read_listing(), allowed_serials=allowed_serials, boot_serial=boot_serial,
                         is_installer_uuid=is_installer_uuid)
        if command == "discover":
            result = found
        elif command == "autofill":
            result = autofill(found)
        elif command == "validate":
            errors = validate(_read_plan(rest[0]), found)
            if errors:
                raise PlanError("the plan is not valid", errors)
            print_fn("plan is valid against the drives present now")
            return 0
        else:
            result = compile_plan(_read_plan(rest[0]), found)
    except PlanError as exc:
        for error in exc.errors:
            print_fn(f"refused: {error}")
        return 1
    print_fn(json.dumps(result, indent=2))
    return 0
