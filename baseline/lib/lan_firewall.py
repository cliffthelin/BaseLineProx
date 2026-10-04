"""LAN-only inbound firewall.

Policy: the machine reaches the internet outbound, but accepts inbound connections (SSH, web UI,
SMB, anything) only from the internal network. Implemented as one nftables table, `inet baseline_lan`,
with a single input chain whose policy is drop. Outbound (no output hook) and forwarding for VMs/LXCs
(no forward hook) are deliberately left alone.

Safety:
  * "LAN" means private address space only (RFC 1918, link-local, ULA, loopback-adjacent). A subnet that
    is global or covers everything (0.0.0.0/0) is rejected, so the policy can never be configured open.
  * The ruleset is syntax-checked (`nft -c`) before it is loaded, verified from the live ruleset after it
    is loaded, and removed again if verification fails - a ruleset that cannot be proven active is not left half-trusted.
  * Open mode (allow_lan_only false) is refused outright; nothing here ever disables the policy.
  * Persistence is a oneshot unit ordered before the network comes up, written only after verification.

This module only builds and applies rules through the Runner it is given. Whether the rules are active on
real hardware has to be proven on that hardware (docs/design/v0.2-work-queue.md, LAN-only section).
"""
from __future__ import annotations

import ipaddress

TABLE = "baseline_lan"
RULESET_PATH = "/etc/baseline/lan-only.nft"
UNIT_NAME = "baseline-lan-only.service"
UNIT_PATH = f"/etc/systemd/system/{UNIT_NAME}"
DEFAULT_LAN_SUBNETS = (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",     # RFC 1918
    "169.254.0.0/16",                                      # IPv4 link-local
    "fe80::/10", "fc00::/7",                               # IPv6 link-local, unique-local
)

_UNIT = f"""[Unit]
Description=Baseline LAN-only inbound firewall
Before=network-pre.target
Wants=network-pre.target
After=nftables.service
RequiresMountsFor=/etc/baseline
DefaultDependencies=no

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f {RULESET_PATH}
ExecStop=/usr/sbin/nft delete table inet {TABLE}

[Install]
WantedBy=sysinit.target
"""


def validate_subnets(subnets) -> list:
    """Private/LAN subnets only. None or empty means the default private ranges."""
    if not subnets:
        return list(DEFAULT_LAN_SUBNETS)
    if not isinstance(subnets, (list, tuple)):
        raise ValueError("lan_subnets must be a list of subnets")
    clean = []
    for item in subnets:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"not a subnet: {item!r}")
        try:
            net = ipaddress.ip_network(item.strip(), strict=True)
        except ValueError:
            raise ValueError(f"not a subnet: {item!r}") from None
        if net.prefixlen == 0 or not (net.is_private or net.is_link_local):
            raise ValueError(f"{item} is not a LAN subnet; LAN-only never allows public or all addresses")
        clean.append(str(net))
    return clean


def build_ruleset(subnets) -> str:
    v4 = [s for s in subnets if ":" not in s]
    v6 = [s for s in subnets if ":" in s]
    allow = []
    if v4:
        allow.append(f"    ip saddr {{ {', '.join(v4)} }} accept")
    if v6:
        allow.append(f"    ip6 saddr {{ {', '.join(v6)} }} accept")
    return (
        f"table inet {TABLE}\n"
        f"delete table inet {TABLE}\n"
        f"table inet {TABLE} {{\n"
        "  chain input {\n"
        "    type filter hook input priority 0; policy drop;\n"
        "    iif lo accept\n"
        "    ct state established,related accept\n"
        "    ct state invalid drop\n"
        "    udp sport 67 udp dport 68 accept\n"        # DHCP replies can precede conntrack state
        "    udp sport 547 udp dport 546 accept\n"
        "    icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-advert, nd-router-solicit } accept\n"
        + "\n".join(allow) + "\n"
        "  }\n"
        "}\n"
    )


def _verified(listing: str, subnets) -> bool:
    return "policy drop" in listing and "hook input" in listing and all(s in listing for s in subnets)


def apply(runner, config: dict) -> tuple:
    """Returns (ok, detail). Refuses before any command if the config is open-mode or malformed."""
    if config.get("allow_lan_only", True) is not True:
        return False, "firewall not applied: open mode is not supported; inbound access is LAN-only"
    try:
        subnets = validate_subnets(config.get("lan_subnets"))
    except ValueError as exc:
        return False, f"firewall not applied: {exc}"

    candidate = RULESET_PATH + ".new"
    runner.makedirs("/etc/baseline")
    runner.write_text_atomic(candidate, build_ruleset(subnets))
    try:
        return _load_and_persist(runner, candidate, subnets)
    finally:
        runner.remove(candidate)


def _restore_previous(runner, had_previous: bool) -> str:
    """After a failed load/verify: put the last good rules back rather than leave the machine open."""
    if had_previous:
        proc = runner.run(["nft", "-f", RULESET_PATH], timeout=20)
        return "the previous ruleset was reloaded" if proc.returncode == 0 else "reloading the previous ruleset also failed"
    runner.run(["nft", "delete", "table", "inet", TABLE], timeout=20)
    return "the unverified ruleset was removed"


def _load_and_persist(runner, candidate: str, subnets) -> tuple:
    had_previous = runner.path_exists(RULESET_PATH)
    check = runner.run(["nft", "-c", "-f", candidate], timeout=20)
    if check.returncode != 0:
        return False, f"firewall not applied: ruleset check failed: {check.stderr.strip()}"
    load = runner.run(["nft", "-f", candidate], timeout=20)
    if load.returncode != 0:
        return False, f"firewall not applied: loading the ruleset failed: {load.stderr.strip()}"

    listing = runner.run(["nft", "list", "table", "inet", TABLE], timeout=20)
    if listing.returncode != 0 or not _verified(listing.stdout, subnets):
        outcome = _restore_previous(runner, had_previous)
        return False, f"firewall not applied: the loaded ruleset could not be verified; {outcome}"

    # Only now does the verified ruleset replace the one the next boot will load.
    runner.write_text_atomic(RULESET_PATH, runner.read_text(candidate))
    runner.write_text_atomic(UNIT_PATH, _UNIT)
    for argv in (["systemctl", "daemon-reload"], ["systemctl", "enable", UNIT_NAME]):
        proc = runner.run(argv, timeout=30)
        if proc.returncode != 0:
            return False, (f"LAN-only rules are active now but will not persist across reboot: "
                           f"{' '.join(argv)} failed: {proc.stderr.strip()}")
    return True, f"LAN-only inbound firewall active and persisted; allowed inbound sources: {', '.join(subnets)}"
