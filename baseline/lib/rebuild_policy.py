"""The standing policy a rebuild service obeys: which exact command may run as root, for which drives, and what it is allowed to be.

A rebuild never formats: the command is the in-place rebuild (data backed up and versioned, code updated). Wiping a drive is a different act with its own typed confirmation and is not in the policy. Nothing outside the policy can run. The policy names ONE command shape (argv template, with {src} {target} {serial} the only fill-ins) and the drives it may be pointed at, each by an
identity hash of the drive's own facts (serial and size) rather than by a name or a person. The source it runs is NOT pinned here: each request pins the exact commit it was made at (shown to the person who approves it), so work can continue right up to the moment of approval. The whole policy is itself
held by a SHA-256 in a second root-owned file, so a partial edit of either is detected and the service stops. It is written only by the setup run as root; it is not tied to any account:
who may send requests is a group the person setting it up names.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_ARGV = ["{python}", "{src}/baseline/bin/baseline-rebuild-drive", "--serial", "{serial}"]
MAX_TTL_HOURS = 24 * 7
DEFAULT_TTL_HOURS = 24


class PolicyError(RuntimeError):
    pass


def drive_identity(serial: str, size_bytes: int) -> str:
    """A drive's identity as the policy holds it: a hash of its serial and size, so the policy file carries no serial."""
    return hashlib.sha256(f"baseline-rebuild-drive-v1:{serial}:{int(size_bytes)}".encode()).hexdigest()


def source_digest(src) -> str:
    base, digest = Path(src), hashlib.sha256()
    for folder in ("baseline/lib", "baseline/bin", "boot"):
        for path in sorted((base / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(base)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def canonical(policy: dict) -> bytes:
    return json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()


def policy_digest(policy: dict) -> str:
    return hashlib.sha256(canonical(policy)).hexdigest()


def build(drives: dict, *, ttl_hours: int = DEFAULT_TTL_HOURS, argv=None) -> dict:
    """`drives` is {name: identity hash}."""
    if not drives:
        raise PolicyError("a policy needs at least one drive")
    if not 1 <= ttl_hours <= MAX_TTL_HOURS:
        raise PolicyError(f"approval time is between 1 and {MAX_TTL_HOURS} hours")
    return {"version": 1, "argv": list(argv or DEFAULT_ARGV), "drives": dict(drives), "max_approval_hours": ttl_hours}


def write(path, digest_path, policy: dict):
    Path(path).write_bytes(canonical(policy) + b"\n")
    Path(digest_path).write_text(policy_digest(policy) + "\n")


def load_verified(path, digest_path) -> dict:
    try:
        policy = json.loads(Path(path).read_text())
        recorded = Path(digest_path).read_text().strip()
    except (OSError, ValueError) as exc:
        raise PolicyError(f"the rebuild policy could not be read: {exc}") from None
    if policy_digest(policy) != recorded:
        raise PolicyError("the rebuild policy does not match its recorded SHA-256; nothing will run")
    return policy


def command_for(policy: dict, *, target: str, serial: str, size_bytes: int, src: str, python: str, current_source: str, approved_source: str) -> list:
    """The one command the policy allows for `target`, after checking the live drive against the drive's pinned identity and the source against the digest the request was approved at."""
    pinned = policy["drives"].get(target)
    if pinned is None:
        raise PolicyError(f"{target} is not a drive this policy covers")
    if drive_identity(serial, size_bytes) != pinned:
        raise PolicyError(f"the drive attached as {target} is not the one the policy was made for")
    if current_source != approved_source:
        raise PolicyError("the source to run is not the one that was approved with the request")
    fills = {"python": python, "src": src, "target": target, "serial": serial}
    out = []
    for word in policy["argv"]:
        for key, value in fills.items():
            word = word.replace("{" + key + "}", value)
        out.append(word)
    return out
