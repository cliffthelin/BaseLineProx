"""Podman + Quadlet service management (Track B4 - see
docs/design/decision-records/58-podman-quadlet-service-management.md).

Podman/Quadlet was chosen over hand-rolled `podman run` + a bespoke
systemd unit per app for the same reason Fedora's own bootc-based
agentic-OS prototype (Red Hat, 2026) reaches for the identical
combination: Quadlet `.container` files are declarative, versionable,
and get turned into completely ordinary systemd units by
`systemd-quadlet-generator` at `daemon-reload` time - so every existing
Baseline convention for a service (enable/start/stop/status via
`systemctl`, logs via `journalctl`) keeps working unchanged, instead of
inventing a second, parallel lifecycle model for containerized apps.

This module never runs `podman` directly for lifecycle - it manages the
Quadlet unit *file* and drives systemd, same as `gui_session.py`
manages a compositor session and `kiosk_gate.py` gates a systemd unit.
Podman itself only ever runs as whatever systemd starts from the
generated unit.

GPU passthrough (`ContainerSpec.gpu_devices`, decision record 96) takes
already-resolved device strings, never a raw guess - a caller resolves
them for a specific detected device via
`gpu_admin.resolve_container_devices` first (a render node path for
AMD/Intel, a real CDI identifier for NVIDIA when `nvidia-smi` can
verify one), matching this module's existing "pure generator, caller
supplies already-real values" design for volumes/network/publish.

Rootless mode is fully implemented, not just a field: `ContainerSpec(rootless=True, user="someuser")`
runs the container under that user's own per-user Podman/systemd
session (`runuser -u <user> -- env XDG_RUNTIME_DIR=/run/user/<uid>
systemctl --user ...`, unit written to `~/.config/containers/systemd/`)
rather than root-owned Podman - matching the "never trust a generic
root-privileged daemon by default" instinct already established for the
GUI brokers (milestone-2-gui-plan.md's "Baseline's own code is the
mediator... never a generic OS service trusted by default"). **Defaults
to `rootless=False`, not `True`** - rootless mode needs a real,
resolvable target user with no sensible universal default (Baseline
itself runs as root today per this project's current-stage reality),
so the safe default matches what's actually true right now rather than
silently requiring an unstated prerequisite (`loginctl enable-linger
<user>`, that user having logged in at least once) that most callers
won't have satisfied. Opt into rootless deliberately, per container,
once that prerequisite is actually met."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError


QUADLET_UNIT_DIR = "/etc/containers/systemd"


@dataclass
class ContainerSpec:
    name: str
    image: str
    description: str = ""
    command: list[str] | None = None
    volumes: list[str] = field(default_factory=list)   # "host:container[:ro]" strings
    environment: dict[str, str] = field(default_factory=dict)
    network: str | None = None                          # e.g. "host", "none", a Quadlet .network name
    publish: list[str] = field(default_factory=list)     # "hostport:containerport" strings
    gpu_devices: list[str] = field(default_factory=list)  # real device strings - a render node path
                                                          # ("/dev/dri/renderD128") or a CDI identifier
                                                          # ("nvidia.com/gpu=<uuid>"), never a raw guess;
                                                          # see gpu_admin.resolve_container_devices, which
                                                          # resolves these for a specific gpu_admin.GpuDevice
                                                          # already validated for container_passthrough mode
    rootless: bool = False                               # see module docstring: True requires .user,
                                                          # there is no sensible default user to fall
                                                          # back to, so this defaults to matching
                                                          # Baseline's actual current reality (runs as
                                                          # root today) rather than silently requiring
                                                          # an unstated prerequisite
    user: str | None = None                              # required when rootless=True - the target
                                                          # unprivileged user this container runs as
    auto_update: str | None = None                       # "registry" | "local" | None


class RootlessUserRequired(ValueError):
    """Raised when `ContainerSpec.rootless=True` but `.user` is unset -
    there is no default user to fall back to; guessing one would be
    worse than refusing (see `write_and_start`'s own docstring)."""


def unit_path(name: str, *, rootless: bool = False, user_home: str | None = None) -> str:
    """Root-owned units live under the fixed system path; a rootless
    unit lives under the target user's own `~/.config/containers/systemd/`
    - real per-user Quadlet lookup, per Podman's own documented layout,
    never a guessed `/home/<user>` path (that assumption breaks for
    LDAP/NFS-homed accounts) - `user_home` must be resolved for real
    first (see `_lookup_user_uid_and_home`)."""
    if rootless:
        if not user_home:
            raise RootlessUserRequired("unit_path(rootless=True) requires a real user_home - resolve it first, never guess it")
        return f"{user_home.rstrip('/')}/.config/containers/systemd/{name}.container"
    return f"{QUADLET_UNIT_DIR}/{name}.container"


def _lookup_user_uid_and_home(runner: Runner, user: str) -> tuple[str, str]:
    """Real lookup via `getent passwd` - never assumes `/home/<user>`,
    which is wrong for LDAP/NFS-homed or otherwise-relocated accounts."""
    proc = runner.run(["getent", "passwd", user], timeout=10)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RootlessUserRequired(f"could not resolve user {user!r} via getent passwd: {proc.stderr.strip() or 'no such user'}")
    fields = proc.stdout.strip().split(":")
    if len(fields) < 6:
        raise RootlessUserRequired(f"unexpected getent passwd output for {user!r}: {proc.stdout!r}")
    return fields[2], fields[5]  # uid, home directory


def _systemctl_prefix(rootless: bool, user: str | None = None, *, uid: str | None = None) -> list[str]:
    """Root mode: plain `systemctl`. Rootless mode: `runuser` into the
    target user's own session with `XDG_RUNTIME_DIR` explicitly set
    (systemd's user-session bus lives at `/run/user/<uid>` - `--user`
    alone doesn't find it when invoked from a root shell that never
    logged in as that user) - real prerequisite the operator must have
    already satisfied once via `loginctl enable-linger <user>`, not
    something this module can do on its own (that's a one-time,
    account-level change, not a per-container operation)."""
    if not rootless:
        return ["systemctl"]
    if not user:
        raise RootlessUserRequired("rootless=True requires user to be set - never defaulted or guessed")
    return ["runuser", "-u", user, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl", "--user"]


def generate_unit(spec: ContainerSpec) -> str:
    """Pure - no I/O, no subprocess. Returns Quadlet `.container` file
    content (systemd's own Quadlet INI format); the caller writes it
    via a Runner, matching browser_policy.generate()'s "pure generator,
    caller does I/O" split."""
    lines = ["[Unit]"]
    if spec.description:
        lines.append(f"Description={spec.description}")
    lines.append("")

    lines.append("[Container]")
    lines.append(f"Image={spec.image}")
    lines.append(f"ContainerName={spec.name}")
    if spec.command:
        lines.append(f"Exec={' '.join(spec.command)}")
    for volume in spec.volumes:
        lines.append(f"Volume={volume}")
    for key, value in sorted(spec.environment.items()):
        lines.append(f"Environment={key}={value}")
    if spec.network:
        lines.append(f"Network={spec.network}")
    for port in spec.publish:
        lines.append(f"PublishPort={port}")
    for device in spec.gpu_devices:
        lines.append(f"AddDevice={device}")
    if spec.auto_update:
        lines.append(f"AutoUpdate={spec.auto_update}")
    lines.append("")

    lines.append("[Service]")
    lines.append("Restart=always")
    lines.append("TimeoutStartSec=900")
    lines.append("")

    lines.append("[Install]")
    # A rootless unit is generated into the user's own systemd instance,
    # which has no multi-user.target - only default.target. Writing
    # multi-user.target there made the generator's [Install] a no-op, so
    # a rootless container silently never started at boot.
    lines.append("WantedBy=default.target" if spec.rootless else "WantedBy=multi-user.target")
    return "\n".join(lines) + "\n"


def is_podman_installed(runner: Runner) -> bool:
    proc = runner.run(["podman", "--version"], timeout=10)
    return proc.returncode == 0


@dataclass
class ApplyResult:
    applied: bool
    detail: str


def write_and_start(runner: Runner, spec: ContainerSpec) -> ApplyResult:
    """Write the generated unit, reload systemd so Quadlet's own
    generator (`podman-system-generator`) turns it into a real,
    transient systemd unit under `/run/systemd/generator/` (system mode)
    or the user generator's own equivalent (rootless mode), then start
    it. **Deliberately `start`, never `enable`** - confirmed via a real
    QEMU smoke test (decision record 59) that `systemctl enable`
    outright refuses a generator-produced unit ("is transient or
    generated"). This isn't a workaround for a missing feature: a
    Quadlet unit's `[Install]`/`WantedBy=` is honored by the generator
    itself at every `daemon-reload`/boot, so there is nothing for
    `enable` to persist that the `.container` file's own presence
    doesn't already guarantee - `systemctl enable` on a Quadlet unit is
    simply the wrong verb, not a stricter version of the right one.
    Refuses (never guesses) if Podman itself isn't present, or if
    `spec.rootless` is set without a real, resolvable `spec.user` - a
    missing dependency is reported, not silently worked around."""
    if not is_podman_installed(runner):
        return ApplyResult(False, "podman is not installed on this host - install it before writing any Quadlet unit")

    uid = user_home = None
    if spec.rootless:
        if not spec.user:
            return ApplyResult(False, "ContainerSpec.rootless=True requires .user (the target unprivileged user) to be set")
        try:
            uid, user_home = _lookup_user_uid_and_home(runner, spec.user)
        except RootlessUserRequired as exc:
            return ApplyResult(False, str(exc))

    runner.write_text_atomic(unit_path(spec.name, rootless=spec.rootless, user_home=user_home), generate_unit(spec))

    prefix = _systemctl_prefix(spec.rootless, spec.user, uid=uid)
    reload_proc = runner.run(prefix + ["daemon-reload"], timeout=30)
    if reload_proc.returncode != 0:
        return ApplyResult(False, f"systemctl daemon-reload failed: {reload_proc.stderr.strip()[:300]}")

    start_proc = runner.run(prefix + ["start", f"{spec.name}.service"], timeout=60)
    if start_proc.returncode != 0:
        return ApplyResult(False, f"systemctl start {spec.name}.service failed: {start_proc.stderr.strip()[:300]}")

    mode = f"rootless (user={spec.user})" if spec.rootless else "root"
    return ApplyResult(True, f"{spec.name}.service written, reloaded, and started ({mode})")


def stop_and_remove(runner: Runner, name: str, *, rootless: bool = False, user: str | None = None) -> ApplyResult:
    """Stops the service and removes the unit file - does NOT touch the
    container image or any named volume, matching this project's
    "never destroy data the operator didn't explicitly ask to lose"
    instinct (same posture as repair_rollback.py leaving backups in
    place). **Deliberately `stop`, never `disable`** - same reasoning
    as `write_and_start`: a Quadlet unit isn't "enabled" in the normal
    sense, so there is nothing meaningful for `disable` to undo: what
    actually prevents it from reappearing on the next `daemon-reload`/
    boot is removing the `.container` source file itself, done below.
    `rootless`/`user` must match whatever `write_and_start` originally
    used for this same container - this function does not remember
    that for you."""
    uid = user_home = None
    if rootless:
        if not user:
            return ApplyResult(False, "rootless=True requires user (the target unprivileged user) to be set")
        try:
            uid, user_home = _lookup_user_uid_and_home(runner, user)
        except RootlessUserRequired as exc:
            return ApplyResult(False, str(exc))

    prefix = _systemctl_prefix(rootless, user, uid=uid)
    stop_proc = runner.run(prefix + ["stop", f"{name}.service"], timeout=60)
    if stop_proc.returncode != 0:
        return ApplyResult(False, f"systemctl stop {name}.service failed: {stop_proc.stderr.strip()[:300]}")
    path = unit_path(name, rootless=rootless, user_home=user_home)
    if runner.path_exists(path):
        runner.remove(path)
    runner.run(prefix + ["daemon-reload"], timeout=30)
    return ApplyResult(True, f"{name}.service stopped and its unit file removed (image/volumes untouched)")


def status(runner: Runner, name: str, *, rootless: bool = False, user: str | None = None) -> str:
    """Returns systemd's own is-active string ("active", "inactive",
    "failed", ...) rather than a Baseline-invented status vocabulary -
    one less thing to keep in sync with reality."""
    if rootless:
        if not user:
            return "unknown"
        try:
            uid, _home = _lookup_user_uid_and_home(runner, user)
        except RootlessUserRequired:
            return "unknown"
        prefix = _systemctl_prefix(True, user, uid=uid)
    else:
        prefix = ["systemctl"]
    proc = runner.run(prefix + ["is-active", f"{name}.service"], timeout=10)
    return proc.stdout.strip() or "unknown"


def is_running(runner: Runner, name: str, *, rootless: bool = False, user: str | None = None) -> bool:
    return status(runner, name, rootless=rootless, user=user) == "active"
