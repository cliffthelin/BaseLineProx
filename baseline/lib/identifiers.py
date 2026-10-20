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
    24-29    rest of the host hash    own id, 6 hex (hash of parent+kind+name)   same
    30-31    special handling (00)    special handling                    special handling

A child is derived from its parent, so it can be minted on the installed system with no installer present. Identifiers are stable: the
same parent, kind and name always give the same identifier. The check byte is integrity (typos, truncation), not authenticity.
The last two digits are reserved for special handling. `00` is the ordinary, deterministic identifier. Other values mark identifiers
that are handled differently; `02` is portable: digits 8-15 are only the origin hint, the registry parent is the authority and may change when the thing
moves to other hardware (`mint_portable`, `reparent`); the identifier itself never changes. `01` associates the identifier with an external UUID through a separate, non-deterministic cross-map
table (`map_external`). New special values are added to SPECIAL as they arise; readers treat an unknown value as special, never as ordinary.
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
SPECIAL = {"none": 0x00, "external": 0x01, "portable": 0x02}   # digits 30-31; 03-7f reserved for future handling, 80-ff for experiments
CROSS_MAP_TYPE = "baseline_external_map"
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
    return _assemble(scope, drive, KINDS["host"], _sha(f"host:{lane}:{serial}")[:10] + "00")


def child_id(parent: str, kind: str, name: str, *, counter: int = 0, special: int = 0, own: str | None = None) -> str:
    """The identifier of the `kind` thing called `name` under `parent`. Pure: the same inputs give the same identifier. `special` is the
    reserved last byte (SPECIAL); `own` supplies the 6 own-id digits explicitly (only the non-deterministic external mapping does)."""
    if not isinstance(special, int) or not 0 <= special <= 255:
        raise IdentifierError("special must be a byte")
    if own is not None and not re.fullmatch(r"[0-9a-f]{6}", own):
        raise IdentifierError("own must be 6 hex digits")
    if kind not in KINDS or kind == "host":
        raise IdentifierError(f"{kind!r} is not a kind that has a parent")
    if not isinstance(name, str) or not _NAME.match(name):
        raise IdentifierError("a name must be plain text of 1-128 characters")
    p = _digits(parent)
    if not is_valid(parent):
        raise IdentifierError("the parent is not a valid identifier")
    if int(p[17], 16) not in _PARENTS[kind]:
        raise IdentifierError(f"a {kind} cannot live under a {KIND_NAMES.get(int(p[17], 16), 'thing of that kind')}")
    own = own or _sha(f"{str(uuid.UUID(parent))}:{kind}:{name}:{counter}")[:6]
    scope = p[:8] if KINDS[kind] in LANE_KINDS else p[24:28] + class_code(name)
    return _assemble(scope, p[8:16], KINDS[kind], p[20:24] + own + format(special, "02x"))


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
    special: int


def parse(guid: str) -> Parsed:
    if not is_valid(guid):
        raise IdentifierError(f"{guid!r} is not an identifier of this layout")
    d = _digits(guid)
    kind = int(d[17], 16)
    lane_kind = kind in LANE_KINDS
    return Parsed(version=d[16], kind=KIND_NAMES[kind], lane=d[:8] if lane_kind else None,
                  parent_pointer=None if lane_kind else d[:4], class_code=None if lane_kind else d[4:8],
                  head=d[8:12], tail=d[12:16], check=d[18:20], host_discriminator=d[20:24], own=d[24:30], special=int(d[30:32], 16))


def lane_prefix(guid: str) -> str | None:
    return parse(guid).lane


def stamped_lane(guid, serial) -> str | None:
    """The installer lane (8 hex digits) a drive's disk GUID says installed it, or None. Only a well-formed HOST identifier whose serial hint matches THIS drive's own serial counts, so a
    copied or unrelated GUID says nothing; this is how a drive is recognised as another lane's without any table of serials."""
    try:
        parsed = parse(str(uuid.UUID(str(guid))))
    except (ValueError, IdentifierError):
        return None
    if parsed.kind != "host" or not isinstance(serial, str) or not _SERIAL.match(serial):
        return None
    if parsed.head != serial_hex(serial, 4) or parsed.tail != serial_hex(serial, 4, from_end=True):
        return None
    return parsed.lane


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


def mint(parent: str, kind: str, name: str, *, source: dict | None = None) -> str:
    """The identifier of `kind` `name` under `parent`, registered with its parent and the drive's serial. Idempotent. If a different
    (parent, kind, name) already holds the identifier (about 1 in 4 billion per pair) the next counter is used and recorded.
    `source` ({"type": ..., "id": ...}) names the entry of another registry this identifier stands for (references.py)."""
    registry = _registry()
    parent_entry = registry.get_entry(REGISTRY_TYPE, parent, scope=registry.GLOBAL)
    serial = _attributes(parent_entry).get("serial") if parent_entry else None
    for counter in range(16):
        candidate = child_id(parent, kind, name, counter=counter)
        existing = registry.get_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL)
        if existing is None:
            registry.upsert_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL, value={"by": "baseline"},
                                  attributes={"kind": kind, "level": KINDS[kind], "serial": serial, "parent": parent, "name": name,
                                              "layout": VERSION, "counter": counter, "source": source})
            return candidate
        attrs = _attributes(existing)
        if (attrs.get("parent"), attrs.get("kind"), attrs.get("name")) == (parent, kind, name):
            if source is not None and attrs.get("source") != source:
                registry.upsert_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL, value=existing.get("value"),
                                      attributes=dict(attrs, source=source))
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


# --- special handling: external UUIDs (digits 30-31 = 01) -------------------------------------------------------------------

def _cross_map():
    import registry
    registry.register_type(CROSS_MAP_TYPE, "Baseline identifier <-> external UUID cross-map; non-deterministic by design (DR255)",
                           default_scope=registry.GLOBAL)
    return registry


SCHEMES = ("uuid", "serial", "partuuid", "fsuuid", "vguuid", "pvuuid", "luks", "gptguid", "mac", "cdi", "vmid", "machine-id", "dmi", "other")
_SCHEME_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+/-]{0,127}$")


def _external_key(external: str, scheme: str) -> str:
    """The cross-map key `scheme:value`; UUIDs are normalised to lower-case canonical form, every other value is taken as written."""
    if scheme not in SCHEMES:
        raise IdentifierError(f"unknown external scheme {scheme!r}; one of {', '.join(SCHEMES)}")
    if scheme in ("uuid", "partuuid", "fsuuid", "vguuid", "pvuuid", "luks", "gptguid", "cdi", "machine-id"):
        try:
            return f"{scheme}:{uuid.UUID(external.removeprefix('GPU-') if scheme == 'cdi' else external)}"
        except (ValueError, AttributeError, TypeError):
            raise IdentifierError(f"not a UUID for scheme {scheme!r}: {external!r}") from None
    if not isinstance(external, str) or not _SCHEME_VALUE.match(external):
        raise IdentifierError(f"not a valid {scheme} value: {external!r}")
    return f"{scheme}:{external.lower() if scheme == 'mac' else external}"


def map_external(parent: str, kind: str, name: str, external: str, *, scheme: str = "uuid") -> str:
    """The identifier associated with `external`, a value from outside Baseline (a disk, partition, filesystem, VG, LUKS or GPU UUID, a
    MAC, a Proxmox VMID, a serial) named by its `scheme`. The first call picks a random own id and records the pair in the cross-map
    table; later calls return the same identifier, so the association is stable even though it is not derivable from the inputs.
    Use it for things Baseline did not name itself; things it names itself are minted with `mint` (deterministic)."""
    key = _external_key(external, scheme)
    registry = _cross_map()
    found = lookup_external(external, scheme=scheme)
    if found:
        return found
    _registry()
    for _ in range(16):
        candidate = child_id(parent, kind, name, special=SPECIAL["external"], own=uuid.uuid4().hex[:6])
        if registry.get_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL) is None:
            registry.upsert_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL, value={"by": "baseline"},
                                  attributes={"kind": kind, "level": KINDS[kind], "parent": parent, "name": name,
                                              "layout": VERSION, "special": SPECIAL["external"], "external": key})
            registry.upsert_entry(CROSS_MAP_TYPE, key, scope=registry.GLOBAL, value={"id": candidate},
                                  attributes={"id": candidate, "scheme": scheme})
            return candidate
    raise IdentifierError("no free identifier for an external mapping")


def lookup_external(external: str, *, scheme: str = "uuid") -> str | None:
    try:
        key = _external_key(external, scheme)
    except IdentifierError:
        return None
    registry = _cross_map()
    entry = registry.get_entry(CROSS_MAP_TYPE, key, scope=registry.GLOBAL)
    return _attributes(entry).get("id") if entry else None


def external_of(guid: str) -> str | None:
    """The `scheme:value` key an external identifier was recorded under, or None."""
    registry = _cross_map()
    entry = registry.get_entry(REGISTRY_TYPE, guid, scope=registry.GLOBAL)
    return _attributes(entry).get("external") if entry else None


# --- special handling: portable identities (digits 30-31 = 02) -------------------------------------------------------------

def mint_portable(parent: str, kind: str, name: str, *, source: dict | None = None) -> str:
    """Like `mint`, for a thing that must outlive the hardware it sits on (a persistence store, application data, a VM's retained state).
    Deterministic from its first parent, so every rebuild finds the same identifier; afterwards `reparent` moves it."""
    registry = _registry()
    parent_entry = registry.get_entry(REGISTRY_TYPE, parent, scope=registry.GLOBAL)
    serial = _attributes(parent_entry).get("serial") if parent_entry else None
    candidate = child_id(parent, kind, name, special=SPECIAL["portable"])
    existing = registry.get_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL)
    if existing is None:
        registry.upsert_entry(REGISTRY_TYPE, candidate, scope=registry.GLOBAL, value={"by": "baseline"},
                              attributes={"kind": kind, "level": KINDS[kind], "serial": serial, "parent": parent, "name": name,
                                          "layout": VERSION, "special": SPECIAL["portable"], "origin": parent, "source": source})
    return candidate


def reparent(guid: str, new_parent: str) -> None:
    """Move a portable identifier under another parent (the drive or machine it now lives on). The identifier is unchanged; the registry
    records the move. Anything not portable keeps its parent for life: refused."""
    registry = _registry()
    entry = registry.get_entry(REGISTRY_TYPE, guid, scope=registry.GLOBAL)
    if entry is None:
        raise IdentifierError(f"{guid} is not registered")
    attrs = _attributes(entry)
    if attrs.get("special") != SPECIAL["portable"] or parse(guid).special != SPECIAL["portable"]:
        raise IdentifierError("only a portable identifier (special 02) may change parent")
    if not is_valid(new_parent) or int(_digits(new_parent)[17], 16) not in _PARENTS[attrs["kind"]]:
        raise IdentifierError("the new parent is not a valid parent for this kind of thing")
    target = registry.get_entry(REGISTRY_TYPE, new_parent, scope=registry.GLOBAL)
    registry.upsert_entry(REGISTRY_TYPE, guid, scope=registry.GLOBAL, value=entry.get("value"),
                          attributes=dict(attrs, parent=new_parent, serial=_attributes(target).get("serial") if target else attrs.get("serial"),
                                          moved_from=attrs.get("parent")))
