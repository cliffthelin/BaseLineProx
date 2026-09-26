"""Docker container provisioning - the "compatibility beyond LXC" half
of Track A6's always-on utility-service primitive.

`vm_provision.py`/`pct_provision.py` (decision records 34/35) both
wrap Proxmox's own `qm`/`pct` - genuinely useful, but a container
built for `pct` only ever runs on Proxmox. A Docker image runs
identically on a Proxmox VM, a bare-metal host, or the cloud - the
portability the earlier cross-hypervisor scoping document
(`cross-hypervisor-provisioning-scoping.md`) recommended against
solving in general, but the container-image-format half of that same
idea is already solved, proven technology, not something this project
would be inventing.

Same `Runner`-injectable convention as the other two provisioning
modules; wraps the `docker` CLI directly (no SDK dependency), matching
this project's stdlib-only, subprocess-based convention throughout.
Where this would actually run - directly on a Docker-capable Proxmox
host, or inside a VM/LXC that itself runs Docker - is not decided by
this module; it only wraps the `docker` command itself.
"""
from __future__ import annotations

from vm_provision import CommandResult  # re-exported: same result shape, same convention

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


# ---------------------------------------------------------------------------
# Pure argv builders
# ---------------------------------------------------------------------------

def create_container_argv(name: str, image: str, *, ports: dict = None,
                           volumes: dict = None, env: dict = None,
                           restart_policy: str = "unless-stopped",
                           detach: bool = True) -> list:
    argv = ["docker", "run"]
    if detach:
        argv.append("-d")
    argv += ["--name", name, "--restart", restart_policy]
    for host_port, container_port in (ports or {}).items():
        argv += ["-p", f"{host_port}:{container_port}"]
    for host_path, container_path in (volumes or {}).items():
        argv += ["-v", f"{host_path}:{container_path}"]
    for key, value in (env or {}).items():
        argv += ["-e", f"{key}={value}"]
    argv.append(image)
    return argv


def start_container_argv(name: str) -> list:
    return ["docker", "start", name]


def stop_container_argv(name: str) -> list:
    return ["docker", "stop", name]


def remove_container_argv(name: str, *, force: bool = True) -> list:
    argv = ["docker", "rm"]
    if force:
        argv.append("-f")
    argv.append(name)
    return argv


def inspect_running_argv(name: str) -> list:
    return ["docker", "inspect", name, "--format", "{{.State.Running}}"]


# ---------------------------------------------------------------------------
# Runner-executed operations
# ---------------------------------------------------------------------------

def create_container(runner: Runner, name: str, image: str, **kwargs) -> CommandResult:
    argv = create_container_argv(name, image, **kwargs)
    proc = runner.run(argv, timeout=60)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"docker run exited {proc.returncode}")
    return CommandResult(True, f"container {name!r} ({image}) created")


def start_container(runner: Runner, name: str) -> CommandResult:
    proc = runner.run(start_container_argv(name), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"docker start exited {proc.returncode}")
    return CommandResult(True, f"container {name!r} started")


def stop_container(runner: Runner, name: str) -> CommandResult:
    proc = runner.run(stop_container_argv(name), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"docker stop exited {proc.returncode}")
    return CommandResult(True, f"container {name!r} stopped")


def remove_container(runner: Runner, name: str, *, force: bool = True) -> CommandResult:
    proc = runner.run(remove_container_argv(name, force=force), timeout=30)
    if proc.returncode != 0:
        return CommandResult(False, proc.stderr.strip() or f"docker rm exited {proc.returncode}")
    return CommandResult(True, f"container {name!r} removed")


def is_running(runner: Runner, name: str) -> bool:
    """False for both "stopped" and "doesn't exist at all" - a caller
    that needs to tell those apart should inspect proc.returncode/
    stderr itself; this helper only answers "can I treat it as up right
    now," matching how vm_provision/pct_provision's own status checks
    are used from bin/baseline."""
    proc = runner.run(inspect_running_argv(name), timeout=10)
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == "true"
