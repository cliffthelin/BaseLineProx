"""Local FakeRunner for the inventory branch - NOT shared with the
repair branch's tests/unit/fake_runner.py (design doc correction #2: no
cross-branch dependency). Tracks every call it receives so tests can
assert not just what a collector returned, but what it never even
attempted - the shape correction #10 specifically requires for
/etc/pve/nodes/<node>/priv/."""
from inventory.runner import CommandResult, Runner


class FakeRunner(Runner):
    def __init__(self):
        self.binaries = {}
        self.command_responses = []  # list of (predicate, CommandResult|callable)
        self.files = {}              # path -> text, or None for permission-denied
        self.dirs = {}                # path -> list[str], or None for permission-denied
        self.existing_paths = set()
        self.symlinks = set()
        self._clock_value = "2026-01-01T00:00:00Z"

        self.run_calls = []
        self.read_calls = []
        self.listdir_calls = []
        self.walk_calls = []

    def script(self, predicate, result):
        """result may be a CommandResult, or a callable(argv) -> CommandResult."""
        self.command_responses.insert(0, (predicate, result))

    def which(self, binary):
        return self.binaries.get(binary)

    def run(self, argv, timeout=15, max_output_bytes=1_000_000):
        self.run_calls.append(list(argv))
        binary = argv[0]
        if binary not in self.binaries or self.binaries[binary] is None:
            return CommandResult(ok=False, unavailable=True, reason=f"{binary} not found")
        for predicate, result in self.command_responses:
            if predicate(argv):
                return result(argv) if callable(result) else result
        return CommandResult(ok=False, unavailable=True, reason=f"no script for {argv}")

    def read_text(self, path, max_bytes=1_000_000):
        self.read_calls.append(path)
        if path not in self.files:
            return CommandResult(ok=False, unavailable=True, reason="not found")
        text = self.files[path]
        if text is None:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        truncated = len(text) > max_bytes
        return CommandResult(ok=True, stdout=text[:max_bytes], output_truncated=truncated)

    def listdir(self, path):
        self.listdir_calls.append(path)
        if path not in self.dirs:
            return CommandResult(ok=False, unavailable=True, reason="not found")
        entries = self.dirs[path]
        if entries is None:
            return CommandResult(ok=False, permission_denied=True, reason="permission denied")
        return CommandResult(ok=True, stdout="\n".join(sorted(entries)))

    def walk_bounded(self, path, max_depth, max_entries):
        self.walk_calls.append(path)
        entries = self.dirs.get(path) or []
        truncated = len(entries) > max_entries
        return CommandResult(ok=True, stdout="\n".join(entries[:max_entries]), output_truncated=truncated)

    def path_exists(self, path):
        return path in self.existing_paths or path in self.files or path in self.dirs

    def now(self):
        return self._clock_value
