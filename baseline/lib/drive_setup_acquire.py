"""Boundary 1: artifact acquisition and verification (Milestone 1, §4).

Reproduces decision record 01's exact reproduced chain as real,
testable code: TLS-fetched keyring -> GPG-verified `Release` ->
hash-verified `Packages` index -> hash-verified `.deb`/ISO. No step
trusts an unauthenticated source; TLS is not the trust mechanism here
(decision record 01 found download.proxmox.com's cert doesn't match
its own hostname from this network path) - the GPG signature on
`Release` is what everything else chains from.

Every external call (network fetch, gpgv, dpkg-deb) goes through an
injectable Runner, exactly like repair.py's own pattern, so this whole
chain is unit-testable with FakeRunner - no real network, no real gpg
keyring, no real package extraction in tests.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


class AcquireRunner:
    """The injectable boundary for this module. Deliberately separate
    from repair.py's Runner - that one is scoped to text-based
    interfaces-file editing; this one is scoped to binary artifact
    fetch/verify/extract, a different domain with different needs
    (binary I/O, subprocess-based fetch/verify tools)."""

    def run(self, argv: list[str], timeout: float = 30) -> "AcquireProc":
        raise NotImplementedError

    def fetch(self, url: str, dest: Path, timeout: float = 30) -> "AcquireProc":
        """Fetch `url` to `dest`. Separate from run() because the real
        implementation may use a different mechanism (curl subprocess,
        or a Python HTTP client) than arbitrary command execution."""
        raise NotImplementedError

    def read_bytes(self, path: Path) -> bytes:
        raise NotImplementedError

    def write_bytes(self, path: Path, data: bytes) -> None:
        raise NotImplementedError

    def path_exists(self, path: Path) -> bool:
        raise NotImplementedError

    def makedirs(self, path: Path) -> None:
        raise NotImplementedError


@dataclass
class AcquireProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class RealAcquireRunner(AcquireRunner):
    def run(self, argv, timeout=30):
        import subprocess
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return AcquireProc(proc.returncode, proc.stdout, proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return AcquireProc(returncode=-1, stderr=str(exc))

    def fetch(self, url, dest, timeout=30):
        return self.run(["curl", "-sS", "-o", str(dest), url], timeout=timeout)

    def read_bytes(self, path):
        return Path(path).read_bytes()

    def write_bytes(self, path, data):
        Path(path).write_bytes(data)

    def path_exists(self, path):
        return Path(path).exists()

    def makedirs(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)


@dataclass
class VerifyStep:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class AcquireResult:
    ok: bool
    steps: list = field(default_factory=list)
    package_path: Path | None = None
    extracted_binary: Path | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_release_signature(runner: AcquireRunner, release_path: Path, sig_path: Path,
                              keyring_path: Path) -> VerifyStep:
    """gpgv is the trust anchor for the entire chain - never skipped,
    never replaced with a hash check of the keyring itself (a keyring
    isn't self-authenticating; TLS at fetch time is the only thing
    backing it, per decision record 01's own noted limitation)."""
    proc = runner.run(["gpgv", "--keyring", str(keyring_path), str(sig_path), str(release_path)])
    ok = proc.returncode == 0 and "Good signature" in proc.stderr
    detail = proc.stderr.strip() or proc.stdout.strip()
    return VerifyStep("release_gpg_signature", ok, detail)


_RELEASE_HASH_LINE = re.compile(r"^\s*([0-9a-f]{64})\s+\d+\s+(\S+)\s*$", re.MULTILINE)


def find_release_hash(release_text: str, relative_path: str) -> str | None:
    """Parse the SHA256: block of an APT Release file, return the hash
    pinned for `relative_path`, or None if not listed."""
    in_sha256_block = False
    for line in release_text.splitlines():
        if line.strip() == "SHA256:":
            in_sha256_block = True
            continue
        if in_sha256_block:
            if not line.startswith(" "):
                in_sha256_block = False
                continue
            m = re.match(r"^\s*([0-9a-f]{64})\s+(\d+)\s+(\S+)\s*$", line)
            if m and m.group(3) == relative_path:
                return m.group(1)
    return None


def verify_hash(runner: AcquireRunner, path: Path, expected_hex: str, name: str) -> VerifyStep:
    data = runner.read_bytes(path)
    actual = sha256_hex(data)
    ok = actual == expected_hex
    detail = "matches" if ok else f"expected {expected_hex}, got {actual}"
    return VerifyStep(name, ok, detail)


@dataclass
class PackageEntry:
    name: str
    version: str
    filename: str
    size: int
    sha256: str


def parse_packages_index(packages_text: str, package_name: str) -> list[PackageEntry]:
    """Debian control-file format: paragraphs separated by a blank
    line. Returns every entry matching `package_name` (there may be
    several versions), caller picks which one it wants."""
    entries = []
    for para in packages_text.split("\n\n"):
        fields = {}
        for line in para.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()
        if fields.get("Package") == package_name and "SHA256" in fields:
            entries.append(PackageEntry(
                name=fields["Package"],
                version=fields.get("Version", ""),
                filename=fields.get("Filename", ""),
                size=int(fields.get("Size", "0") or 0),
                sha256=fields["SHA256"],
            ))
    return entries


def acquire_and_verify(runner: AcquireRunner, workspace: Path, *,
                        keyring_url: str, release_url: str, release_gpg_url: str,
                        packages_url: str, packages_relative_path: str,
                        package_name: str, package_version: str,
                        mirror_base_url: str) -> AcquireResult:
    """The full reproduced chain from decision record 01, as one
    orchestrated, testable function. Every failure stops the chain
    immediately - a later step is never attempted on unverified input."""
    steps: list[VerifyStep] = []
    runner.makedirs(workspace)

    keyring_path = workspace / "keyring.gpg"
    release_path = workspace / "Release"
    release_gpg_path = workspace / "Release.gpg"
    packages_gz_path = workspace / "Packages.gz"
    deb_path = workspace / "package.deb"

    # 1: fetch keyring (TLS only, not itself the trust anchor)
    proc = runner.fetch(keyring_url, keyring_path)
    steps.append(VerifyStep("fetch_keyring", proc.returncode == 0, proc.stderr))
    if proc.returncode != 0:
        return AcquireResult(ok=False, steps=steps)

    # 2: fetch Release + Release.gpg
    proc = runner.fetch(release_url, release_path)
    steps.append(VerifyStep("fetch_release", proc.returncode == 0, proc.stderr))
    if proc.returncode != 0:
        return AcquireResult(ok=False, steps=steps)
    proc = runner.fetch(release_gpg_url, release_gpg_path)
    steps.append(VerifyStep("fetch_release_gpg", proc.returncode == 0, proc.stderr))
    if proc.returncode != 0:
        return AcquireResult(ok=False, steps=steps)

    # 3: verify GPG signature - the trust anchor
    sig_step = verify_release_signature(runner, release_path, release_gpg_path, keyring_path)
    steps.append(sig_step)
    if not sig_step.ok:
        return AcquireResult(ok=False, steps=steps)

    # 4: fetch Packages.gz, verify against Release's own pinned hash
    proc = runner.fetch(packages_url, packages_gz_path)
    steps.append(VerifyStep("fetch_packages", proc.returncode == 0, proc.stderr))
    if proc.returncode != 0:
        return AcquireResult(ok=False, steps=steps)

    release_text = runner.read_bytes(release_path).decode("utf-8", errors="replace")
    expected_packages_hash = find_release_hash(release_text, packages_relative_path)
    if expected_packages_hash is None:
        steps.append(VerifyStep("packages_hash_pinned_in_release", False,
                                 f"{packages_relative_path} not listed in Release's SHA256 block"))
        return AcquireResult(ok=False, steps=steps)

    hash_step = verify_hash(runner, packages_gz_path, expected_packages_hash, "packages_hash")
    steps.append(hash_step)
    if not hash_step.ok:
        return AcquireResult(ok=False, steps=steps)

    # 5: decompress and locate the package entry
    import gzip
    packages_text = gzip.decompress(runner.read_bytes(packages_gz_path)).decode("utf-8", errors="replace")
    entries = parse_packages_index(packages_text, package_name)
    match = next((e for e in entries if e.version == package_version), None)
    if match is None:
        steps.append(VerifyStep("package_entry_located", False,
                                 f"{package_name} {package_version} not found ({len(entries)} other version(s) present)"))
        return AcquireResult(ok=False, steps=steps)
    steps.append(VerifyStep("package_entry_located", True, f"{match.filename} sha256={match.sha256}"))

    # 6: fetch and verify the .deb itself
    deb_url = mirror_base_url.rstrip("/") + "/" + match.filename
    proc = runner.fetch(deb_url, deb_path)
    steps.append(VerifyStep("fetch_deb", proc.returncode == 0, proc.stderr))
    if proc.returncode != 0:
        return AcquireResult(ok=False, steps=steps)

    deb_hash_step = verify_hash(runner, deb_path, match.sha256, "deb_hash")
    steps.append(deb_hash_step)
    if not deb_hash_step.ok:
        return AcquireResult(ok=False, steps=steps)

    return AcquireResult(ok=True, steps=steps, package_path=deb_path)


def extract_deb(runner: AcquireRunner, deb_path: Path, extract_to: Path) -> VerifyStep:
    """dpkg-deb -x extracts without touching the host's own dpkg
    database - confirmed directly in decision record 01 (dpkg -l
    stays empty before/after)."""
    runner.makedirs(extract_to)
    proc = runner.run(["dpkg-deb", "-x", str(deb_path), str(extract_to)])
    return VerifyStep("extract_deb", proc.returncode == 0, proc.stderr)
