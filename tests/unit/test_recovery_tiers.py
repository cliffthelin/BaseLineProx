"""Tests for recovery_tiers.py - the real authorization model for
Baseline Recovery Mode (decision record 76). Per direct instruction:
"Without credential this is essentially guest access. without Proxmox
credential no proxmox changes are allowed and extremely reduced
visibility no logs and no added tools." Proxmox and persistence
credentials are independent axes - having one never implies the
other."""
import recovery_tiers as rt


def test_guest_actions_available_with_no_credentials_at_all():
    actions = rt.allowed_actions()
    assert "view_login_screen" in actions
    assert "view_recovery_screen" in actions


def test_guest_alone_never_allows_proxmox_changes():
    actions = rt.allowed_actions()
    assert "proxmox_changes" not in actions


def test_guest_alone_never_allows_viewing_logs():
    actions = rt.allowed_actions()
    assert "view_logs" not in actions


def test_guest_alone_never_allows_added_tools():
    actions = rt.allowed_actions()
    assert "use_added_tools" not in actions


def test_guest_alone_never_allows_user_persistence_access():
    actions = rt.allowed_actions()
    assert "read_user_persistence" not in actions
    assert "write_user_persistence" not in actions


def test_proxmox_credential_unlocks_proxmox_changes_logs_and_tools():
    actions = rt.allowed_actions(proxmox_authenticated=True)
    assert "proxmox_changes" in actions
    assert "view_logs" in actions
    assert "use_added_tools" in actions


def test_proxmox_credential_alone_does_not_unlock_user_persistence():
    actions = rt.allowed_actions(proxmox_authenticated=True)
    assert "read_user_persistence" not in actions
    assert "write_user_persistence" not in actions


def test_persistence_credential_unlocks_user_persistence_access():
    actions = rt.allowed_actions(persistence_authenticated=True)
    assert "read_user_persistence" in actions
    assert "write_user_persistence" in actions


def test_persistence_credential_alone_does_not_unlock_proxmox_changes():
    actions = rt.allowed_actions(persistence_authenticated=True)
    assert "proxmox_changes" not in actions
    assert "view_logs" not in actions
    assert "use_added_tools" not in actions


def test_both_credentials_together_unlock_everything():
    actions = rt.allowed_actions(proxmox_authenticated=True, persistence_authenticated=True)
    assert actions == (rt.GUEST_ACTIONS | rt.PROXMOX_ACTIONS | rt.PERSISTENCE_ACTIONS)


def test_guest_floor_is_always_present_regardless_of_credentials():
    for proxmox in (True, False):
        for persistence in (True, False):
            actions = rt.allowed_actions(proxmox_authenticated=proxmox, persistence_authenticated=persistence)
            assert rt.GUEST_ACTIONS <= actions


def test_is_allowed_matches_allowed_actions():
    assert rt.is_allowed("proxmox_changes", proxmox_authenticated=True) is True
    assert rt.is_allowed("proxmox_changes", proxmox_authenticated=False) is False
    assert rt.is_allowed("view_login_screen") is True
