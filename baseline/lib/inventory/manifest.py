"""Orchestrates every collector into one manifest.

redactor and clock are both injectable so tests get byte-identical
output (design doc correction #6): a real CLI run always passes a fresh
Redactor() (random key) and the real system clock via their defaults;
tests pass a fixed key and a fixed clock function instead.
"""
from . import pathsafety, schema
from .redact import Redactor
from .collectors import baseline_config, config_files, network, proxmox, scheduling, security, storage, system, tools


def collect_all(runner, source, host_label, node_names=None, fw_paths=None,
                 redactor=None, clock=None, tools_manifest=None):
    redactor = redactor if redactor is not None else Redactor()
    clock = clock if clock is not None else runner.now
    node_names = node_names or []
    fw_paths = fw_paths or []

    categories = {
        "packages": system.collect_packages(runner),
        "apt": system.collect_apt(runner),
        "platform_versions": system.collect_platform_versions(runner),
        "firmware_drivers": system.collect_firmware_drivers(runner),
        "systemd": system.collect_systemd_units(runner),
        "kernel_modules_udev": system.collect_kernel_udev(runner),
        "runtimes": system.collect_runtimes(runner),
        "network": network.collect_network(runner),
        "storage": storage.collect_storage(runner),
        "boot": storage.collect_boot(runner, redactor),
        "firewall_sysctl_dns_time": {
            **security.collect_dns_time(runner),
            "sysctl": security.collect_sysctl(runner),
            "firewall": security.collect_firewall_ruleset(runner),
            "journald": security.collect_journald(runner),
        },
        "scheduling": scheduling.collect_scheduling(runner, redactor),
        "baseline_config": baseline_config.collect_baseline_config(runner),
        "proxmox": {
            "storage_cfg": proxmox.collect_storage_cfg(runner),
            "datacenter_cfg": proxmox.collect_datacenter_cfg(runner),
            "nodes": proxmox.collect_nodes(runner, node_names, redactor),
            "firewall": proxmox.collect_firewall(runner, fw_paths, redactor),
            "storage_status": proxmox.collect_pvesm_status(runner, redactor),
            "cluster": proxmox.collect_cluster(runner),
            "repo_and_subscription": proxmox.collect_repo_and_subscription(runner),
        },
        "diagnostic_tools": tools.collect(runner, tools_manifest),
    }

    cf = config_files.collect_config_files(runner, redactor)
    categories["config_files_collection"] = {"_collection_notes": cf["_collection_notes"]}

    return schema.build_manifest(
        source=source, host_label=host_label, categories=categories,
        config_files=cf["entries"],
        redaction_report={"fields_redacted": redactor.fields_redacted, "key_id": redactor.key_id},
        clock=clock,
    )


def write_manifest(manifest, output_path, repo_root, overwrite=False):
    resolved = pathsafety.validate_output_path(output_path, repo_root, overwrite)
    data = schema.to_json(manifest)
    pathsafety.atomic_write(resolved, data, overwrite)
    return resolved
