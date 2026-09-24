from inventory.redact import Redactor
from inventory.runner import CommandResult
from inventory.collectors import proxmox

from .fake_runner import FakeRunner


def test_storage_cfg_drops_secret_shaped_fields():
    r = FakeRunner()
    r.files["/etc/pve/storage.cfg"] = "dir: local\n password mysecret\n content images\n"
    result = proxmox.collect_storage_cfg(r)
    assert "mysecret" not in str(result)


def test_storage_cfg_keeps_allowlisted_fields():
    r = FakeRunner()
    r.files["/etc/pve/storage.cfg"] = "dir: local\n content images\n shared 1\n"
    result = proxmox.collect_storage_cfg(r)
    assert result["entries"][0]["fields"]["content"] == "images"


def test_datacenter_cfg_unknown_fields_recorded_as_names_only_no_values():
    r = FakeRunner()
    r.files["/etc/pve/datacenter.cfg"] = "keyboard: en-us\nsome_future_field: secret-looking-value\n"
    result = proxmox.collect_datacenter_cfg(r)
    assert "secret-looking-value" not in str(result)
    assert result["unknown_fields"]["names"] == ["some_future_field"]
    assert result["unknown_fields"]["count"] == 1
    assert result["fields"]["keyboard"] == "en-us"


def test_node_names_are_tokenized_never_raw():
    r = FakeRunner()
    r.dirs["/etc/pve/nodes/realhostname/qemu-server"] = []
    r.dirs["/etc/pve/nodes/realhostname/lxc"] = []
    redactor = Redactor(key=b"fixed")
    result = proxmox.collect_nodes(r, ["realhostname"], redactor)
    assert "realhostname" not in result
    assert any(key.startswith("host:") for key in result)


def test_never_lists_or_reads_priv_directory():
    """Correction #10: the collector must never even attempt priv/, not
    merely handle a PermissionError gracefully if it does."""
    r = FakeRunner()
    r.dirs["/etc/pve/nodes/node1/qemu-server"] = ["100.conf"]
    r.files["/etc/pve/nodes/node1/qemu-server/100.conf"] = "cores: 2\n"
    r.dirs["/etc/pve/nodes/node1/lxc"] = []
    r.dirs["/etc/pve/nodes/node1/priv"] = ["authorized_keys", "pve-root-ca.pem"]
    redactor = Redactor(key=b"fixed")
    proxmox.collect_nodes(r, ["node1"], redactor)
    assert not any("priv" in path for path in r.listdir_calls)
    assert not any("priv" in path for path in r.read_calls)


def test_vmid_tokens_are_consistent_within_one_run():
    r = FakeRunner()
    r.dirs["/etc/pve/nodes/node1/qemu-server"] = ["100.conf"]
    r.files["/etc/pve/nodes/node1/qemu-server/100.conf"] = "cores: 2\n"
    r.dirs["/etc/pve/nodes/node1/lxc"] = []
    redactor = Redactor(key=b"fixed")
    result = proxmox.collect_nodes(r, ["node1"], redactor)
    node_token = next(iter(result))
    vmid_token_a = result[node_token]["qemu"][0]["vmid_token"]
    vmid_token_b = redactor.tokenize("100", "vmid")
    assert vmid_token_a == vmid_token_b


def test_net_line_keeps_bridge_drops_mac():
    r = FakeRunner()
    r.dirs["/etc/pve/nodes/node1/qemu-server"] = ["100.conf"]
    r.files["/etc/pve/nodes/node1/qemu-server/100.conf"] = "net0: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0\n"
    r.dirs["/etc/pve/nodes/node1/lxc"] = []
    redactor = Redactor(key=b"fixed")
    result = proxmox.collect_nodes(r, ["node1"], redactor)
    node_token = next(iter(result))
    fields = result[node_token]["qemu"][0]["fields"]
    assert fields["net0"]["bridge"] == "vmbr0"
    assert "AA:BB:CC:DD:EE:FF" not in str(fields)


def test_pvesubscription_get_never_invoked():
    r = FakeRunner()
    proxmox.collect_repo_and_subscription(r)
    assert not any(call and call[0] == "pvesubscription" for call in r.run_calls)


def test_subscription_status_is_unavailable_with_reason():
    r = FakeRunner()
    result = proxmox.collect_repo_and_subscription(r)
    assert result["subscription_status"] == "unavailable"
    assert "pvesubscription get is not run" in result["subscription_status_reason"]


def test_repo_channel_enabled_state_still_reported():
    r = FakeRunner()
    r.files["/etc/apt/sources.list.d/pve-enterprise.list"] = "# deb https://enterprise.proxmox.com/...\n"
    r.files["/etc/apt/sources.list.d/pve-no-subscription.list"] = "deb http://download.proxmox.com/... bookworm pve-no-subscription\n"
    result = proxmox.collect_repo_and_subscription(r)
    assert result["enterprise_repo_enabled"] is False
    assert result["no_subscription_repo_enabled"] is True


def test_pvesm_status_excludes_live_usage_keeps_structure():
    r = FakeRunner()
    r.binaries["pvesm"] = "/usr/sbin/pvesm"
    r.script(
        lambda a: a[:2] == ["pvesm", "status"],
        CommandResult(ok=True, stdout="Name Type Status Total Used Available %\nlocal dir active 100 50 50 50.00%\n"),
    )
    redactor = Redactor(key=b"fixed")
    result = proxmox.collect_pvesm_status(r, redactor)
    entry = result["storages"][0]
    assert entry["total_capacity"] == "100"
    assert "used" not in entry
    assert "available" not in entry
    assert "%" not in entry
    assert entry["name_token"] != "local"


def test_firewall_addresses_are_tokenized_structure_kept():
    r = FakeRunner()
    r.files["/etc/pve/firewall/cluster.fw"] = "IN ACCEPT -source 10.0.0.5 -dest 10.0.0.1 -p tcp -dport 22\n"
    redactor = Redactor(key=b"fixed")
    result = proxmox.collect_firewall(r, ["/etc/pve/firewall/cluster.fw"], redactor)
    rule = result["/etc/pve/firewall/cluster.fw"][0]
    assert "10.0.0.5" not in str(rule)
    assert "10.0.0.1" not in str(rule)
    assert rule["proto"] == "tcp"
    assert rule["dport"] == "22"


def test_cluster_reports_standalone_when_no_corosync_files():
    r = FakeRunner()
    result = proxmox.collect_cluster(r)
    assert result == {"clustered": False, "membership": None}


def test_cluster_reports_clustered_without_raw_pvecm_parsing():
    r = FakeRunner()
    r.existing_paths.add("/etc/pve/corosync.conf")
    r.binaries["pvecm"] = "/usr/sbin/pvecm"
    r.script(lambda a: a[:2] == ["pvecm", "status"], CommandResult(ok=True, stdout="fake membership output"))
    result = proxmox.collect_cluster(r)
    assert result["clustered"] is True
    assert result["status_command_available"] is True
