"""Boot-time reapply for the additive repair's DHCP stanza (decision
record 17's confirmed gap: ifupdown2's own dispatch only ever processes
the *first* `iface <name>` stanza for a given interface name, so a
second, additively-added `iface <name> inet dhcp` stanza never comes up
on its own at boot - only the one-time supplementary `dhclient` call in
repair_additive.add_dhcp_to_bridge does, and that call happens once, at
apply time, not on every subsequent boot.

Deliberately narrow, not a general-purpose "retry DHCP on anything"
tool: only interfaces where the additive repair's own signature is
present (a name recorded as duplicate by ifnet_config's parser, with a
second `inet dhcp` stanza specifically) are touched, and only when that
interface currently has no IPv4 address at all - never re-run against
an interface that already has one, and never touch an interface this
mechanism didn't itself create the duplicate stanza for.
"""
from __future__ import annotations

import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import repair  # noqa: E402
import ifnet_config  # noqa: E402
from repair import Runner  # noqa: E402

# Matches a standalone `iface <name> inet dhcp` line - the same shape
# ifnet_config.add_dhcp_stanza writes.
_DHCP_STANZA_RE = re.compile(r"^\s*iface\s+(\S+)\s+inet\s+dhcp\s*$", re.MULTILINE)


def _has_additive_dhcp_stanza(cfg: ifnet_config.ParsedConfig, name: str) -> bool:
    """True only if a second, separate `iface <name> inet dhcp` stanza
    exists somewhere in the parsed files - not just that `name` was
    recorded as a duplicate for some other reason (e.g. two static
    stanzas from a hand-edited file, which this must not touch)."""
    if name not in cfg.duplicate_names:
        return False
    for text in cfg.files.values():
        for match in _DHCP_STANZA_RE.finditer(text):
            if match.group(1) == name:
                return True
    return False


def _has_ipv4_address(runner: Runner, name: str) -> bool:
    result = runner.run(["ip", "-4", "-o", "addr", "show", "dev", name], timeout=5)
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def reapply_additive_dhcp(runner: Runner) -> list[dict]:
    """Idempotent: safe to run on every boot. Returns one event dict per
    interface actually touched (empty list is the normal case once an
    interface has a working lease - this is not expected to do anything
    on most boots)."""
    events = []
    cfg = repair.read_interfaces_config(runner)
    for name in sorted(cfg.duplicate_names):
        if not _has_additive_dhcp_stanza(cfg, name):
            continue
        if _has_ipv4_address(runner, name):
            continue
        result = runner.run(["dhclient", name], timeout=30)
        status = "pass" if result.returncode == 0 else "fail"
        detail = (f"boot-time reapply: dhclient {name}" if result.returncode == 0
                  else f"boot-time reapply failed: dhclient {name}: {result.stderr.strip()}")
        repair.log_event(runner, "boot-reapply", "additive_dhcp_reapply", status, detail)
        events.append({"interface": name, "status": status, "detail": detail})
    return events


def main() -> int:
    runner = repair.RealRunner()
    events = reapply_additive_dhcp(runner)
    for ev in events:
        print(f"[{ev['status']}] {ev['interface']}: {ev['detail']}")
    if not events:
        print("[baseline-additive-dhcp-reapply] nothing to do")
    return 0 if all(e["status"] == "pass" for e in events) else 1


if __name__ == "__main__":
    sys.exit(main())
