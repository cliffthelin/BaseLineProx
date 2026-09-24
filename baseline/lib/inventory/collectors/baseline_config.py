"""Baseline's own configuration and state directories.

/var/lib/baseline is walked with an explicit max depth and entry count -
never an unbounded `ls -laR` - recording truncation if either bound is
exceeded (design doc correction #7).

Canonical-repo reconciliation: the original inventory branch predates
provision.sh's current deploy list and only ever checked
baseline.service. It now also inventories the deployed code itself
(/opt/baseline/bin, /opt/baseline/lib/*.py - filenames + sha256, never
content, since these are Baseline's own source, not secrets) and all
three systemd units provision.sh installs, not just one - a real gap a
port-time review caught, not something the original branch chose to
defer."""
import json

from .status_notes import note as _note, notes as _notes

MAX_WALK_DEPTH = 4
MAX_WALK_ENTRIES = 500

DEPLOYED_UNITS = ("baseline.service", "baseline-additive-dhcp-reapply.service",
                  "baseline-firstboot.service")


def _extract_json_keys(text):
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    return sorted(data.keys()) if isinstance(data, dict) else []


def collect_baseline_config(runner):
    etc_listing = runner.listdir("/etc/baseline")
    config_key_summaries = {}
    etc_files = etc_listing.stdout.splitlines() if etc_listing.ok else []
    collection_notes = _notes((etc_listing, "listdir /etc/baseline"))
    for name in etc_files:
        if not name.endswith(".json"):
            continue
        content = runner.read_text(f"/etc/baseline/{name}")
        config_key_summaries[name] = {"keys": _extract_json_keys(content.stdout) if content.ok else []}
        n = _note(content, f"read /etc/baseline/{name}")
        if n:
            collection_notes.append(n)

    var_lib = runner.walk_bounded("/var/lib/baseline", MAX_WALK_DEPTH, MAX_WALK_ENTRIES)
    collection_notes += _notes((var_lib, "walk_bounded /var/lib/baseline"))

    unit_status_available = {}
    for unit in DEPLOYED_UNITS:
        status = runner.run(["systemctl", "status", unit, "--no-pager"])
        unit_status_available[unit] = status.ok
        n = _note(status, f"systemctl status {unit}")
        if n:
            collection_notes.append(n)

    deployed_bin = runner.walk_bounded("/opt/baseline/bin", MAX_WALK_DEPTH, MAX_WALK_ENTRIES)
    deployed_lib = runner.walk_bounded("/opt/baseline/lib", MAX_WALK_DEPTH, MAX_WALK_ENTRIES)
    collection_notes += _notes(
        (deployed_bin, "walk_bounded /opt/baseline/bin"),
        (deployed_lib, "walk_bounded /opt/baseline/lib"),
    )
    deployed_files = sorted(
        (deployed_bin.stdout.splitlines() if deployed_bin.ok else [])
        + (deployed_lib.stdout.splitlines() if deployed_lib.ok else [])
    )
    deployed_hashes = {}
    if deployed_files:
        # One batched sha256sum call, matching this codebase's established
        # preference (see collectors/system.py's batched dpkg-query) for
        # one subprocess over one-per-file - these are Baseline's own
        # deployed source files, never secrets, so recording their hashes
        # (not content) is the drift-evidence this collector exists for.
        hashes = runner.run(["sha256sum"] + deployed_files, timeout=30)
        n = _note(hashes, "sha256sum /opt/baseline/{bin,lib}/*")
        if n:
            collection_notes.append(n)
        if hashes.ok:
            for line in hashes.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2:
                    deployed_hashes[parts[1]] = parts[0]

    return {
        "etc_baseline_files": etc_files,
        "config_key_summaries": config_key_summaries,
        "var_lib_baseline_layout": var_lib.stdout.splitlines() if var_lib.ok else [],
        "var_lib_baseline_truncated": var_lib.output_truncated if var_lib.ok else False,
        "unit_status_available": unit_status_available,
        "deployed_files": deployed_files,
        "deployed_file_sha256": deployed_hashes,
        "_collection_notes": collection_notes,
    }
