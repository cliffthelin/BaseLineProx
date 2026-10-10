import proxmox_detect


def test_failed_probes_stop_the_installer_decision_as_unknown():
    state = proxmox_detect.InstallState(
        installed=False, evidence=[], errors=["dpkg-query: permission denied"])
    decision = proxmox_detect.decide_next_action(state)
    assert decision.action == "detection_unavailable"
    assert "permission denied" in decision.reason


def test_positive_proxmox_evidence_wins_over_an_unrelated_probe_error():
    state = proxmox_detect.InstallState(
        installed=True, version="8.2", evidence=["/etc/pve is mounted"],
        errors=["pveversion: timed out"])
    assert proxmox_detect.decide_next_action(state).action == "run_diagnostics_only"


def test_confirmed_absence_still_allows_the_installer_path():
    state = proxmox_detect.InstallState(installed=False, evidence=[])
    assert proxmox_detect.decide_next_action(state).action == "run_installer"


def test_firstboot_blocks_package_install_when_detection_state_is_unknown():
    import firstboot_statemachine
    result = firstboot_statemachine.proxmox_detection_block({
        "proxmox_installed": False,
        "proxmox_probe_errors": ["dpkg-query: permission denied"],
    })
    assert result == {
        "action": "detection_unavailable",
        "reason": "dpkg-query: permission denied",
        "package_install_allowed": False,
    }
