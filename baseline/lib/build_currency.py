"""Whether a drive already carries the build that is about to be installed, so an install that has nothing new to apply is skipped instead of wiping the drive.

The build is the tracked source the installer carries (`baseline/` and `boot/`), identified by its git tree hashes at HEAD. Uncommitted edits to those paths count as a different build, since
the installer would carry them. At install time the build is recorded in the run's journal beside the drive's other facts; the next run compares what it is about to carry with that record.
A drive with no record (installed before this existed) is never assumed current. Every command here is a read.
"""
from __future__ import annotations

CARRIED = ("baseline", "boot")


class BuildError(RuntimeError):
    pass


def source_state(runner, repo) -> dict:
    """{"trees": {path: tree hash at HEAD}, "dirty": [changed paths]} for the carried source; raises BuildError when it cannot be read."""
    trees = {}
    for path in CARRIED:
        proc = runner.run(["git", "-C", str(repo), "rev-parse", f"HEAD:{path}"], timeout=30)
        sha = (proc.stdout or "").strip()
        if proc.returncode or len(sha) < 40:
            raise BuildError(f"the build's source ({path}) could not be identified")
        trees[path] = sha
    status = runner.run(["git", "-C", str(repo), "status", "--porcelain", "--", *CARRIED], timeout=60)
    if status.returncode:
        raise BuildError("the build's source could not be checked for uncommitted changes")
    dirty = sorted({line[3:].strip() for line in (status.stdout or "").splitlines() if line.strip()})
    return {"trees": trees, "dirty": dirty}


def assess(recorded, current: dict) -> dict:
    """What an install should do: {"action": "skip" | "install", "reason": ...}. Only an exact match of a recorded build with a clean current one skips."""
    if current.get("dirty"):
        return {"action": "install", "reason": f"the source has uncommitted changes ({len(current['dirty'])} files), so this is not a build that was installed before"}
    if not isinstance(recorded, dict) or not isinstance(recorded.get("trees"), dict):
        return {"action": "install", "reason": "this drive has no record of which build it carries"}
    if recorded["trees"] == current["trees"]:
        return {"action": "skip", "reason": "the drive already carries this exact build"}
    changed = sorted(p for p in current["trees"] if recorded["trees"].get(p) != current["trees"][p])
    return {"action": "install", "reason": "the build changed since this drive was installed (" + ", ".join(changed) + ")"}
