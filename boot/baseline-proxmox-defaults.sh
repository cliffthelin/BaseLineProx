#!/bin/bash
# Baseline: what a fresh Proxmox host should already show (operator's laptop review, 2026-10-12): the Baseline role volumes as storages, a
# group, the firewall on, a way from Proxmox's own GUI to Baseline, and no subscription nag. Every step is idempotent and best effort: one
# that cannot run (a service not up yet) never stops the others, and the script exits 0 so it can run from provisioning and from an apt hook.
#   baseline-proxmox-defaults            everything
#   baseline-proxmox-defaults nag        only the subscription notice (the apt hook uses this after a package upgrade)
set -u
say() { echo "[baseline-proxmox-defaults] $*"; }

nag() {
    local js=/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
    [ -f "$js" ] || return 0
    if grep -q "res.data.status.toLowerCase() !== 'active'" "$js"; then
        cp -n "$js" "$js.baseline-original" 2>/dev/null || true
        sed -i "s/res.data.status.toLowerCase() !== 'active'/false/" "$js"
        systemctl try-restart pveproxy.service >/dev/null 2>&1 || true
        say "subscription notice disabled in the web interface"
    fi
}

storage() {  # id path content
    local id="$1" path="$2" content="$3"
    mountpoint -q "$path" || { say "skip $id: $path is not mounted"; return 0; }
    pvesm status 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$id" && return 0
    pvesm add dir "$id" --path "$path" --content "$content" --is_mountpoint "$path" >/dev/null 2>&1 \
        && say "storage $id -> $path ($content)" || say "could not add storage $id"
}

if [ "${1:-}" = nag ]; then nag; exit 0; fi

# INSTALLER_CACHE was once registered as `baseline-isos`, a name that is not a volume's. Same folder, the volume's own name.
if pvesm status 2>/dev/null | awk 'NR>1{print $1}' | grep -qx baseline-isos && ! pvesm status 2>/dev/null | awk 'NR>1{print $1}' | grep -qx installer-cache; then
    pvesm remove baseline-isos >/dev/null 2>&1 && \
    pvesm add dir installer-cache --path /mnt/INSTALLER_CACHE --content iso --is_mountpoint /mnt/INSTALLER_CACHE >/dev/null 2>&1 && \
    say "storage baseline-isos renamed installer-cache"
fi

# The Baseline roles as Proxmox storages. USER_ADMIN holds the substrate's private data: backups only, never VM disks.
storage user-admin       /mnt/USER_ADMIN       backup
storage user-personal    /mnt/USER_PERSONAL    images,backup
storage appdata-admin    /mnt/APPDATA_ADMIN    images,backup
storage appdata-personal /mnt/APPDATA_PERSONAL images,backup

# A group to put people in (Datacenter > Permissions > Groups).
if command -v pveum >/dev/null 2>&1; then
    pveum group list 2>/dev/null | grep -q "baseline-admins" || {
        pveum group add baseline-admins --comment "Baseline administrators" >/dev/null 2>&1 \
            && pveum acl modify / --groups baseline-admins --roles Administrator >/dev/null 2>&1 \
            && say "group baseline-admins (Administrator)"; }
fi

# The datacenter firewall, with the two ports Baseline itself serves kept open. Proxmox adds the management rules for the local network.
if command -v pvesh >/dev/null 2>&1; then
    pvesh get /cluster/firewall/rules --output-format json 2>/dev/null | grep -q '"baseline-web"' || \
        pvesh create /cluster/firewall/rules --type in --action ACCEPT --proto tcp --dport 8100 --enable 1 --comment baseline-web >/dev/null 2>&1
    pvesh set /cluster/firewall/options --enable 1 >/dev/null 2>&1 && say "datacenter firewall enabled"
    # The way from Proxmox's own interface to Baseline (Datacenter > Summary > Notes).
    pvesh set /cluster/options --description "Baseline: [open the Baseline console](http://localhost:8100) - from another computer use http://<this host>:8100. On this machine's own screen: Ctrl+Alt+F1 is the Baseline text console." >/dev/null 2>&1 \
        && say "Datacenter notes point at Baseline"
fi

nag
exit 0
