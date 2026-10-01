"""Constant, fixed-length identifiers for everything Baseline names.

Direct instruction, 2026-09-30. The identifier is a code and only a
code - a human name never forms part of it. Names exist solely as
aliases (symlinks) pointing at the constant, the way /dev/disk/by-label
points at a device:

    <L>_<M>_<NNNNN>        always ID_LENGTH (9) characters

    L      layer cluster   U User, A App, S Substrate, O Operating System
    M      medium          see MEDIA
    NNNNN  code            five characters; numeric by default, allocated
                           once and never reused or renumbered

    A_C_00001   -> by-name/caddy
    O_I_00001   -> by-name/proxmox-ve

Why each rule exists:

- **Fixed length.** ext4 labels are 16 characters and every old name that
  ran past that truncated: USER_PERSISTENCE_ADMIN and _PERSONAL both
  became USER_PERSISTENCE. Nine characters never truncates, for any
  persona name, forever.
- **`_` as both separators.** `_` passes through systemd unit-name
  escaping untouched (`-` becomes `\\x2d`, `+` becomes `\\x2b`), is kept
  by udev in /dev/disk/by-label, and is safe in overlay options, podman
  bind syntax and fstab - unlike `:` `,` `=` `%` `@`.
- **Uppercase and digits only in the code.** Owner uids are derived by
  lowercasing the identifier; with no lowercase letters allowed, that
  mapping is one-to-one, so two identifiers can never share a uid.
- **Allocated once, never reused.** A number computed from the current
  set would renumber everything after a removal - the same hazard that
  moved a persona's partition from 6 to 7 on the real Baseline drive. Every
  allocation is recorded in the registry and only ever *retired*, so the
  stored set is a permanent high-water mark.
- **Aliases are never a mount path.** Mounts, overlays, binds and owner
  uids reference the constant. An alias is a symlink; if anything could
  rewrite one, it could redirect a mount into another application's
  data. `assert_canonical` makes that a checked rule, and alias
  directories are root-owned and not writable by any application.

Planning only: this module validates, allocates in the registry and
computes alias paths. It never creates a symlink, a user or a directory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import registry

ID_LENGTH = 9
SEPARATOR = "_"
CODE_LENGTH = 5
MAX_NUMERIC = 10 ** CODE_LENGTH - 1

CLUSTERS = {
    "U": "User",
    "A": "App",
    "S": "Substrate",
    "O": "Operating System",
}

# F/A/S were specified directly (Flatpak, AppImage, Snap) and I (ISO)
# was kept from review; D/C/L/V/N cover the media the codebase already
# installs today (deb packages, OCI images, LXC guests, VMs) and Nix.
MEDIA = {
    "D": "deb package",
    "C": "OCI container",
    "L": "LXC guest",
    "V": "VM",
    "F": "Flatpak",
    "A": "AppImage",
    "S": "Snap",
    "N": "Nix",
    "I": "ISO image",
}

_ID_RE = re.compile(
    rf"^(?P<cluster>[{''.join(CLUSTERS)}]){SEPARATOR}"
    rf"(?P<medium>[{''.join(MEDIA)}]){SEPARATOR}"
    rf"(?P<code>[0-9A-Z]{{{CODE_LENGTH}}})$"
)
_CODE_RE = re.compile(rf"^[0-9A-Z]{{{CODE_LENGTH}}}$")

ALIAS_DIRNAME = "by-name"
ALIAS_DIR_OWNER = "root"
ALIAS_DIR_MODE = "0755"   # readable by all, writable by root only
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")

REGISTRY_TYPE = "baseline_ids"
COUNTER_TYPE = "baseline_id_counters"
SCOPE = registry.GLOBAL


class NamingError(ValueError):
    pass


@dataclass(frozen=True)
class BaselineId:
    cluster: str
    medium: str
    code: str

    def __str__(self) -> str:
        return SEPARATOR.join((self.cluster, self.medium, self.code))

    @property
    def owner_name(self) -> str:
        """The owner uid's name. Lowercasing is one-to-one because the
        code allows no lowercase letters."""
        return f"baseline-{str(self).lower()}"


# -- Format and parse --------------------------------------------------

def format_id(cluster: str, medium: str, code: str) -> str:
    if cluster not in CLUSTERS:
        raise NamingError(f"unknown cluster {cluster!r}; one of {sorted(CLUSTERS)}")
    if medium not in MEDIA:
        raise NamingError(f"unknown medium {medium!r}; one of {sorted(MEDIA)}")
    if not _CODE_RE.match(code or ""):
        raise NamingError(f"code must be {CODE_LENGTH} characters of 0-9 or A-Z, got {code!r}")
    value = SEPARATOR.join((cluster, medium, code))
    assert len(value) == ID_LENGTH
    return value


def parse_id(value: str) -> BaselineId:
    m = _ID_RE.match(value or "")
    if not m:
        raise NamingError(f"{value!r} is not a Baseline identifier (<L>_<M>_<NNNNN>)")
    return BaselineId(m["cluster"], m["medium"], m["code"])


def is_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def numeric_code(n: int) -> str:
    if not 1 <= n <= MAX_NUMERIC:
        raise NamingError(f"numeric code out of range 1-{MAX_NUMERIC}: {n}")
    return f"{n:0{CODE_LENGTH}d}"


# -- Allocation (registry-backed, never reused) ------------------------

def _ensure_types() -> None:
    registry.register_type(REGISTRY_TYPE, "Allocated Baseline identifiers (naming.py) - never deleted, only retired",
                           default_scope=SCOPE)
    registry.register_type(COUNTER_TYPE, "Per-cluster numeric high-water marks (naming.py)",
                           default_scope=SCOPE)


def allocated(*, read_only: bool = False) -> dict:
    """Every identifier ever allocated, retired ones included.
    `read_only=True` never creates the registry - for page views."""
    if read_only:
        return registry.list_entries(REGISTRY_TYPE, scope=SCOPE, read_only=True)
    _ensure_types()
    return registry.list_entries(REGISTRY_TYPE, scope=SCOPE)


@dataclass(frozen=True)
class Assignment:
    value: str
    allocated: bool     # False = a preview of what allocation would assign; not reserved


def preview(requests) -> dict:
    """What `allocate_many(requests)` would return, computed without
    writing anything. Already-allocated subjects come back with
    allocated=True; the rest are numbered the way allocation would number
    them right now, marked allocated=False because nothing reserves them -
    a concurrent allocation could take the same code first.

    `requests` is an iterable of (cluster, medium, subject)."""
    existing = allocated(read_only=True)
    counters = registry.list_entries(COUNTER_TYPE, scope=SCOPE, read_only=True)
    by_subject = {(e["attributes"].get("cluster"), e["attributes"].get("medium"),
                   e["attributes"].get("subject")): value for value, e in existing.items()}
    taken: dict = {}
    for value in existing:
        taken.setdefault(value[0], set()).add(parse_id(value).code)
    next_n = {c: max(int((counters.get(c) or {}).get("value") or 1), 1) for c in CLUSTERS}

    out = {}
    for cluster, medium, subject in requests:
        hit = by_subject.get((cluster, medium, subject))
        if hit:
            out[subject] = Assignment(hit, True)
            continue
        codes = taken.setdefault(cluster, set())
        n = next_n[cluster]
        while numeric_code(n) in codes:
            n += 1
        codes.add(numeric_code(n))
        next_n[cluster] = n + 1
        out[subject] = Assignment(format_id(cluster, medium, numeric_code(n)), False)
    return out


def allocate_many(requests) -> dict:
    """Allocate every request, returning subject -> identifier. Writes
    the registry; call from an explicit provisioning step, never a view."""
    return {subject: allocate(cluster, medium, subject) for cluster, medium, subject in requests}


def find(cluster: str, medium: str, subject: str) -> str | None:
    """The identifier already allocated to `subject` in this cluster and
    medium, if any - allocation is idempotent per subject."""
    for value, entry in allocated().items():
        a = entry["attributes"]
        if a.get("cluster") == cluster and a.get("medium") == medium and a.get("subject") == subject:
            return value
    return None


def _taken_codes(cluster: str) -> set:
    """Codes are unique per cluster regardless of medium, so a number
    alone identifies one thing within its cluster."""
    return {parse_id(v).code for v in allocated() if v.startswith(cluster + SEPARATOR)}


def allocate(cluster: str, medium: str, subject: str, *, code: str | None = None) -> str:
    """Allocate (or return the existing) identifier for `subject`.

    `subject` is internal provenance - what this identifier was created
    for, e.g. an installer catalog id - stored as an attribute. It is
    never part of the identifier. `code` may be an explicit five-character
    code; otherwise the next unused number in the cluster is taken."""
    format_id(cluster, medium, code or "00001")      # validates cluster/medium early
    existing = find(cluster, medium, subject)
    if existing:
        return existing

    taken = _taken_codes(cluster)
    if code is not None:
        if code in taken:
            raise NamingError(f"code {code} is already allocated in cluster {cluster}")
        chosen = code
    else:
        counter = registry.get_entry(COUNTER_TYPE, cluster, scope=SCOPE)
        n = max(int((counter or {}).get("value") or 1), 1)
        while numeric_code(n) in taken:
            n += 1
        chosen = numeric_code(n)
        registry.upsert_entry(COUNTER_TYPE, cluster, attributes={"cluster": cluster},
                              scope=SCOPE, value=n + 1)

    value = format_id(cluster, medium, chosen)
    registry.upsert_entry(REGISTRY_TYPE, value, scope=SCOPE, value={"retired": False},
                          attributes={"cluster": cluster, "medium": medium,
                                      "code": chosen, "subject": subject})
    return value


def retire(value: str) -> None:
    """Mark an identifier no longer in use. The entry stays, so its code
    is never handed out again."""
    parse_id(value)
    if registry.get_entry(REGISTRY_TYPE, value, scope=SCOPE) is None:
        raise NamingError(f"{value} was never allocated")
    registry.set_value(REGISTRY_TYPE, value, {"retired": True}, scope=SCOPE)


def is_retired(value: str) -> bool:
    entry = registry.get_entry(REGISTRY_TYPE, value, scope=SCOPE)
    return bool(entry and (entry.get("value") or {}).get("retired"))


# -- Aliases -----------------------------------------------------------

def validate_alias(alias: str) -> str:
    """A human name for an identifier. It may not itself look like an
    identifier: an alias called A_C_00002 pointing at A_C_00001 would be
    a trap for anyone reading the tree."""
    if not _ALIAS_RE.match(alias or ""):
        raise NamingError(f"alias {alias!r} must be 1-63 characters of A-Z a-z 0-9 . _ - "
                          f"and start with a letter or digit")
    if is_id(alias):
        raise NamingError(f"alias {alias!r} has the form of an identifier")
    return alias


def alias_dir(base: str) -> str:
    """Where aliases live under a base directory (e.g. a persona's AppData
    root). One per base, so aliases are naturally per persona."""
    return f"{base.rstrip('/')}/{ALIAS_DIRNAME}"


@dataclass(frozen=True)
class AliasLink:
    link: str        # the symlink's own path
    target: str      # relative, so the tree survives being mounted elsewhere
    owner: str = ALIAS_DIR_OWNER
    dir_mode: str = ALIAS_DIR_MODE


def alias_link(base: str, alias: str, value: str) -> AliasLink:
    validate_alias(alias)
    parse_id(value)
    return AliasLink(link=f"{alias_dir(base)}/{alias}", target=f"../{value}")


def canonical_path(base: str, value: str) -> str:
    parse_id(value)
    return f"{base.rstrip('/')}/{value}"


def assert_canonical(path: str) -> str:
    """Refuse any path that goes through an alias directory. Mounts,
    overlays, binds and ownership must reference the constant: a path
    via a symlink would follow whatever the symlink points at when the
    mount happens."""
    parts = [p for p in path.split("/") if p]
    if ALIAS_DIRNAME in parts:
        raise NamingError(f"{path!r} goes through {ALIAS_DIRNAME}/ - mount by identifier, never by alias")
    return path
