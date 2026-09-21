"""In-memory Runner for the repair-action test suite - no test importing
this ever calls real subprocess/filesystem/clock. See repair.Runner for the
interface being faked."""
import posixpath
from dataclasses import dataclass, field

import repair


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeRunner(repair.Runner):
    def __init__(self, files=None, command_responses=None, clock_start=1_700_000_000.0):
        self.files = dict(files or {})
        self.dirs = set()
        for path in list(self.files):
            self._mark_parents(path)
        # command_responses: list of (argv0_and_predicate, FakeProc) checked
        # in order; predicate(argv) -> bool. Default: returncode 0, empty.
        self.command_responses = list(command_responses or [])
        self.calls = []          # every argv passed to run(), in order
        self.writes = []         # every path written via write_text_atomic
        self.appends = []
        self._clock = clock_start
        self.sleeps = []

    # -- fs -----------------------------------------------------------
    def _mark_parents(self, path):
        p = posixpath.dirname(path)
        while p and p not in self.dirs:
            self.dirs.add(p)
            p = posixpath.dirname(p)

    def read_text(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_text_atomic(self, path, content):
        self.files[path] = content
        self._mark_parents(path)
        self.writes.append(path)

    def append_text(self, path, content):
        self.files[path] = self.files.get(path, "") + content
        self._mark_parents(path)
        self.appends.append(path)

    def path_exists(self, path):
        return path in self.files or path in self.dirs

    def remove(self, path):
        for k in list(self.files):
            if k == path or k.startswith(path + "/"):
                del self.files[k]
        self.dirs.discard(path)

    def makedirs(self, path):
        self.dirs.add(path)
        self._mark_parents(path)

    def listdir(self, path):
        path = path.rstrip("/")
        children = set()
        for k in list(self.files) + list(self.dirs):
            if k == path:
                continue
            if posixpath.dirname(k) == path:
                children.add(k)
        return sorted(children)

    # -- clock ----------------------------------------------------------
    def now(self):
        return self._clock

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._clock += seconds

    def advance(self, seconds):
        self._clock += seconds

    # -- commands ---------------------------------------------------------
    def script(self, predicate, proc: FakeProc):
        """Register a scripted response. `predicate(argv) -> bool`."""
        self.command_responses.append((predicate, proc))

    def script_prefix(self, *prefix, **proc_kwargs):
        self.script(lambda argv: list(argv[:len(prefix)]) == list(prefix), FakeProc(**proc_kwargs))

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return FakeProc(0, "", "")
