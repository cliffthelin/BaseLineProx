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

Rootless-first: `rootless=True` (the default) puts the container under a
per-user Podman socket rather than root-owned Podman, matching the
"never trust a generic root-privileged daemon by default" instinct
already established for the GUI brokers (milestone-2-gui-plan.md's
"Baseline's own code is the mediator... never a generic OS service
trusted by default" - Podman itself is the one exception already
audited/vetted at the distro level, not a portal daemon Baseline would
otherwise avoid)."""
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
    rootless: bool = True
    auto_update: str | None = None                       # "registry" | "local" | None


def unit_path(name: str) -> str:
    return f"{QUADLET_UNIT_DIR}/{name}.container"


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
    if spec.auto_update:
        lines.append(f"AutoUpdate={spec.auto_update}")
    lines.append("")

    lines.append("[Service]")
    lines.append("Restart=always")
    lines.append("TimeoutStartSec=900")
    lines.append("")

    lines.append("[Install]")
    lines.append("WantedBy=multi-user.target")
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
    transient systemd unit under `/run/systemd/generator/`, then start
    it. **Deliberately `start`, never `enable`** - confirmed via a real
    QEMU smoke test (decision record 59) that `systemctl enable`
    outright refuses a generator-produced unit ("is transient or
    generated"). This isn't a workaround for a missing feature: a
    Quadlet unit's `[Install]`/`WantedBy=` is honored by the generator
    itself at every `daemon-reload`/boot, so there is nothing for
    `enable` to persist that the `.container` file's own presence
    doesn't already guarantee - `systemctl enable` on a Quadlet unit is
    simply the wrong verb, not a stricter version of the right one.
    Refuses (never guesses) if Podman itself isn't present - a missing
    dependency is reported, not silently worked around."""
    if not is_podman_installed(runner):
        return ApplyResult(False, "podman is not installed on this host - install it before writing any Quadlet unit")

    runner.write_text_atomic(unit_path(spec.name), generate_unit(spec))

    reload_proc = runner.run(["systemctl", "daemon-reload"], timeout=30)
    if reload_proc.returncode != 0:
        return ApplyResult(False, f"systemctl daemon-reload failed: {reload_proc.stderr.strip()[:300]}")

    start_proc = runner.run(["systemctl", "start", f"{spec.name}.service"], timeout=60)
    if start_proc.returncode != 0:
        return ApplyResult(False, f"systemctl start {spec.name}.service failed: {start_proc.stderr.strip()[:300]}")

    return ApplyResult(True, f"{spec.name}.service written, reloaded, and started")


def stop_and_remove(runner: Runner, name: str) -> ApplyResult:
    """Stops the service and removes the unit file - does NOT touch the
    container image or any named volume, matching this project's
    "never destroy data the operator didn't explicitly ask to lose"
    instinct (same posture as repair_rollback.py leaving backups in
    place). **Deliberately `stop`, never `disable`** - same reasoning
    as `write_and_start`: a Quadlet unit isn't "enabled" in the normal
    sense, so there is nothing meaningful for `disable` to undo: what
    actually prevents it from reappearing on the next `daemon-reload`/
    boot is removing the `.container` source file itself, done below."""
    stop_proc = runner.run(["systemctl", "stop", f"{name}.service"], timeout=60)
    if stop_proc.returncode != 0:
        return ApplyResult(False, f"systemctl stop {name}.service failed: {stop_proc.stderr.strip()[:300]}")
    if runner.path_exists(unit_path(name)):
        runner.remove(unit_path(name))
    runner.run(["systemctl", "daemon-reload"], timeout=30)
    return ApplyResult(True, f"{name}.service stopped and its unit file removed (image/volumes untouched)")


def status(runner: Runner, name: str) -> str:
    """Returns systemd's own is-active string ("active", "inactive",
    "failed", ...) rather than a Baseline-invented status vocabulary -
    one less thing to keep in sync with reality."""
    proc = runner.run(["systemctl", "is-active", f"{name}.service"], timeout=10)
    return proc.stdout.strip() or "unknown"


def is_running(runner: Runner, name: str) -> bool:
    return status(runner, name) == "active"
