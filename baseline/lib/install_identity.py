"""A stable, per-install identity that survives rebuilds and is never
silently shared by clones.

Direct instruction, 2026-09-30: "each install should have a UUID and if
someone replicated 30 machines and was going to establish a soft
identification ... this will be praised later for preventing something or
enabling something important."

**Soft identification, not authentication.** The install id names a
machine so a fleet can be told apart, inventoried and traced back to its
origin. It is not a secret and proves nothing about who is asking - never
gate access on it.

Where it lives, and why there: `/mnt/SUBSTRATE/install/identity.json`.
SUBSTRATE survives a substrate rebuild, which `/etc/machine-id` does not -
machine-id is per OS install and changes every time Proxmox is
reinstalled, so it cannot name *this Baseline install* across its own
rebuild cycle.

**The clone problem.** A stored id is copied by anything that copies the
disk. Thirty machines imaged from one would all claim to be one - the
failure systemd's machine-id hit, which is why OS images ship it blank.
Two defences, kept separate:

1. **Replication never carries the identity.** `REPLICATION_EXCLUDES`
   lists what a self-replicating build must not copy. A replica mints its
   own id on first boot and records its origin as `parent_id`, so the
   fleet forms a lineage rather than a set of duplicates.
2. **A copy that arrives anyway is detected, not believed.** The identity
   records a fingerprint of the hardware it was minted on. On different
   hardware, `ensure_identity` reports `hardware_changed` and changes
   nothing. Whether that is a disk *moved* to new hardware (same install:
   `adopt_hardware`) or a *clone* (a new install: `fork_identity`) cannot
   be told from the disk, so it is never guessed - an operator decides.

**Fingerprint sources.** SMBIOS product UUID and board/product serials,
which are root-only (mode 0400) - firstboot runs as root. Model names are
deliberately excluded: thirty identical machines share them. Many boards
ship *placeholder* SMBIOS values identical across every unit of a model;
those are recognised and reported as a weak fingerprint, because a fleet
of such boards would otherwise all match each other.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field

DEFAULT_PATH = "/mnt/SUBSTRATE/install/identity.json"
HISTORY_PATH_SUFFIX = ".history.jsonl"
SCHEMA = 1

# What a self-replicating build must never copy onto a replica.
REPLICATION_EXCLUDES = (
    DEFAULT_PATH,
    DEFAULT_PATH + HISTORY_PATH_SUFFIX,
)

_FINGERPRINT_SOURCES = (
    "/sys/class/dmi/id/product_uuid",
    "/sys/class/dmi/id/board_serial",
    "/sys/class/dmi/id/product_serial",
)

# Values boards ship when the vendor never set a real one. Compared
# case-insensitively after stripping.
_PLACEHOLDERS = {
    "", "none", "0", "default string", "to be filled by o.e.m.", "not specified",
    "system serial number", "123456789", "0123456789",
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "03000200-0400-0500-0006-000700080009",
}

STATUS_CREATED = "created"
STATUS_EXISTING = "existing"
STATUS_HARDWARE_CHANGED = "hardware_changed"
STATUS_FINGERPRINT_UNAVAILABLE = "fingerprint_unavailable"


class IdentityError(ValueError):
    pass


@dataclass
class Fingerprint:
    digest: str | None              # sha256 over the real, non-placeholder values
    sources_read: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.digest is not None

    @property
    def weak(self) -> bool:
        """True when any source was a placeholder - such a value is shared
        by every unit of the model, so it cannot separate a fleet."""
        return bool(self.placeholders)


@dataclass
class Identity:
    install_id: str
    created_at: float
    parent_id: str | None = None    # the install this one was replicated or forked from
    generation: int = 0             # 0 = origin; replicas count up from their parent
    fingerprint: str | None = None
    fingerprint_weak: bool = False
    alias: str = ""                 # a soft, changeable human name - never the identity
    schema: int = SCHEMA


def _validate_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise IdentityError(f"not a UUID: {value!r}") from exc


def hardware_fingerprint(runner) -> Fingerprint:
    """Fingerprint of the machine, from root-only SMBIOS fields. Never
    raises: unreadable sources are recorded, not fatal."""
    values, fp = [], Fingerprint(digest=None)
    for path in _FINGERPRINT_SOURCES:
        try:
            raw = runner.read_text(path).strip()
        except (PermissionError, FileNotFoundError, OSError):
            fp.unreadable.append(path)
            continue
        if raw.lower() in _PLACEHOLDERS:
            fp.placeholders.append(path)
            continue
        fp.sources_read.append(path)
        values.append(f"{path}={raw}")
    if values:
        fp.digest = hashlib.sha256("\n".join(values).encode()).hexdigest()
    return fp


def read_identity(runner, path: str = DEFAULT_PATH) -> Identity | None:
    if not runner.path_exists(path):
        return None
    data = json.loads(runner.read_text(path))
    data["install_id"] = _validate_uuid(data["install_id"])
    if data.get("parent_id"):
        data["parent_id"] = _validate_uuid(data["parent_id"])
    return Identity(**data)


def _write(runner, path: str, ident: Identity) -> None:
    runner.write_text_atomic(path, json.dumps(asdict(ident), indent=2, sort_keys=True) + "\n")


def _record_history(runner, path: str, event: str, ident: Identity, now: float) -> None:
    runner.append_text(path + HISTORY_PATH_SUFFIX,
                       json.dumps({"at": now, "event": event, **asdict(ident)}, sort_keys=True) + "\n")


def ensure_identity(runner, *, now: float, fingerprint: Fingerprint,
                    path: str = DEFAULT_PATH, parent_id: str | None = None,
                    parent_generation: int = -1, new_uuid=uuid.uuid4) -> tuple:
    """Return this install's identity, minting it if none exists.

    Never overwrites an existing identity. If the stored fingerprint does
    not match this hardware, returns the stored identity unchanged with
    STATUS_HARDWARE_CHANGED - moved disk or clone is an operator decision.

    `parent_id`/`parent_generation` come from a replication manifest when
    this install was built from another one; an origin install has none."""
    existing = read_identity(runner, path)
    if existing is not None:
        if not fingerprint.available or existing.fingerprint is None:
            return existing, STATUS_FINGERPRINT_UNAVAILABLE
        if existing.fingerprint != fingerprint.digest:
            return existing, STATUS_HARDWARE_CHANGED
        return existing, STATUS_EXISTING

    ident = Identity(
        install_id=str(new_uuid()),
        created_at=now,
        parent_id=_validate_uuid(parent_id) if parent_id else None,
        generation=parent_generation + 1 if parent_id else 0,
        fingerprint=fingerprint.digest,
        fingerprint_weak=fingerprint.weak,
    )
    _write(runner, path, ident)
    _record_history(runner, path, "created", ident, now)
    return ident, STATUS_CREATED


def adopt_hardware(runner, *, now: float, fingerprint: Fingerprint, path: str = DEFAULT_PATH) -> Identity:
    """Operator decision: this disk was MOVED to new hardware. Same
    install, same id; only the recorded fingerprint changes."""
    current = read_identity(runner, path)
    if current is None:
        raise IdentityError("no identity to adopt")
    if not fingerprint.available:
        raise IdentityError("cannot adopt hardware without a readable fingerprint")
    current.fingerprint, current.fingerprint_weak = fingerprint.digest, fingerprint.weak
    _write(runner, path, current)
    _record_history(runner, path, "adopted_hardware", current, now)
    return current


def fork_identity(runner, *, now: float, fingerprint: Fingerprint, path: str = DEFAULT_PATH,
                  new_uuid=uuid.uuid4) -> Identity:
    """Operator decision: this is a CLONE. It becomes a new install whose
    parent is the identity it was copied with, so the lineage records
    where it came from instead of erasing it."""
    current = read_identity(runner, path)
    if current is None:
        raise IdentityError("no identity to fork from")
    forked = Identity(
        install_id=str(new_uuid()), created_at=now,
        parent_id=current.install_id, generation=current.generation + 1,
        fingerprint=fingerprint.digest, fingerprint_weak=fingerprint.weak,
    )
    _write(runner, path, forked)
    _record_history(runner, path, "forked", forked, now)
    return forked


def set_alias(runner, alias: str, *, now: float, path: str = DEFAULT_PATH) -> Identity:
    """A changeable human name for the install (e.g. "lab-03"). Changing
    it never changes the id."""
    import naming
    naming.validate_alias(alias)
    current = read_identity(runner, path)
    if current is None:
        raise IdentityError("no identity to name")
    current.alias = alias
    _write(runner, path, current)
    _record_history(runner, path, "aliased", current, now)
    return current
