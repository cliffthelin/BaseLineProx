#!/bin/bash
# Read-only environment probe for the permanent boot-time repair-recovery
# service (docs/design/reset-interface-to-dhcp-plan.md, "Required merge
# blockers" #1).
#
# This script makes NO configuration changes of any kind - it only reads
# and prints. Run it on the actual target (a disposable Proxmox VM to
# start with, per the plan's integration-test requirement) to collect the
# facts needed to decide where in the real boot sequence a permanent,
# dormant recovery service can safely sit: after the filesystem holding
# the backup/pending-manifest is available, but before
# networking.service/ifupdown2's startup path consumes an unverified
# candidate config. Guessing that ordering from a different distro (this
# was written from an Ubuntu 24.04 session with no reachable Proxmox/
# Debian host) is exactly what the plan says not to do - this script is
# how that gets answered from a real host instead.
#
# Output is redacted: real addresses, MACs, and hostnames are stripped
# from anything that isn't itself the thing being asked about (unit
# ordering, versions, mount facts). What's kept is structure - interface
# *names* and stanza *types* (static/dhcp/manual), not the values that
# make a specific host identifiable.
#
# Usage: baseline-repair-env-probe.sh [output-file]
#   With no argument, prints to stdout only. With an argument, ALSO writes
#   the same report to that file (still never touches system config) -
#   this is the one file this script ever writes, and only if asked.
set -uo pipefail

OUT_FILE="${1:-}"

redact_interfaces() {
    # Keep stanza structure (iface NAME inet METHOD, bridge-ports/bond-
    # slaves/vlan-raw-device membership, auto/allow-hotplug lines) - drop
    # the actual address/netmask/gateway/dns values and anything else
    # that isn't structural.
    sed -E \
        -e 's/^([[:space:]]*)(address|netmask|gateway|dns-nameservers|dns-search)[[:space:]].*/\1\2 <redacted>/' \
        "$1" 2>/dev/null
}

redact_generic() {
    # Best-effort strip of IPv4/IPv6/MAC-looking tokens from command
    # output that's otherwise structural (systemctl show, dpkg-query,
    # version strings).
    sed -E \
        -e 's/[0-9]{1,3}(\.[0-9]{1,3}){3}(\/[0-9]{1,2})?/<redacted-ipv4>/g' \
        -e 's/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/<redacted-mac>/g'
}

section() {
    echo
    echo "=== $1 ==="
}

run() {
    # Never let one missing/failing command abort the whole probe -
    # $? is recorded in the output instead, since "this command doesn't
    # exist here" is itself a useful fact (e.g. ifupdown2 not installed).
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "(command not found: $1)"
        return 0
    fi
    "$@" 2>&1 || echo "(exited $?)"
}

{
    echo "Baseline repair-environment probe - read-only, no config changed."
    echo "Generated: $(date -u +%FT%TZ 2>/dev/null || echo unknown)"

    section "Proxmox version"
    run pveversion -v | redact_generic

    section "Debian version"
    cat /etc/debian_version 2>/dev/null || echo "(no /etc/debian_version)"
    echo "--- /etc/os-release ---"
    cat /etc/os-release 2>/dev/null

    section "ifupdown2"
    run dpkg-query -W -f='${Package} ${Version} ${Status}\n' ifupdown2
    echo "--- ifreload path ---"
    command -v ifreload 2>/dev/null || echo "(ifreload not on PATH)"

    section "networking.service unit (as systemd actually resolved it)"
    run systemctl cat networking.service

    section "networking.service ordering (Before / After / Wants / Requires)"
    run systemctl show networking.service -p Before -p After -p Wants -p Requires -p WantedBy -p RequiredBy

    section "network-pre.target ordering"
    run systemctl show network-pre.target -p Before -p After

    section "network.target ordering"
    run systemctl show network.target -p Before -p After

    section "local-fs.target ordering (what 'the filesystem holding the backup is available' actually depends on)"
    run systemctl show local-fs.target -p Before -p After

    section "Full boot-relevant unit dependency tree for networking.service"
    run systemctl list-dependencies networking.service --before
    echo "--- After ---"
    run systemctl list-dependencies networking.service --after

    section "Mount facts: is /var separate from / ?"
    run findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /var
    echo "--- / itself ---"
    run findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /
    echo "--- would /var/lib/baseline/repair be usable this early? (existence + writability, not created) ---"
    if [ -d /var/lib ]; then
        echo "/var/lib exists"
        [ -w /var/lib ] && echo "/var/lib is writable by this user" || echo "/var/lib is NOT writable by this user"
    else
        echo "/var/lib does not exist (unexpected)"
    fi

    section "Current /etc/network/interfaces closure (structure only, values redacted)"
    if [ -f /etc/network/interfaces ]; then
        redact_interfaces /etc/network/interfaces
        echo "--- source/source-directory targets referenced ---"
        grep -E '^\s*source(-directory)?\s' /etc/network/interfaces 2>/dev/null
        for f in /etc/network/interfaces.d/*; do
            [ -f "$f" ] || continue
            echo "--- $f ---"
            redact_interfaces "$f"
        done
    else
        echo "(no /etc/network/interfaces on this host)"
    fi

    section "systemd version (unit-file syntax/behavior can vary across versions)"
    run systemctl --version | head -1

    echo
    echo "=== End of probe. No configuration was changed. ==="
} | tee ${OUT_FILE:+"$OUT_FILE"} /dev/null
