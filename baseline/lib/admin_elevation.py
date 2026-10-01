"""The real cross-persona "sudo" gate for the admin persona (decision
record 76). Admin has open access to every persona's USER,
but only after a SEPARATE, additional passphrase - not the same
secret as admin's own base login - per direct instruction: "Admin has
open access to each and an additional passphrase. This is to add an
extra guard from it being primary target to get access to all
accounts. it's essentially sudo or root."

Deliberately short-lived (default 15 minutes, `settings_store`'s own
`admin_elevation_ttl_minutes` - matching real `sudo`'s well-known
default `timestamp_timeout`) and separate from admin's own base
session: a compromised admin session alone still can't reach another
persona's data without the elevation passphrase having been entered
within this much shorter window.

Passphrase verification itself is injected as a plain callable, not
owned by this module - matches this project's established
`drive_setup_answer.py`/`settings_web.py` "hasher/verifier as a
callable" convention, so this module never needs its own opinion about
how the elevation secret is hashed or stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import settings_store


@dataclass
class ElevationTicket:
    granted_at: float

    def expired(self, now: float, ttl_minutes: float) -> bool:
        return now > self.granted_at + ttl_minutes * 60


@dataclass
class ElevationStore:
    tickets: dict = field(default_factory=dict)

    def grant(self, now: float) -> None:
        self.tickets["elevated"] = ElevationTicket(granted_at=now)

    def is_elevated(self, runner, now: float) -> bool:
        ticket = self.tickets.get("elevated")
        if ticket is None:
            return False
        ttl_minutes = settings_store.get_setting("sessions", "admin_elevation_ttl_minutes")
        if ticket.expired(now, ttl_minutes):
            del self.tickets["elevated"]
            return False
        return True

    def revoke(self) -> None:
        self.tickets.pop("elevated", None)


def attempt_elevation(store: ElevationStore, verify_fn, passphrase: str, now: float) -> bool:
    """`verify_fn(passphrase) -> bool` is the injected check against
    the real, separately-stored elevation secret. Grants a fresh
    ticket only on a genuine match - never on a falsy/exception-raising
    verifier being silently treated as success."""
    if not verify_fn(passphrase):
        return False
    store.grant(now)
    return True


def require_elevation(store: ElevationStore, runner, now: float) -> bool:
    """Is admin currently allowed to touch another persona's data
    right now? True only inside the elevation ticket's own TTL window -
    real, present-tense state, never "was ever granted, once"."""
    return store.is_elevated(runner, now)
