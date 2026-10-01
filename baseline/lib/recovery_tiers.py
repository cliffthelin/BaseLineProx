"""The real authorization model for Baseline Recovery Mode (decision
record 76). Per direct instruction: "Without credential this is
essentially nothing beyond the login screen. without Proxmox credential no proxmox
changes are allowed and extremely reduced visibility no logs and no
added tools."

Proxmox and USER credentials are independent axes, not a
single linear tier - having proven one never implies the other. The only
thing available without any credential is the login screen itself. There
is no unauthenticated access, and no setting or admin can grant one anything more
(direct instruction, 2026-09-30): the rest is a strict, explicit allowlist
per proven credential, never an inferred permission. Recovery mode is its
own credential - this machine's root password or its passphrase, each
stored only as a one-way hash (verifiable, never decryptable).
"""
from __future__ import annotations

LOGIN_SCREEN_ACTIONS = frozenset({"view_login_screen"})
RECOVERY_ACTIONS = frozenset({"view_recovery_screen"})
PROXMOX_ACTIONS = frozenset({"proxmox_changes", "view_logs", "use_added_tools"})
USER_VOLUME_ACTIONS = frozenset({"read_user_volume", "write_user_volume"})


def allowed_actions(*, proxmox_authenticated: bool = False, user_volume_authenticated: bool = False,
                    recovery_authenticated: bool = False) -> frozenset:
    actions = set(LOGIN_SCREEN_ACTIONS)
    if recovery_authenticated:
        actions |= RECOVERY_ACTIONS
    if proxmox_authenticated:
        actions |= PROXMOX_ACTIONS
    if user_volume_authenticated:
        actions |= USER_VOLUME_ACTIONS
    return frozenset(actions)


def is_allowed(action: str, *, proxmox_authenticated: bool = False, user_volume_authenticated: bool = False,
               recovery_authenticated: bool = False) -> bool:
    return action in allowed_actions(proxmox_authenticated=proxmox_authenticated,
                                      user_volume_authenticated=user_volume_authenticated,
                                      recovery_authenticated=recovery_authenticated)
