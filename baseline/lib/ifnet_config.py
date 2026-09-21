#!/usr/bin/env python3
"""ifupdown2-style /etc/network/interfaces parsing, rewriting, and hashing -
the host-network repair slice's read/write layer over persisted network
config.

Deliberately pure: every function here takes text or a Runner (see
repair.py) and returns text or data - no bare `open()`/`subprocess.run()`
calls of its own. That's what makes the topology-derivation and
stanza-rewrite logic unit-testable against fixture files with no root, no
real device, and no real interfaces file touched (see
docs/design/reset-interface-to-dhcp-plan.md's test strategy).

Scope: `inet`/`inet6` stanzas (`static`/`dhcp`/`manual`/`loopback`), `auto`/
`allow-hotplug` lines, and `source`/`source-directory`/glob-form `source`
inclusion. Anything else Baseline's parser doesn't confidently recognize
(`mapping` blocks, a stanza name appearing twice) is recorded rather than
guessed at - `confidently_parsed` goes false and callers must refuse
rather than rewrite.

`rewrite_stanza_to_dhcp` (replace an existing `inet static` stanza) and
`add_dhcp_stanza` (append a new `inet dhcp` stanza alongside an existing
non-inet, e.g. `inet6 static`, one - never deleting or rewriting it) are
the two supported repair shapes; see topology.py's `derive_target` /
`derive_additive_target` for which one applies to a given topology.
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field

IFACE_RE = re.compile(r"^\s*iface\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
AUTO_RE = re.compile(r"^\s*auto\s+(.+)$")
HOTPLUG_RE = re.compile(r"^\s*allow-hotplug\s+(.+)$")
SOURCE_RE = re.compile(r"^\s*source\s+(\S+)\s*$")
SOURCE_DIR_RE = re.compile(r"^\s*source-directory\s+(\S+)\s*$")
OPTION_RE = re.compile(r"^\s+(\S+)\s+(.+?)\s*$")  # indented "key value" line
COMMENT_OR_BLANK_RE = re.compile(r"^\s*(#.*)?$")

_GLOB_METACHARS = frozenset("*?[")


def _has_glob_metachars(target: str) -> bool:
    return any(ch in target for ch in _GLOB_METACHARS)


def resolve_source_glob(pattern: str, directory_entries: list[str]) -> list[str]:
    """Pure glob resolution: given a `source <pattern>` target (e.g.
    "/etc/network/interfaces.d/*") and the list of entries already
    listed in its parent directory (I/O done by the caller, via
    Runner.listdir - see repair.read_interfaces_config), return the
    subset that match, sorted for determinism. Minimal on purpose - this
    only needs to handle the one shape Proxmox's automated installer is
    confirmed (Milestone 1 Phase 0) to actually generate
    ("source /etc/network/interfaces.d/*"), not arbitrary shell-glob
    syntax; `fnmatch` is sufficient for that and is stdlib, no new
    dependency.
    """
    matched = [entry for entry in directory_entries if fnmatch.fnmatch(entry, pattern)]
    return sorted(matched)


# Options that name other stanzas as members - the reverse-reference edges
# topology.py walks. Values are whitespace-separated device-name lists,
# except vlan-raw-device (single name).
MEMBER_LIST_OPTIONS = ("bridge-ports", "bond-slaves")
MEMBER_SINGLE_OPTIONS = ("vlan-raw-device",)


@dataclass
class Stanza:
    name: str
    family: str  # "inet", "inet6", ...
    method: str  # "static", "dhcp", "manual", "loopback", ...
    options: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)   # raw source lines, iface line first
    source_path: str = ""
    line_start: int = -1  # index into files[source_path].splitlines(), for rewriting
    line_end: int = -1    # exclusive


@dataclass
class ParsedConfig:
    stanzas: dict = field(default_factory=dict)     # name -> Stanza (first occurrence wins; duplicates recorded)
    order: list = field(default_factory=list)
    files: dict = field(default_factory=dict)        # path -> raw text, every file actually read
    duplicate_names: set = field(default_factory=set)
    unparsed_lines: list = field(default_factory=list)   # (path, lineno, text) - directives we didn't confidently model
    read_errors: list = field(default_factory=list)      # (path, detail) - a sourced file that couldn't be read
    glob_source_targets: list = field(default_factory=list)  # (path, lineno, pattern) - a `source <glob>`
        # directive; informational only (see _parse_text) - resolved via
        # I/O by repair.read_interfaces_config / resolve_source_glob
        # below, not by this module directly.

    @property
    def confidently_parsed(self) -> bool:
        return not self.duplicate_names and not self.unparsed_lines and not self.read_errors


def _member_names(stanza: Stanza) -> list[str]:
    out = []
    for opt in MEMBER_LIST_OPTIONS:
        if opt in stanza.options:
            out.extend(stanza.options[opt].split())
    for opt in MEMBER_SINGLE_OPTIONS:
        if opt in stanza.options:
            out.append(stanza.options[opt])
    return out


def bridge_members(stanza: Stanza) -> list[str]:
    return stanza.options.get("bridge-ports", "").split()


def bond_members(stanza: Stanza) -> list[str]:
    return stanza.options.get("bond-slaves", "").split()


def vlan_parent(stanza: Stanza) -> str | None:
    return stanza.options.get("vlan-raw-device")


def classify(stanza: Stanza) -> str:
    """physical | bridge | bond | vlan | unknown - purely from the stanza's
    own declared options, never from guessing at the device name."""
    if "bridge-ports" in stanza.options:
        return "bridge"
    if "bond-slaves" in stanza.options:
        return "bond"
    if "vlan-raw-device" in stanza.options:
        return "vlan"
    if stanza.name == "lo" or stanza.method == "loopback":
        return "loopback"
    return "physical"


def _parse_text(path: str, text: str, cfg: ParsedConfig) -> list[str]:
    """Parse one file's text into cfg in place. Returns the list of
    `source`/`source-directory` targets this file names, for the caller to
    resolve and recurse into (resolution is I/O and stays out of this
    module - see repair.py's read_interfaces_config)."""
    lines = text.splitlines()
    includes: list[str] = []
    i = 0
    current: Stanza | None = None

    def close_current():
        nonlocal current
        if current is None:
            return
        current.line_end = i
        if current.name in cfg.stanzas:
            cfg.duplicate_names.add(current.name)
        else:
            cfg.stanzas[current.name] = current
            cfg.order.append(current.name)
        current = None

    while i < len(lines):
        line = lines[i]
        m = IFACE_RE.match(line)
        if m:
            close_current()
            name, family, method = m.group(1), m.group(2), m.group(3)
            current = Stanza(name=name, family=family, method=method,
                              lines=[line], source_path=path, line_start=i, line_end=i + 1)
            i += 1
            continue
        if current is not None:
            om = OPTION_RE.match(line)
            if om:
                current.options[om.group(1)] = om.group(2)
                current.lines.append(line)
                i += 1
                continue
            if COMMENT_OR_BLANK_RE.match(line):
                # blank/comment inside a stanza's block doesn't end it in
                # real ifupdown files, but we stay conservative: only a
                # blank line ends the block here, matching how ifupdown2's
                # own parser treats stanza boundaries. A comment is kept
                # inside; a blank line closes.
                if line.strip() == "":
                    close_current()
                i += 1
                continue
            # A non-indented, non-comment, non-iface line while inside a
            # stanza (e.g. a second directive glued on) - not confidently
            # modeled, close the stanza and fall through to top-level
            # handling for this line instead of guessing.
            close_current()
        sm = SOURCE_RE.match(line)
        if sm:
            target = sm.group(1)
            if _has_glob_metachars(target):
                # A real, standard Debian/Proxmox directive
                # ("source /etc/network/interfaces.d/*" - confirmed to be
                # exactly what the automated Proxmox installer generates,
                # and present in every Milestone 1 Phase 0 fixture) that
                # names a glob pattern, not a literal path. This module
                # has no filesystem access (by design - see the module
                # docstring), so it cannot itself expand the glob; it
                # records the pattern for the caller (repair.py's
                # read_interfaces_config, which does have I/O access via
                # Runner.listdir) to resolve. This is purely informational
                # here - it does NOT break confidence, since a
                # successfully-resolved glob is not an unconfident parse.
                # The bug this replaces: previously, a caller that didn't
                # special-case glob characters would try to open the
                # literal string "/etc/network/interfaces.d/*" as a file
                # path, get OSError, and silently treat it as an empty
                # file - which could hide real fragment files instead of
                # reading them. See ifnet_config.resolve_source_glob and
                # repair.read_interfaces_config for the actual resolution.
                cfg.glob_source_targets.append((path, i, target))
                i += 1
                continue
            includes.append(("source", target))
            i += 1
            continue
        sdm = SOURCE_DIR_RE.match(line)
        if sdm:
            includes.append(("source-directory", sdm.group(1)))
            i += 1
            continue
        if AUTO_RE.match(line) or HOTPLUG_RE.match(line) or COMMENT_OR_BLANK_RE.match(line):
            i += 1
            continue
        # Anything else at top level (mapping blocks, directives this
        # parser doesn't know) - record, don't guess.
        cfg.unparsed_lines.append((path, i, line))
        i += 1
    close_current()
    return [target for _kind, target in includes]


def parse_files(files: dict) -> ParsedConfig:
    """`files`: {path: text} for every file already read (the main
    interfaces file plus every resolved `source`/`source-directory`
    target) - resolution and reading are the caller's job (repair.py),
    so this stays pure and test-fixture-friendly. Re-runs `_parse_text`
    per file and merges; encounter order is `files`' own dict order."""
    cfg = ParsedConfig(files=dict(files))
    for path, text in files.items():
        _parse_text(path, text, cfg)
    return cfg


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_closure(files: dict) -> str:
    """One stable hash over the whole set of files a reload would read -
    order-independent (sorted by path) so it doesn't spuriously change
    just because dict iteration order did."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(files[path].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class RewriteError(ValueError):
    pass


def rewrite_stanza_to_dhcp(cfg: ParsedConfig, target_name: str) -> dict:
    """Return {path: new_full_text} with ONLY `target_name`'s stanza
    replaced by a bare `iface <name> inet dhcp` line - every other line in
    every file is byte-identical to the input, including the file the
    target stanza isn't in. Raises RewriteError rather than guessing if
    the stanza is missing, isn't static, or the parse wasn't confident
    enough to safely locate its exact line range."""
    if not cfg.confidently_parsed:
        raise RewriteError("refusing to rewrite: interfaces config was not confidently parsed "
                            f"(duplicates={cfg.duplicate_names!r}, "
                            f"unparsed={[l[2] for l in cfg.unparsed_lines]!r})")
    stanza = cfg.stanzas.get(target_name)
    if stanza is None:
        raise RewriteError(f"no stanza named {target_name!r} found")
    if stanza.family != "inet" or stanza.method != "static":
        raise RewriteError(f"{target_name!r} is {stanza.family} {stanza.method}, not inet static - nothing to reset")

    original = cfg.files[stanza.source_path]
    lines = original.splitlines(keepends=True)
    # Reconstruct with keepends so the replacement doesn't have to guess
    # the file's own line-ending convention.
    before = lines[:stanza.line_start]
    after = lines[stanza.line_end:]
    ending = "\n"
    if lines and lines[stanza.line_start].endswith("\r\n"):
        ending = "\r\n"
    new_stanza_line = f"iface {stanza.name} inet dhcp{ending}"
    new_text = "".join(before) + new_stanza_line + "".join(after)

    out = dict(cfg.files)
    out[stanza.source_path] = new_text
    return out


def add_dhcp_stanza(cfg: ParsedConfig, target_name: str) -> dict:
    """Additive repair: append a NEW `iface <target_name> inet dhcp`
    stanza to the end of the file that already declares `target_name`,
    leaving that existing stanza - and every other line in every file -
    byte-identical to the input. This is the counterpart to
    rewrite_stanza_to_dhcp for the case where `target_name` has no
    `inet` stanza at all yet (only a non-inet, e.g. `inet6 static`, one)
    - see topology.derive_additive_target. Never deletes or rewrites the
    existing stanza; the two families coexist as separate `iface`
    blocks, which is standard, valid ifupdown2 syntax for dual-stack
    configuration.

    Known, accepted limitation (documented, not fixed here): this
    module's own ParsedConfig keys stanzas by name only, so if the file
    produced here is re-parsed by this same parser, the coexisting
    `inet6 static` and `inet dhcp` stanzas (same name, different
    family) will be reported as a duplicate name and `confidently_parsed`
    will be False - meaning no further automated repair action can
    target this interface again until a human resolves it. This is a
    real gap in this parser's data model (Stanza should ideally be keyed
    by (name, family), not name alone), but is safely fail-closed rather
    than silently wrong: after this additive fix applies, any future
    repair attempt against this interface refuses rather than guessing
    which stanza to touch.
    """
    if not cfg.confidently_parsed:
        raise RewriteError("refusing to rewrite: interfaces config was not confidently parsed "
                            f"(duplicates={cfg.duplicate_names!r}, "
                            f"unparsed={[l[2] for l in cfg.unparsed_lines]!r}, "
                            f"glob_source_targets={[g[2] for g in cfg.glob_source_targets]!r})")
    stanza = cfg.stanzas.get(target_name)
    if stanza is None:
        raise RewriteError(f"no stanza named {target_name!r} found")
    if stanza.family == "inet":
        raise RewriteError(f"{target_name!r} already has an inet stanza ({stanza.method}) - "
                            "use rewrite_stanza_to_dhcp for a replace, not an additive add")
    if stanza.method != "static":
        raise RewriteError(f"{target_name!r} is {stanza.family} {stanza.method}, not static - "
                            "nothing for an additive DHCP stanza to attach to")

    original = cfg.files[stanza.source_path]
    ending = "\n"
    if stanza.lines and stanza.lines[0].endswith("\r\n"):
        # Stanza.lines are stored without their original line terminator
        # (str.splitlines() strips it) - this branch is defensive and
        # will not trigger against Stanza.lines as currently populated;
        # kept only so a future change to how lines are captured fails
        # loud (wrong ending) rather than silent, not to claim CRLF
        # support that hasn't actually been tested.
        ending = "\r\n"
    text = original if original.endswith(ending) else original + ending
    new_block = f"iface {target_name} inet dhcp{ending}"
    new_text = text + new_block

    out = dict(cfg.files)
    out[stanza.source_path] = new_text
    return out
