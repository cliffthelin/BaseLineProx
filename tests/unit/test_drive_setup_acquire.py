"""Unit tests for drive_setup_acquire.py - reproduces decision record
01's GPG -> hash -> hash chain as testable assertions. All
FakeAcquireRunner-scripted, no real network/gpg/dpkg-deb calls."""
import gzip
from pathlib import Path

import drive_setup_acquire as acquire
from drive_setup_acquire import AcquireProc, AcquireRunner


class FakeAcquireRunner(AcquireRunner):
    def __init__(self):
        self.files = {}
        self.fetch_responses = {}  # url -> (AcquireProc, bytes|None)
        self.command_responses = []  # (predicate, AcquireProc)
        self.calls = []
        self.fetch_calls = []

    def script_fetch(self, url, proc: AcquireProc, content: bytes = b""):
        self.fetch_responses[url] = (proc, content)

    def script_command(self, predicate, proc: AcquireProc):
        self.command_responses.append((predicate, proc))

    def run(self, argv, timeout=30):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return AcquireProc(0, "", "")

    def fetch(self, url, dest, timeout=30):
        self.fetch_calls.append(url)
        proc, content = self.fetch_responses.get(url, (AcquireProc(1, "", "404 not found"), None))
        if proc.returncode == 0 and content is not None:
            self.files[str(dest)] = content
        return proc

    def read_bytes(self, path):
        return self.files[str(path)]

    def write_bytes(self, path, data):
        self.files[str(path)] = data

    def path_exists(self, path):
        return str(path) in self.files

    def makedirs(self, path):
        pass


RELEASE_TEXT = """Origin: Proxmox
Suite: trixie
SHA256:
 70e0d43d0c53d7bfbbe29fb7a172f94384d0f5d12f1fd2d3311a43e3d349d979 12345 pve-no-subscription/binary-amd64/Packages
 2deff25830139e3450672b2efea7b4d7be98dbb2182134d48e542841341fdb 6789 pve-no-subscription/binary-amd64/Packages.gz
"""

PACKAGES_TEXT = """Package: proxmox-auto-install-assistant
Version: 9.2.8
Architecture: amd64
Filename: dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.2.8_amd64.deb
Size: 1074452
SHA256: 94b562ac026bf9a989e0a5834538ad24e38606f8858367af0e665af0bcbdc2e2

Package: proxmox-auto-install-assistant
Version: 9.0.6
Architecture: amd64
Filename: dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.0.6_amd64.deb
Size: 1000000
SHA256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""


def _make_full_chain_runner(deb_bytes=b"fake deb contents", deb_hash_override=None,
                             sig_ok=True, packages_hash_override=None):
    r = FakeAcquireRunner()

    deb_hash = deb_hash_override or acquire.sha256_hex(deb_bytes)
    packages_text = PACKAGES_TEXT.replace(
        "SHA256: 94b562ac026bf9a989e0a5834538ad24e38606f8858367af0e665af0bcbdc2e2",
        f"SHA256: {deb_hash}",
    )
    packages_gz = gzip.compress(packages_text.encode())
    packages_gz_hash = packages_hash_override or acquire.sha256_hex(packages_gz)
    release_text = f"""Origin: Proxmox
Suite: trixie
SHA256:
 70e0d43d0c53d7bfbbe29fb7a172f94384d0f5d12f1fd2d3311a43e3d349d979 12345 pve-no-subscription/binary-amd64/Packages
 {packages_gz_hash} 6789 pve-no-subscription/binary-amd64/Packages.gz
"""

    r.script_fetch("https://example.invalid/keyring.gpg", AcquireProc(0, "", ""), b"fake keyring bytes")
    r.script_fetch("http://example.invalid/Release", AcquireProc(0, "", ""), release_text.encode())
    r.script_fetch("http://example.invalid/Release.gpg", AcquireProc(0, "", ""), b"fake sig bytes")
    r.script_fetch("http://example.invalid/Packages.gz", AcquireProc(0, "", ""), packages_gz)
    r.script_fetch(
        "http://example.invalid/dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.2.8_amd64.deb",
        AcquireProc(0, "", ""), deb_bytes,
    )

    sig_proc = AcquireProc(0, "", "gpgv: Good signature from ...") if sig_ok else \
        AcquireProc(1, "", "gpgv: BAD signature")
    r.script_command(lambda a: a[:1] == ["gpgv"], sig_proc)
    return r


def test_full_chain_succeeds_with_matching_hashes():
    r = _make_full_chain_runner()
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="9.2.8",
        mirror_base_url="http://example.invalid",
    )
    assert result.ok
    assert result.package_path is not None
    assert all(s.ok for s in result.steps)


def test_chain_stops_at_bad_gpg_signature():
    r = _make_full_chain_runner(sig_ok=False)
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="9.2.8",
        mirror_base_url="http://example.invalid",
    )
    assert not result.ok
    # Must never have fetched Packages.gz after a failed signature check.
    assert "http://example.invalid/Packages.gz" not in r.fetch_calls


def test_chain_stops_when_packages_hash_does_not_match_release():
    r = _make_full_chain_runner(packages_hash_override="0" * 64)
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="9.2.8",
        mirror_base_url="http://example.invalid",
    )
    assert not result.ok
    failed = [s for s in result.steps if s.name == "packages_hash" and not s.ok]
    assert len(failed) == 1
    # Never proceeded to fetch the .deb on unverified Packages content.
    assert not any("assistant_9.2.8" in u for u in r.fetch_calls)


def test_chain_stops_when_deb_hash_does_not_match_packages_index():
    # Fetch a .deb whose real bytes don't match the hash the (verified)
    # Packages index says it should have - simulating a tampered or
    # corrupted download.
    r = _make_full_chain_runner()
    # Overwrite the scripted .deb fetch with different content but keep
    # the Packages index (and its hash) referring to the original.
    r.fetch_responses["http://example.invalid/dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.2.8_amd64.deb"] = (
        AcquireProc(0, "", ""), b"TAMPERED CONTENT",
    )
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="9.2.8",
        mirror_base_url="http://example.invalid",
    )
    assert not result.ok
    failed = [s for s in result.steps if s.name == "deb_hash" and not s.ok]
    assert len(failed) == 1


def test_chain_stops_when_requested_version_not_in_index():
    r = _make_full_chain_runner()
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="99.99.99",
        mirror_base_url="http://example.invalid",
    )
    assert not result.ok
    failed = [s for s in result.steps if s.name == "package_entry_located" and not s.ok]
    assert len(failed) == 1


def test_chain_stops_on_network_failure_at_any_step():
    r = FakeAcquireRunner()  # nothing scripted - every fetch fails
    result = acquire.acquire_and_verify(
        r, Path("/ws"),
        keyring_url="https://example.invalid/keyring.gpg",
        release_url="http://example.invalid/Release",
        release_gpg_url="http://example.invalid/Release.gpg",
        packages_url="http://example.invalid/Packages.gz",
        packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
        package_name="proxmox-auto-install-assistant",
        package_version="9.2.8",
        mirror_base_url="http://example.invalid",
    )
    assert not result.ok
    assert result.steps[0].name == "fetch_keyring"
    assert not result.steps[0].ok


def test_parse_packages_index_returns_all_matching_versions():
    entries = acquire.parse_packages_index(PACKAGES_TEXT, "proxmox-auto-install-assistant")
    assert len(entries) == 2
    versions = {e.version for e in entries}
    assert versions == {"9.2.8", "9.0.6"}


def test_find_release_hash_locates_pinned_hash():
    h = acquire.find_release_hash(RELEASE_TEXT, "pve-no-subscription/binary-amd64/Packages")
    assert h == "70e0d43d0c53d7bfbbe29fb7a172f94384d0f5d12f1fd2d3311a43e3d349d979"


def test_find_release_hash_returns_none_for_unlisted_path():
    h = acquire.find_release_hash(RELEASE_TEXT, "some/other/path")
    assert h is None


def test_extract_deb_never_touches_host_dpkg_database():
    r = FakeAcquireRunner()
    r.script_command(lambda a: a[:1] == ["dpkg-deb"], AcquireProc(0, "", ""))
    step = acquire.extract_deb(r, Path("/ws/package.deb"), Path("/ws/extracted"))
    assert step.ok
    assert r.calls == [["dpkg-deb", "-x", "/ws/package.deb", "/ws/extracted"]]
    # No apt/dpkg -i / install-style command was ever issued.
    assert not any("install" in " ".join(c) for c in r.calls)


def test_extract_deb_reports_failure():
    r = FakeAcquireRunner()
    r.script_command(lambda a: a[:1] == ["dpkg-deb"], AcquireProc(2, "", "dpkg-deb: error: corrupt archive"))
    step = acquire.extract_deb(r, Path("/ws/package.deb"), Path("/ws/extracted"))
    assert not step.ok
    assert "corrupt archive" in step.detail
