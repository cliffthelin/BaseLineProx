"""Tests for recovery_tiers.py - the real authorization model for
Baseline Recovery Mode (decision record 76). Per direct instruction:
"Without credential this is essentially nothing beyond the login screen. without Proxmox
credential no proxmox changes are allowed and extremely reduced
visibility no logs and no added tools." Proxmox and persistence
credentials are independent axes - having one never implies the
other."""
import recovery_tiers as rt


def test_with_no_credential_only_the_login_screen_is_available():
    """Nothing is reachable without a credential: nothing beyond the login screen without a credential."""
    assert rt.allowed_actions() == frozenset({"view_login_screen"})
    assert rt.LOGIN_SCREEN_ACTIONS == frozenset({"view_login_screen"})


def test_the_recovery_screen_needs_the_root_password_or_machine_passphrase():
    assert "view_recovery_screen" not in rt.allowed_actions()
    assert "view_recovery_screen" not in rt.allowed_actions(proxmox_authenticated=True)
    assert "view_recovery_screen" in rt.allowed_actions(recovery_authenticated=True)


def test_login_screen_alone_never_allows_proxmox_changes():
    actions = rt.allowed_actions()
    assert "proxmox_changes" not in actions


def test_login_screen_alone_never_allows_viewing_logs():
    actions = rt.allowed_actions()
    assert "view_logs" not in actions


def test_login_screen_alone_never_allows_added_tools():
    actions = rt.allowed_actions()
    assert "use_added_tools" not in actions


def test_login_screen_alone_never_allows_user_volume_access():
    actions = rt.allowed_actions()
    assert "read_user_volume" not in actions
    assert "write_user_volume" not in actions


def test_proxmox_credential_unlocks_proxmox_changes_logs_and_tools():
    actions = rt.allowed_actions(proxmox_authenticated=True)
    assert "proxmox_changes" in actions
    assert "view_logs" in actions
    assert "use_added_tools" in actions


def test_proxmox_credential_alone_does_not_unlock_user_volume():
    actions = rt.allowed_actions(proxmox_authenticated=True)
    assert "read_user_volume" not in actions
    assert "write_user_volume" not in actions


def test_persistence_credential_unlocks_user_volume_access():
    actions = rt.allowed_actions(user_volume_authenticated=True)
    assert "read_user_volume" in actions
    assert "write_user_volume" in actions


def test_persistence_credential_alone_does_not_unlock_proxmox_changes():
    actions = rt.allowed_actions(user_volume_authenticated=True)
    assert "proxmox_changes" not in actions
    assert "view_logs" not in actions
    assert "use_added_tools" not in actions


def test_both_credentials_together_unlock_everything():
    actions = rt.allowed_actions(proxmox_authenticated=True, user_volume_authenticated=True)
    assert actions == (rt.LOGIN_SCREEN_ACTIONS | rt.PROXMOX_ACTIONS | rt.USER_VOLUME_ACTIONS)
    assert "view_recovery_screen" not in actions   # recovery is its own credential


def test_the_login_screen_is_always_present_regardless_of_credentials():
    for proxmox in (True, False):
        for persistence in (True, False):
            actions = rt.allowed_actions(proxmox_authenticated=proxmox, user_volume_authenticated=persistence)
            assert rt.LOGIN_SCREEN_ACTIONS <= actions


def test_is_allowed_matches_allowed_actions():
    assert rt.is_allowed("proxmox_changes", proxmox_authenticated=True) is True
    assert rt.is_allowed("proxmox_changes", proxmox_authenticated=False) is False
    assert rt.is_allowed("view_login_screen") is True
