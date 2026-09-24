"""Firewall/sysctl/DNS/time/journald facts.

Sysctl handling per Cliff's fail-closed correction: every key found in
/etc/sysctl.conf and /etc/sysctl.d/*.conf is recorded as *discovered* -
by name only, never queried just for appearing in a config file. Only
the small, separately reviewed SYSCTL_ALLOWLIST ever gets its live value
queried, each as ["sysctl", "<key>"] - one argument-array element per
key, never sysctl -a and never a shell string. A discovered key that
also happens to be on the reviewed allowlist gets both: it's in
discovered_keys and its value is in values. A line that doesn't parse as
"key = value" is recorded as skipped, never passed to sysctl.
"""
import re

from .status_notes import note as _note, notes as _notes

SYSCTL_ALLOWLIST = ["net.ipv4.ip_forward", "net.ipv6.conf.all.disable_ipv6"]
_SYSCTL_KEY_RE = re.compile(r"^([A-Za-z0-9_.]+)\s*=")


def _parse_sysctl_conf(text):
    keys, malformed = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SYSCTL_KEY_RE.match(line)
        if m:
            keys.append(m.group(1))
        else:
            malformed.append(line)
    return keys, malformed


def collect_sysctl(runner):
    intentional_keys, malformed = [], []
    collection_notes = []
    conf = runner.read_text("/etc/sysctl.conf")
    if conf.ok:
        keys, bad = _parse_sysctl_conf(conf.stdout)
        intentional_keys += keys
        malformed += bad
    else:
        n = _note(conf, "read /etc/sysctl.conf")
        if n:
            collection_notes.append(n)

    listing = runner.listdir("/etc/sysctl.d")
    if listing.ok:
        for name in listing.stdout.splitlines():
            if not name.endswith(".conf"):
                continue
            frag = runner.read_text(f"/etc/sysctl.d/{name}")
            if not frag.ok:
                n = _note(frag, f"read /etc/sysctl.d/{name}")
                if n:
                    collection_notes.append(n)
                continue
            keys, bad = _parse_sysctl_conf(frag.stdout)
            intentional_keys += keys
            malformed += bad
    else:
        n = _note(listing, "listdir /etc/sysctl.d")
        if n:
            collection_notes.append(n)

    discovered_keys = sorted(set(intentional_keys))
    # Fail closed: a key only being present in a config file never earns
    # it a live query - only SYSCTL_ALLOWLIST (separately reviewed) does.
    values = {}
    for key in SYSCTL_ALLOWLIST:
        result = runner.run(["sysctl", key])
        collection_notes += _notes((result, f"sysctl {key}"))
        if result.ok:
            values[key] = result.stdout.strip()
    return {
        "discovered_keys": discovered_keys,
        "reviewed_keys_queried": sorted(SYSCTL_ALLOWLIST),
        "values": values,
        "skipped_malformed_lines": malformed,
        "_collection_notes": collection_notes,
    }


def collect_firewall_ruleset(runner):
    if runner.which("nft"):
        nft = runner.run(["nft", "list", "ruleset"])
        if nft.ok:
            return {"backend": "nft", "summary_available": True, "_collection_notes": []}
        return {"backend": None, "summary_available": False, "_collection_notes": _notes((nft, "nft list ruleset"))}
    if runner.which("iptables"):
        iptables = runner.run(["iptables-save"])
        if iptables.ok:
            return {"backend": "iptables", "summary_available": True, "_collection_notes": []}
        return {"backend": None, "summary_available": False, "_collection_notes": _notes((iptables, "iptables-save"))}
    return {
        "backend": None,
        "summary_available": False,
        "_collection_notes": [{"command": "nft/iptables", "status": "unavailable", "reason": "neither nft nor iptables on PATH"}],
    }


def collect_dns_time(runner):
    resolvectl_path = runner.which("resolvectl")
    dns = runner.run(["resolvectl", "status"]) if resolvectl_path else None
    time_status = runner.run(["timedatectl", "status"])
    collection_notes = _notes((time_status, "timedatectl status"))
    if dns is not None:
        collection_notes += _notes((dns, "resolvectl status"))
    elif not resolvectl_path:
        collection_notes.append({"command": "resolvectl status", "status": "unavailable", "reason": "resolvectl not on PATH"})
    return {
        "dns_available": bool(dns and dns.ok),
        "time_status": time_status.stdout if time_status.ok else None,
        "_collection_notes": collection_notes,
    }


def collect_journald(runner):
    conf = runner.read_text("/etc/systemd/journald.conf")
    disk_usage = runner.run(["journalctl", "--disk-usage"])
    return {
        "config": conf.stdout if conf.ok else None,
        "disk_usage_summary": disk_usage.stdout.strip() if disk_usage.ok else None,
        "_collection_notes": _notes(
            (conf, "read /etc/systemd/journald.conf"),
            (disk_usage, "journalctl --disk-usage"),
        ),
    }
