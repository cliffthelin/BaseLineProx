"""The real authorization model for Baseline Recovery Mode (decision
record 76). Per direct instruction: "Without credential this is
essentially guest access. without Proxmox credential no proxmox
changes are allowed and extremely reduced visibility no logs and no
added tools."

Proxmox and USER credentials are independent axes, not a
single linear tier - having proven one never implies the other. The
guest floor (reaching the login/recovery screen itself) is always
present, never conditionally withheld; everything else is a strict,
explicit allowlist per proven credential, never an inferred permission.
"""
from __future__ import annotations

GUEST_ACTIONS = frozenset({"view_login_screen", "view_recovery_screen"})
PROXMOX_ACTIONS = frozenset({"proxmox_changes", "view_logs", "use_added_tools"})
USER_VOLUME_ACTIONS = frozenset({"read_user_volume", "write_user_volume"})


def allowed_actions(*, proxmox_authenticated: bool = False, user_volume_authenticated: bool = False) -> frozenset:
    actions = set(GUEST_ACTIONS)
    if proxmox_authenticated:
        actions |= PROXMOX_ACTIONS
    if user_volume_authenticated:
        actions |= USER_VOLUME_ACTIONS
    return frozenset(actions)


def is_allowed(action: str, *, proxmox_authenticated: bool = False, user_volume_authenticated: bool = False) -> bool:
    return action in allowed_actions(proxmox_authenticated=proxmox_authenticated,
                                      user_volume_authenticated=user_volume_authenticated)
