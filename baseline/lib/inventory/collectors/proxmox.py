"""Proxmox-managed configuration.

/etc/pve is a live pmxcfs filesystem, never walked recursively. Every
read here is an explicit, named path or command with its own field
allowlist. This module NEVER constructs a path under any node's priv/
directory - not a listdir, not a read, not even an existence check.
That's an allowlist boundary, not something to gracefully degrade
around: a PermissionError coming back from priv/ would mean this module
already violated the boundary by asking (design doc correction #10).

pvesubscription get is deliberately never invoked (correction #3):
filtering its output after the fact still means the process received the
raw subscription key in memory first. Repository channel and enabled-
source state are read from static config instead; subscription status is
recorded as "unavailable" with a reason until a real host confirms a
safe, field-specific query exists.
"""
import re

import repair  # canonical-repo reconciliation: reuse repair.COROSYNC_CONFIG_PATHS
                # below so this read-only fact check can never silently
                # drift from repair.check_standalone_host()'s own
                # cluster-membership file check - they answer different
                # questions (refuse a repair action vs. record a fact)
                # but must always agree on which paths mean "clustered".

from .status_notes import note as _note, notes as _notes

STORAGE_ALLOWED_KEYS = {"type", "content", "nodes", "shared", "maxfiles", "username"}
_SECRET_KEY_RE = re.compile(r"(password|secret|token|keyring|encryption)", re.IGNORECASE)

# Starter allowlist only - not validated against a real datacenter.cfg
# from this session; confirm the full real key set against a real host
# before treating this as final (see design doc, "still leaves open").
DATACENTER_ALLOWED_KEYS = {
    "keyboard", "console", "language", "migration", "ha", "max_workers", "bwlimit",
}

VM_CONFIG_ALLOWED_KEYS = {"cores", "memory", "bootdisk", "ostype", "scsihw"}
_NET_KEY_RE = re.compile(r"^net\d+$")

_FIREWALL_ADDRESS_FLAGS = {"-source", "-dest"}
_FIREWALL_KEPT_FLAGS = {"-p": "proto", "-dport": "dport", "-sport": "sport", "-i": "iface"}


def _parse_kv_block(text):
    """Flat 'key: value' or 'key value' per-line parsing - not a full
    Proxmox config-file parser, since only allowlisted keys are ever
    kept regardless of what else a line contains."""
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif " " in line:
            key, value = line.split(" ", 1)
        else:
            continue
        fields[key.strip()] = value.strip()
    return fields


def collect_storage_cfg(runner):
    result = runner.read_text("/etc/pve/storage.cfg")
    if not result.ok:
        return {"available": False, "reason": result.reason}
    entries = []
    current = None
    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ":" in line:
            if current:
                entries.append(current)
            kind, _, name = line.partition(":")
            current = {"type": kind.strip(), "fields": {}}
        elif current is not None and line.strip():
            key, _, value = line.strip().partition(" ")
            if _SECRET_KEY_RE.search(key):
                continue
            if key in STORAGE_ALLOWED_KEYS:
                current["fields"][key] = value.strip()
    if current:
        entries.append(current)
    return {"available": True, "entries": entries}


def collect_datacenter_cfg(runner):
    result = runner.read_text("/etc/pve/datacenter.cfg")
    if not result.ok:
        return {"available": False, "reason": result.reason}
    raw_fields = _parse_kv_block(result.stdout)
    kept = {k: v for k, v in raw_fields.items() if k in DATACENTER_ALLOWED_KEYS}
    unknown_names = sorted(k for k in raw_fields if k not in DATACENTER_ALLOWED_KEYS)
    return {
        "available": True,
        "fields": kept,
        "unknown_fields": {"names": unknown_names, "count": len(unknown_names)},
    }


def _redact_net_line(value, redactor):
    bridge = None
    for part in value.split(","):
        if part.startswith("bridge="):
            bridge = part.split("=", 1)[1]
    return {"bridge": bridge}


def _collect_node_vm_ct_configs(runner, node, vmid_kind, redactor, collection_notes):
    """vmid_kind is 'qemu-server' or 'lxc'. Only ever lists/reads under
    exactly this one subdirectory of the node - never priv/, never the
    node directory itself recursively."""
    dir_path = f"/etc/pve/nodes/{node}/{vmid_kind}"
    listing = runner.listdir(dir_path)
    if not listing.ok:
        n = _note(listing, f"listdir {dir_path}")
        if n:
            collection_notes.append(n)
        return []
    configs = []
    for name in listing.stdout.splitlines():
        if not name.endswith(".conf"):
            continue
        vmid = name[:-len(".conf")]
        content = runner.read_text(f"{dir_path}/{name}")
        if not content.ok:
            n = _note(content, f"read {dir_path}/{name}")
            if n:
                collection_notes.append(n)
            continue
        raw_fields = _parse_kv_block(content.stdout)
        kept = {k: v for k, v in raw_fields.items() if k in VM_CONFIG_ALLOWED_KEYS}
        for k, v in raw_fields.items():
            if _NET_KEY_RE.match(k):
                kept[k] = _redact_net_line(v, redactor)
        configs.append({"vmid_token": redactor.tokenize(vmid, "vmid"), "fields": kept})
    return configs


def collect_nodes(runner, node_names, redactor):
    out = {}
    collection_notes = []
    for node in node_names:
        node_token = redactor.tokenize(node, "host")
        out[node_token] = {
            "qemu": _collect_node_vm_ct_configs(runner, node, "qemu-server", redactor, collection_notes),
            "lxc": _collect_node_vm_ct_configs(runner, node, "lxc", redactor, collection_notes),
        }
    out["_collection_notes"] = collection_notes
    return out


def _redact_fw_rule(line, redactor):
    tokens = line.split()
    if len(tokens) < 2:
        return {}
    fields = {"rule": " ".join(tokens[:2])}
    i = 2
    while i < len(tokens):
        flag = tokens[i]
        value = tokens[i + 1] if i + 1 < len(tokens) else None
        if value is not None:
            if flag in _FIREWALL_ADDRESS_FLAGS:
                fields[flag.lstrip("-")] = redactor.tokenize(value, "cidr")
            elif flag in _FIREWALL_KEPT_FLAGS:
                fields[_FIREWALL_KEPT_FLAGS[flag]] = value
        i += 2
    return fields


def collect_firewall(runner, fw_paths, redactor):
    rules = {}
    collection_notes = []
    for path in fw_paths:
        result = runner.read_text(path)
        if not result.ok:
            n = _note(result, f"read {path}")
            if n:
                collection_notes.append(n)
            continue
        parsed = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            parsed.append(_redact_fw_rule(line, redactor))
        rules[path] = parsed
    rules["_collection_notes"] = collection_notes
    return rules


def collect_pvesm_status(runner, redactor):
    """Structure only. shared/content-type facts come from storage.cfg
    already (cross-referenced by name token, not duplicated here); this
    command only adds live status/type/capacity. Used/available/percent
    columns are excluded as volatile, same rule as everywhere else in
    this design (correction #8)."""
    result = runner.run(["pvesm", "status"])
    if not result.ok:
        return {"available": False, "reason": result.reason}
    lines = result.stdout.splitlines()
    storages = []
    for line in lines[1:]:
        cols = line.split()
        if len(cols) < 3:
            continue
        name, kind, status = cols[0], cols[1], cols[2]
        total = cols[3] if len(cols) > 3 else None
        storages.append({
            "name_token": redactor.tokenize(name, "storage"),
            "type": kind,
            "enabled": status == "active",
            "total_capacity": total,
        })
    return {"available": True, "storages": storages}


def collect_repo_and_subscription(runner):
    enterprise = runner.read_text("/etc/apt/sources.list.d/pve-enterprise.list")
    no_sub = runner.read_text("/etc/apt/sources.list.d/pve-no-subscription.list")

    def _has_enabled_line(result):
        if not result.ok:
            return False
        return any(line.strip() and not line.strip().startswith("#") for line in result.stdout.splitlines())

    # A missing repo list file (unavailable, reason "not found") means the
    # channel simply isn't configured - not an error - so it's noted but
    # doesn't change enabled=False's meaning.
    collection_notes = _notes(
        (enterprise, "read /etc/apt/sources.list.d/pve-enterprise.list"),
        (no_sub, "read /etc/apt/sources.list.d/pve-no-subscription.list"),
    )

    return {
        "enterprise_repo_enabled": _has_enabled_line(enterprise),
        "no_subscription_repo_enabled": _has_enabled_line(no_sub),
        "subscription_status": "unavailable",
        "subscription_status_reason": (
            "pvesubscription get is not run - no confirmed safe, field-specific "
            "query exists that cannot return the subscription key; needs "
            "validating against a real host before this can change"
        ),
        "_collection_notes": collection_notes,
    }


def collect_cluster(runner):
    clustered = any(runner.path_exists(p) for p in repair.COROSYNC_CONFIG_PATHS)
    if not clustered:
        return {"clustered": False, "membership": None}
    result = runner.run(["pvecm", "status"])
    return {
        "clustered": True,
        "status_command_available": result.ok,
        # Detailed per-node membership parsing needs validating against
        # real `pvecm status` output, which this session cannot produce -
        # not invented here (see design doc, "still leaves open").
    }
