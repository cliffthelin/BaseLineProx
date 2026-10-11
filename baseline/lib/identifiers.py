"""Hierarchical identifiers for host installs, substrate, VMs, applications and hardware (DR255).

Every identifier is a 128-bit UUID in text form (so it works as a GPT disk GUID, an SMBIOS/VM UUID or a filesystem UUID) laid out as 32
hex digits:

    digits   host (kind 0)            substrate / VM (kinds 1, 2)   application / hardware (kinds 3, 4)
    0-7      installer lane (8)       installer lane (inherited)    4 = parent pointer, 4 = class code   (the lane is dropped)
    8-11     serial: first 4 hex      same                          same
    12-15    serial: last 4 hex       same                          same
    16       layout version (1)       same                          same
    17       kind (0)                 1 substrate, 2 VM / container 3 application, 4 hardware
    18-19    check byte               same                          same
    20-23    host discriminator       inherited from the host       inherited from the host
    24-31    rest of the host hash    own id (hash of parent+kind+name)   own id (hash of parent+kind+name)

A child is derived from its parent, so it can be minted on the installed system with no installer present. Identifiers are stable: the
same parent, kind and name always give the same identifier. The check byte is integrity (typos, truncation), not authenticity.
The registry holds one shape for every level, so adding a level never changes it.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

VERSION = "1"
KINDS = {"host": 0, "substrate": 1, "vm": 2, "application": 3, "hardware": 4}
KIND_NAMES = {number: name for name, number in KINDS.items()}
LANE_KINDS = {0, 1, 2}                  # these carry the installer lane; applications and hardware do not
REGISTRY_TYPE = "baseline_identities"
NON_HEX = "0"                           # reserved filler when a serial has fewer hex characters than a group needs
_HEX = "0123456789abcdef"
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,127}$")
# which kinds may live under which
_PARENTS = {"substrate": {0}, "vm": {0}, "application": {0, 1, 2}, "hardware": {0, 1, 2}}


class IdentifierError(ValueError):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def serial_hex(serial: str, count: int, *, from_end: bool = False) -> str:
    """`count` hex characters of `serial`, skipping every non-hex character: from the front, or the last `count` (kept in written order)
    when `from_end`; filled with NON_HEX where the serial has too few."""
    hexes = [c.lower() for c in serial if c.lower() in _HEX]
    if from_end:
        taken = hexes[-count:]
        return NON_HEX * (count - len(taken)) + "".join(taken)
    taken = hexes[:count]
    return "".join(taken) + NON_HEX * (count - len(taken))


def class_code(name: str) -> str:
    """4 hex digits naming the class of a thing (`chrome`, `nic`): a hash of the class name, never in the reserved low range 0000-00ff."""
    code = _sha("class:" + name.split("/", 1)[0])[:4]
    return code if int(code, 16) >= 0x0100 else format(int(code, 16) | 0x8000, "04x")


def _check(body_with_zero_check: str) -> str:
    return _sha("baseline-id-v1:" + body_with_zero_check)[:2]


def _assemble(scope8: str, drive8: str, kind: int, tail12: str) -> str:
    zero = f"{scope8}{drive8}{VERSION}{kind:x}00{tail12}"
    body = f"{scope8}{drive8}{VERSION}{kind:x}{_check(zero)}{tail12}"
    return str(uuid.UUID(f"{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"))


def _digits(guid: str) -> str:
    try:
        return str(uuid.UUID(guid)).replace("-", "")
    except (ValueError, AttributeError, TypeError):
        raise IdentifierError(f"not a UUID: {guid!r}") from None


def host_id(lane: str, serial: str) -> str:
    """The identifier of the install on the drive with `serial`, made by the installer lane `lane` (that lane's UUID)."""
    if not isinstance(serial, str) or not _SERIAL.match(serial):
        raise IdentifierError("a drive's identifier needs its plain hardware serial, at least 8 characters")
    lane = str(uuid.UUID(lane))
    scope = lane.replace("-", "")[:8]
    drive = serial_hex(serial, 4) + serial_hex(serial, 4, from_end=True)
    return _assemble(scope, drive, KINDS["host"], _sha(f"host:{lane}:{serial}")[:12])


def child_id(parent: str, kind: str, name: str, *, counter: int = 0) -> str:
    """The identifier of the `kind` thing called `name` under `parent`. Pure: the same inputs give the same identifier."""
    if kind not in KINDS or kind == "host":
        raise IdentifierError(f"{kind!r} is not a kind that has a parent")
    if not isinstance(name, str) or not _NAME.match(name):
        raise IdentifierError("a name must be plain text of 1-128 characters")
    p = _digits(parent)
    if not is_valid(parent):
        raise IdentifierError("the parent is not a valid identifier")
    if int(p[17], 16) not in _PARENTS[kind]:
        raise IdentifierError(f"a {kind} cannot live under a {KIND_NAMES.get(int(p[17], 16), 'thing of that kind')}")
    own = _sha(f"{str(uuid.UUID(parent))}:{kind}:{name}:{counter}")[:8]
    scope = p[:8] if KINDS[kind] in LANE_KINDS else p[24:28] + class_code(name)
    return _assemble(scope, p[8:16], KINDS[kind], p[20:24] + own)


def is_valid(guid: str) -> bool:
    """Whether `guid` has this layout (version, a known kind digit) and its check byte matches."""
    try:
        d = _digits(guid)
    except IdentifierError:
        return False
    zero = d[:18] + "00" + d[20:]
    return d[16] == VERSION and int(d[17], 16) in KIND_NAMES and d[18:20] == _check(zero)


@dataclass(frozen=True)
class Parsed:
    version: str
    kind: str
    lane: str | None             # kinds 0-2
    parent_pointer: str | None   # kinds 3-4
    class_code: str | None       # kinds 3-4
    head: str
    tail: str
    check: str
    host_discriminator: str
    own: str


def parse(guid: str) -> Parsed:
    if not is_valid(guid):
        raise IdentifierError(f"{guid!r} is not an identifier of this layout")
    d = _digits(guid)
    kind = int(d[17], 16)
    lane_kind = kind in LANE_KINDS
    return Parsed(version=d[16], kind=KIND_NAMES[kind], lane=d[:8] if lane_kind else None,
                  parent_pointer=None if lane_kind else d[:4], class_code=None if lane_kind else d[4:8],
                  head=d[8:12], tail=d[12:16], check=d[18:20], host_discriminator=d[20:24], own=d[24:32])


def lane_prefix(guid: str) -> str | None:
    return parse(guid).lane


def same_drive(a: str, b: str) -> bool:
    """Whether two identifiers belong to the same install on the same drive, judged from the digits alone (the serial hint and the host
    discriminator); exact ancestry is the registry's `parent`."""
    x, y = _digits(a), _digits(b)
    return is_valid(a) and is_valid(b) and x[8:16] == y[8:16] and x[20:24] == y[20:24]


# --- the registry: one shape for every level ------------------------------------------------------------------------------

def _registry():
    import registry
    registry.register_type(REGISTRY_TYPE, "Baseline hierarchical identifiers: host installs, substrate, VMs, applications, hardware (DR255)",
                           default_scope=registry.GLOBAL)
    return registry


def _attributes(entry):
    return entry.get("attributes", entry) if isinstance(entry, dict) else {}


def register_host(host: str, *, serial: str) -> None:
    registry = _registry()
    registry.upsert_entry(REGISTRY_TYPE, host, scope=registry.GLOBAL, value={"by": "installer"},
                          attributes={"kind": "host", "level": 0, "serial": serial, "parent": None, "name": serial,
                                      "layout": VERSION, "counter": 0})


def mint(parent: str, kind: str, name: str) -> str:
    """The identifier of `kind` `name` under `parent`, registered with its parent and the drive's serial. Idempotent. If a different
    (parent, kind, name) already holds the identifier (about 1 in 4 billion per pair) the next counter is used and recorded."""
    registry = _registry()
    parent_entry = registry.get_entry(REGISTRY_TYPE, parent, scope=registry.GLOBAL)
    serial = _attributes(parent_entry).get("serial") if parent_entry else None
    for counter in range(16):
        candidate = child_id(parent, kind, name, counter=counter)
        existing = registry.get_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL)
        if existing is None:
            registry.upsert_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL, value={"by": "baseline"},
                                  attributes={"kind": kind, "level": KINDS[kind], "serial": serial, "parent": parent, "name": name,
                                              "layout": VERSION, "counter": counter})
            return candidate
        attrs = _attributes(existing)
        if (attrs.get("parent"), attrs.get("kind"), attrs.get("name")) == (parent, kind, name):
            return candidate
    raise IdentifierError("no free identifier after 16 counters; this should never happen")


def descendants(host: str) -> list:
    """Registered identifiers below `host`: everything on the same drive that names `host` as an ancestor."""
    registry = _registry()
    entries = registry.list_entries(REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)
    parents = {guid: _attributes(entry).get("parent") for guid, entry in entries.items()}

    def below(guid, seen=()):
        parent = parents.get(guid)
        if parent is None or parent in seen:
            return False
        return parent == host or below(parent, seen + (guid,))
    return sorted(guid for guid in parents if guid != host and below(guid))
