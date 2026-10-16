Excerpts of the `[Unit]` and `[Install]` sections of Proxmox VE 9.2's own units (pve-cluster 9.1.5, pve-manager 9.2.2, pve-firewall 6.0.4,
pve-ha-manager 5.2.4, rrdcached 1.7.2-4.2+pve4, lxcfs 7.0.0-pve1), with the `[Service]` section replaced by a stub. They exist only so
`tests/unit/test_boot_unit_ordering.py` can ask systemd whether Baseline's units and Proxmox's together contain an ordering cycle.
