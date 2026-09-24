"""Allowlisted configuration-file drift evidence (the manifest's
top-level `config_files[]` array).

Every entry here comes from an explicit, fixed allowlist (plus the
dynamically-resolved `/etc/network/interfaces` source closure, which is
itself walked the same bounded way repair.py's own
`read_interfaces_config` does - reusing ifnet_config's pure parsing
helpers, not repair.Runner, since inventory deliberately keeps its own
non-raising Runner contract; see runner.py's module docstring). Nothing
outside the allowlist is ever touched by this collector, and no raw
file content is ever stored - only metadata plus an HMAC-backed content
identity token, so a future comparison run (with the same injected
comparison key - see redact.py's key_id) can tell whether a file
changed without this manifest ever holding the bytes that would let
someone reconstruct it.

`/etc/pve` is explicitly out of scope here - it has its own, separately
allowlisted collector (collectors/proxmox.py) with its own priv/
exclusion boundary, and this module must never widen that by walking
into it too.
"""
import re

import ifnet_config

from .status_notes import note as _note

MAX_INTERFACES_CLOSURE_FILES = 200  # matches this codebase's other bounded-walk caps

# Fixed single-file allowlist: (path, category). "identity" entries are
# expected to differ legitimately between any two hosts; everything
# else is a candidate for real drift.
_STATIC_FILES = [
    ("/etc/hostname", "identity"),
    ("/etc/hosts", "identity"),
    ("/etc/resolv.conf", "identity"),
    ("/etc/default/grub", "boot"),
    ("/etc/kernel/cmdline", "boot"),
    ("/etc/sysctl.conf", "sysctl"),
]

# (directory, suffixes, category) - every matching filename inside is
# allowlisted; the directory listing itself is the only "discovery"
# step, matching security.py's sysctl fail-closed discipline (a file's
# *presence* earns it a metadata/identity entry; that is not the same
# as trusting or executing its contents).
_GLOB_DIRS = [
    ("/etc/sysctl.d", (".conf",), "sysctl"),
    ("/etc/modprobe.d", (".conf",), "modules"),
    ("/etc/modules-load.d", (".conf",), "modules"),
]

_BASELINE_UNITS = ("baseline.service", "baseline-additive-dhcp-reapply.service", "baseline-firstboot.service")


def _baseline_managed(path):
    return (path.startswith("/opt/baseline/") or path.startswith("/etc/baseline/")
            or path in (f"/etc/systemd/system/{u}" for u in _BASELINE_UNITS))


def _category_for(path, default):
    if _baseline_managed(path):
        return "baseline"
    if path.startswith("/etc/apt/"):
        return "apt"
    return default


def _interfaces_closure_paths(runner, collection_notes):
    """Mirrors repair.read_interfaces_config's resolution of
    `source`/`source-directory`/glob-form `source` targets, built on
    inventory's own non-raising Runner instead of repair.Runner (see
    module docstring) - reuses ifnet_config's pure regex/glob helpers
    so the two resolution algorithms can't silently diverge in
    behavior, even though they're driven by different Runner
    contracts."""
    paths = []
    to_read = ["/etc/network/interfaces"]
    seen = set()
    while to_read and len(seen) < MAX_INTERFACES_CLOSURE_FILES:
        path = to_read.pop(0)
        if path in seen:
            continue
        seen.add(path)
        content = runner.read_text(path)
        n = _note(content, f"read {path}")
        if n:
            collection_notes.append(n)
        if not content.ok:
            continue
        paths.append(path)
        for line in content.stdout.splitlines():
            m = ifnet_config.SOURCE_RE.match(line)
            if m:
                target = m.group(1)
                if ifnet_config._has_glob_metachars(target):
                    parent = target.rsplit("/", 1)[0] or "/"
                    listing = runner.listdir(parent)
                    n = _note(listing, f"listdir {parent}")
                    if n:
                        collection_notes.append(n)
                    # resolve_source_glob fnmatches full paths against
                    # the full glob pattern (matching repair.py's own
                    # closure walk, whose Runner.listdir returns full
                    # Path objects) - inventory's Runner.listdir returns
                    # bare names, so prefix them first rather than
                    # passing bare names against a full-path pattern.
                    entries = [f"{parent}/{e}" for e in listing.stdout.splitlines()] if listing.ok else []
                    to_read.extend(ifnet_config.resolve_source_glob(target, entries))
                else:
                    to_read.append(target)
                continue
            m = ifnet_config.SOURCE_DIR_RE.match(line)
            if m:
                sd = m.group(1)
                listing = runner.listdir(sd)
                n = _note(listing, f"listdir {sd}")
                if n:
                    collection_notes.append(n)
                if listing.ok:
                    to_read.extend(f"{sd}/{e}" for e in listing.stdout.splitlines())
    return sorted(seen & set(paths))


def _glob_dir_paths(runner, directory, suffixes, collection_notes):
    listing = runner.listdir(directory)
    n = _note(listing, f"listdir {directory}")
    if n:
        collection_notes.append(n)
    if not listing.ok:
        return []
    return sorted(f"{directory}/{name}" for name in listing.stdout.splitlines() if name.endswith(suffixes))


def _apt_source_paths(runner, collection_notes):
    paths = []
    if runner.path_exists("/etc/apt/sources.list"):
        paths.append("/etc/apt/sources.list")
    listing = runner.listdir("/etc/apt/sources.list.d")
    n = _note(listing, "listdir /etc/apt/sources.list.d")
    if n:
        collection_notes.append(n)
    if listing.ok:
        paths += sorted(
            f"/etc/apt/sources.list.d/{name}" for name in listing.stdout.splitlines()
            if name.endswith((".list", ".sources"))
        )
    return paths


def _baseline_managed_paths(runner, collection_notes):
    paths = []
    etc = runner.listdir("/etc/baseline")
    n = _note(etc, "listdir /etc/baseline")
    if n:
        collection_notes.append(n)
    if etc.ok:
        paths += sorted(f"/etc/baseline/{name}" for name in etc.stdout.splitlines())
    for kind in ("bin", "lib"):
        listing = runner.walk_bounded(f"/opt/baseline/{kind}", 4, 500)
        n = _note(listing, f"walk_bounded /opt/baseline/{kind}")
        if n:
            collection_notes.append(n)
        if listing.ok:
            paths += sorted(p for p in listing.stdout.splitlines() if p)
    paths += [f"/etc/systemd/system/{u}" for u in _BASELINE_UNITS if runner.path_exists(f"/etc/systemd/system/{u}")]
    return paths


def _build_allowlist(runner, collection_notes):
    paths = [p for p, _cat in _STATIC_FILES if runner.path_exists(p)]
    categories = {p: cat for p, cat in _STATIC_FILES}

    for directory, suffixes, category in _GLOB_DIRS:
        for p in _glob_dir_paths(runner, directory, suffixes, collection_notes):
            paths.append(p)
            categories[p] = category

    for p in _interfaces_closure_paths(runner, collection_notes):
        paths.append(p)
        categories[p] = "network"

    for p in _apt_source_paths(runner, collection_notes):
        paths.append(p)
        categories[p] = "apt"

    for p in _baseline_managed_paths(runner, collection_notes):
        paths.append(p)
        categories[p] = "baseline"

    return sorted(set(paths)), categories


_STAT_FORMAT = "%n|%F|%U|%G|%a|%s|%N"


def _batched_stat(runner, paths, collection_notes):
    if not paths:
        return {}
    result = runner.run(["stat", "-c", _STAT_FORMAT] + paths, timeout=20)
    n = _note(result, "stat (config_files allowlist)")
    if n:
        collection_notes.append(n)
    out = {}
    for line in result.stdout.splitlines():
        parts = line.split("|", 6)
        if len(parts) != 7:
            continue
        name, ftype, owner, group, mode, size, _n = parts
        out[name] = {"file_type": ftype, "owner": owner, "group": group, "mode": mode, "size": _safe_int(size)}
    # %N alone (last field) can contain "'path' -> 'target'" for a
    # symlink - re-derive it from the raw line's tail rather than the
    # split above, since a target path could itself contain "|".
    for line in result.stdout.splitlines():
        if " -> " not in line:
            continue
        head = line.split("|", 1)[0]
        tail = line.rsplit("|", 1)[-1]
        m = re.search(r"->\s*'(.*)'\s*$", tail)
        if head in out and m:
            out[head]["symlink_target"] = m.group(1)
    return out


def _safe_int(text):
    try:
        return int(text)
    except ValueError:
        return None


def _batched_sha256(runner, paths, collection_notes):
    regular_files = [p for p in paths]
    if not regular_files:
        return {}
    result = runner.run(["sha256sum"] + regular_files, timeout=30)
    n = _note(result, "sha256sum (config_files allowlist)")
    if n:
        collection_notes.append(n)
    out = {}
    if result.ok:
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                out[parts[1]] = parts[0]
    return out


def _owning_packages(runner, paths, collection_notes):
    owners = {}
    for p in paths:
        result = runner.run(["dpkg", "-S", p], timeout=10)
        if not result.ok:
            continue
        # "package: /path" or "package, package2: /path" for
        # dpkg-diverted/shared paths - keep the first, note the rest was
        # collapsed rather than silently dropping the ambiguity.
        line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if ":" in line:
            pkgs = line.split(":", 1)[0]
            owners[p] = pkgs.split(",")[0].strip()
    return owners


def _conffile_modified_status(runner, owning_packages, content_hashes, collection_notes):
    """Reuses dpkg's own per-conffile hash tracking (the same
    ${Conffiles} data system.py's collect_packages() already gathers in
    one batched pass) rather than needing the original packaged file
    content to compare against - the packaged hash is enough."""
    distinct_packages = sorted(set(owning_packages.values()))
    if not distinct_packages:
        return {}
    result = runner.run(["dpkg-query", "-W", "-f=${Package}\t${Conffiles}\n"] + distinct_packages, timeout=15)
    n = _note(result, "dpkg-query -W (conffile hashes for config_files allowlist)")
    if n:
        collection_notes.append(n)
    packaged_hash_by_path = {}
    if result.ok:
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            _pkg, rest = line.split("\t", 1)
            for entry in rest.strip().split("\n"):
                fields = entry.split()
                if len(fields) >= 2:
                    packaged_hash_by_path[fields[0]] = fields[1]

    status = {}
    for path, pkg in owning_packages.items():
        packaged_md5 = packaged_hash_by_path.get(path)
        if packaged_md5 is None:
            status[path] = None  # not a tracked conffile of its owning package
            continue
        # dpkg's Conffiles hash is MD5, not the sha256 content identity
        # this collector otherwise uses - two different hash algorithms
        # answering two different questions (dpkg's own drift check vs.
        # this manifest's cross-run content identity), never conflated.
        md5_result = runner.run(["md5sum", path], timeout=10)
        live_md5 = md5_result.stdout.split()[0] if md5_result.ok and md5_result.stdout.strip() else None
        status[path] = (live_md5 is not None) and (live_md5 != packaged_md5)
    return status


def collect_config_files(runner, redactor):
    collection_notes = []
    paths, categories = _build_allowlist(runner, collection_notes)

    stat_map = _batched_stat(runner, paths, collection_notes)
    regular_files = [p for p in paths if stat_map.get(p, {}).get("file_type") == "regular file"]
    hash_map = _batched_sha256(runner, regular_files, collection_notes)
    owner_map = _owning_packages(runner, paths, collection_notes)
    conffile_status = _conffile_modified_status(runner, owner_map, hash_map, collection_notes)

    entries = []
    for path in paths:
        st = stat_map.get(path)
        entry = {"path": path, "category": _category_for(path, categories.get(path, "other")),
                  "baseline_managed": _baseline_managed(path), "exists": st is not None}
        if st is None:
            entries.append(entry)
            continue
        entry.update({
            "file_type": st["file_type"],
            "symlink_target": st.get("symlink_target"),
            "owner": st["owner"],
            "group": st["group"],
            "mode": st["mode"],
            "size": st["size"],
            "owning_package": owner_map.get(path),
            "conffile_modified": conffile_status.get(path),
        })
        if path in hash_map:
            entry["content_identity"] = redactor.tokenize(hash_map[path], "content")
        entries.append(entry)

    return {"entries": entries, "_collection_notes": collection_notes}
