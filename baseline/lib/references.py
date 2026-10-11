"""The backbone: hierarchical identifiers (identifiers.py, DR255) as the references components use for each other.

Two uses, both additive and tolerant (on a machine that is not a Baseline host nothing is minted and nothing fails):

- Registries. Each registry keeps its own entries and its own keys (the foundation registry, DR89; naming.py's short local codes such as
  `A_C_00001`). `link` mints the global identifier for an entry and records which entry it stands for, so any component can go from an
  identifier to the registry entry (`resolve`) and from an entry to its identifier (`reference_for`). A naming code is the *local*
  constant (labels, units, uids); the identifier is the *global* reference, minted from that code so it never depends on a human name.
- Messages. `stamp` adds `source_ref` and `subject_ref` (identifiers) to an event or packet, so a message says who sent it and what it
  is about in the same terms every registry uses.

The running system's own host identifier is in `/etc/baseline/host-id`, written by first boot after it sets the disk identifier.
"""
from __future__ import annotations

import re
from pathlib import Path

import identifiers

HOST_ID_FILE = Path("/etc/baseline/host-id")
HOST = object()                                   # `stamp(..., source=HOST)`: this system's own host identifier, when it has one
_SAFE = re.compile(r"[^A-Za-z0-9_./:@+-]")


class ReferenceError(ValueError):
    pass


def current_host(path=None) -> str | None:
    """This system's host identifier, or None when it has none (not a Baseline host, or a damaged or foreign file)."""
    try:
        text = Path(path or HOST_ID_FILE).read_text().strip()
    except OSError:
        return None
    try:
        return text if identifiers.is_valid(text) and identifiers.parse(text).kind == "host" else None
    except identifiers.IdentifierError:
        return None


def _name(value: str) -> str | None:
    cleaned = _SAFE.sub("_", str(value))[:128]
    return cleaned if cleaned and cleaned[0].isalnum() else None


def link(type_id: str, entry_id: str, *, kind: str, parent: str | None = None, name: str | None = None) -> str | None:
    """The identifier for registry entry (`type_id`, `entry_id`), minted under `parent` (default: this host) and registered with a pointer
    back to the entry. Idempotent. None when there is no parent to mint under."""
    parent = parent or current_host()
    name = _name(name or entry_id)
    if parent is None or name is None:
        return None
    return identifiers.mint(parent, kind, name, source={"type": type_id, "id": str(entry_id)})


def _entries():
    import registry
    identifiers._registry()
    return registry.list_entries(identifiers.REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)


def reference_for(type_id: str, entry_id: str) -> str | None:
    wanted = {"type": type_id, "id": str(entry_id)}
    for guid, entry in _entries().items():
        if identifiers._attributes(entry).get("source") == wanted:
            return guid
    return None


def resolve(guid: str) -> dict | None:
    """What registered `guid` stands for: its kind, parent, name, serial and the registry entry it points at; None if unknown."""
    entry = _entries().get(guid)
    return dict(identifiers._attributes(entry)) if entry is not None else None


# naming.py's clusters and media (A App, S Substrate, U User, O Operating System; V VM, L LXC, ...) to the identifier kind
def kind_for_naming(code: str) -> str | None:
    import naming
    try:
        parsed = naming.parse_id(code)
    except (naming.NamingError, ValueError):
        return None
    if parsed.medium in ("V", "L"):
        return "vm"
    return "application" if parsed.cluster == "A" else "substrate"


def link_naming(code: str, *, parent: str | None = None) -> str | None:
    kind = kind_for_naming(code)
    if kind is None:
        return None
    return link("naming", code, kind=kind, parent=parent, name=code)


def stamp(record: dict, *, source=None, subject=None) -> dict:
    """A copy of `record` with `source_ref` (who it is from) and `subject_ref` (what it is about) added. Each must be a valid identifier;
    `source=HOST` means this system's own host identifier, left out when there is none."""
    out = dict(record)
    if source is HOST:
        source = current_host()
    for key, value in (("source_ref", source), ("subject_ref", subject)):
        if value is None:
            continue
        if not isinstance(value, str) or not identifiers.is_valid(value):
            raise ReferenceError(f"{key} must be a valid identifier of the DR255 layout, got {value!r}")
        out[key] = value
    return out


# --- storage roles (DR256) ---------------------------------------------------------------------------------------------------

BOUND_ROLES = frozenset({"SUBSTRATE", "SESSION_TEMP"})      # tied to this host; every other role holds data that moves with its owner


def link_roles(labels, *, parent: str | None = None) -> dict:
    """The identifier of each storage role (volume label) on this host: portable (special 02) for roles that hold data that must outlive the
    drive (BASELINE, INSTALLER_CACHE, USER_*, APPDATA_*), fixed to the host for SUBSTRATE and SESSION_TEMP. Empty without a host."""
    parent = parent or current_host()
    if parent is None:
        return {}
    out = {}
    for label in labels:
        name = _name(label)
        if name is None:
            continue
        source = {"type": "storage_role", "id": label}
        out[label] = (identifiers.mint(parent, "substrate", name, source=source) if label in BOUND_ROLES
                      else identifiers.mint_portable(parent, "substrate", name, source=source))
    return out


def default_role_labels(personas=None) -> list:
    import drive_installer as di
    volumes = di.baseline_volumes_for(tuple(personas) if personas is not None else di.DEFAULT_PERSONAS)
    return [v[3] for v in volumes]


def backfill(*, parent: str | None = None) -> dict:
    """Give every entry that existed before this host had an identifier its reference: naming codes, then the storage roles. Idempotent."""
    parent = parent or current_host()
    if parent is None:
        return {"linked": 0, "reason": "no host identifier"}
    import naming
    linked = 0
    for code in naming.allocated(read_only=True):
        linked += link_naming(code, parent=parent) is not None
    roles = link_roles(default_role_labels(), parent=parent)
    return {"linked": linked + len(roles)}


def link_external(kind: str, name: str, value: str, *, scheme: str, parent: str | None = None) -> str | None:
    """The identifier for a thing known to Baseline only by an outside identifier (a Proxmox VMID, a MAC): mapped once, then stable.
    None when there is no host to put it under."""
    parent = parent or current_host()
    name = _name(name)
    if parent is None or name is None:
        return None
    return identifiers.map_external(parent, kind, name, str(value), scheme=scheme)
