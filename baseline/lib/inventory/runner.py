"""Inventory-local subprocess/filesystem/clock abstraction.

Deliberately NOT a re-export of repair.Runner. This branch
(inventory/current-drive-manifest) was created from main, before
repair.py existed on repair/host-network-reset-to-dhcp - importing it
here would create an undeclared dependency on a branch this one doesn't
descend from. A shared runner module is a reasonable refactor to propose
once both branches have merged into main, not before (see
docs/design/current-drive-inventory-plan.md, correction #2).

Every method is bounded by construction: run() takes an explicit timeout
and a maximum captured-output size and returns a CommandResult recording
timed_out/output_truncated/permission_denied/unavailable rather than
raising - a missing tool, a timeout, or a permission error are all
first-class, reportable outcomes for a read-only inventory, never
exceptions that abort the whole collection run.
"""
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 15
DEFAULT_MAX_OUTPUT_BYTES = 1_000_000


@dataclass
class CommandResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: "int | None" = None
    timed_out: bool = False
    output_truncated: bool = False
    permission_denied: bool = False
    unavailable: bool = False
    reason: str = ""


def _cap(text, max_bytes):
    data = text.encode(errors="replace")
    if len(data) <= max_bytes:
        return text, False
    return data[:max_bytes].decode(errors="ignore"), True


class Runner:
    """Injectable abstraction - FakeRunner in tests/unit/inventory/
    implements the same interface without touching a real host."""

    def which(self, binary):
        raise NotImplementedError

    def run(self, argv, timeout=DEFAULT_TIMEOUT_S, max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES):
        raise NotImplementedError

    def read_text(self, path, max_bytes=DEFAULT_MAX_OUTPUT_BYTES):
        raise NotImplementedError

    def listdir(self, path):
        raise NotImplementedError

    def walk_bounded(self, path, max_depth, max_entries):
        raise NotImplementedError

    def path_exists(self, path):
        raise NotImplementedError

    def now(self):
        raise NotImplementedError


class RealRunner(Runner):
    def which(self, binary):
        # shutil.which(), never `["command", "-v", binary]` - command -v
        # is normally a shell builtin, so shelling out for it would mean
        # invoking a shell solely for discovery (design doc correction #7).
        return shutil.which(binary)

    def run(self, argv, timeout=DEFAULT_TIMEOUT_S, max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES):
        binary = argv[0]
        if self.which(binary) is None:
            return CommandResult(ok=False, unavailable=True, reason=f"{binary} not found on PATH")
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return CommandResult(ok=False, timed_out=True, reason=f"timed out after {timeout}s")
        except PermissionError:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        stdout, truncated_out = _cap(proc.stdout, max_output_bytes)
        stderr, truncated_err = _cap(proc.stderr, max_output_bytes)
        return CommandResult(
            ok=proc.returncode == 0, stdout=stdout, stderr=stderr,
            returncode=proc.returncode, output_truncated=truncated_out or truncated_err,
        )

    def read_text(self, path, max_bytes=DEFAULT_MAX_OUTPUT_BYTES):
        try:
            with open(path, "r", errors="replace") as f:
                data = f.read(max_bytes + 1)
        except FileNotFoundError:
            return CommandResult(ok=False, unavailable=True, reason="not found")
        except PermissionError:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        except IsADirectoryError:
            return CommandResult(ok=False, unavailable=True, reason="is a directory")
        truncated = len(data) > max_bytes
        return CommandResult(ok=True, stdout=data[:max_bytes], output_truncated=truncated)

    def listdir(self, path):
        try:
            return CommandResult(ok=True, stdout="\n".join(sorted(os.listdir(path))))
        except FileNotFoundError:
            return CommandResult(ok=False, unavailable=True, reason="not found")
        except PermissionError:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        except NotADirectoryError:
            return CommandResult(ok=False, unavailable=True, reason="not a directory")

    def walk_bounded(self, path, max_depth, max_entries):
        entries = []
        truncated = False
        base_depth = path.rstrip("/").count("/")
        try:
            for root, dirs, files in os.walk(path):
                depth = root.rstrip("/").count("/") - base_depth
                if depth >= max_depth:
                    dirs[:] = []
                    continue
                dirs.sort()
                stop = False
                for name in sorted(dirs) + sorted(files):
                    entries.append(os.path.join(root, name))
                    if len(entries) >= max_entries:
                        truncated = True
                        stop = True
                        break
                if stop:
                    break
        except PermissionError:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        except FileNotFoundError:
            return CommandResult(ok=False, unavailable=True, reason="not found")
        return CommandResult(ok=True, stdout="\n".join(entries), output_truncated=truncated)

    def path_exists(self, path):
        return os.path.exists(path)

    def now(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
