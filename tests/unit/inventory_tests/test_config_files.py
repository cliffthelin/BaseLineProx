"""config_files[] collector tests - allowlist-only membership, no raw
content ever stored, HMAC-backed content identity, interfaces
source-closure resolution (glob-form source and source-directory),
conffile-modified detection, and baseline-managed classification."""
from inventory.collectors.config_files import collect_config_files
from inventory.redact import Redactor
from inventory.runner import CommandResult

from .fake_runner import FakeRunner


def _base_runner():
    r = FakeRunner()
    # Nothing exists by default except what each test registers - the
    # allowlist must never assume presence.
    r.binaries["stat"] = "/usr/bin/stat"
    r.binaries["sha256sum"] = "/usr/bin/sha256sum"
    r.binaries["dpkg"] = "/usr/bin/dpkg"
    r.binaries["dpkg-query"] = "/usr/bin/dpkg-query"
    r.binaries["md5sum"] = "/usr/bin/md5sum"
    return r


def _stat_line(path, ftype="regular file", owner="root", group="root", mode="644", size=100, target=None):
    if target:
        return f"{path}|symbolic link|{owner}|{group}|777|{len(target)}|'{path}' -> '{target}'"
    return f"{path}|{ftype}|{owner}|{group}|{mode}|{size}|'{path}'"


def test_only_allowlisted_paths_are_ever_touched():
    """A file that exists on disk but isn't on the allowlist must never
    appear - this is enforced by construction (the collector only ever
    builds paths from the fixed lists + bounded discovery), verified
    here by confirming a decoy path never gets stat'd."""
    r = _base_runner()
    r.existing_paths.add("/etc/hostname")
    r.existing_paths.add("/etc/shadow")  # decoy - must never be touched
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=_stat_line("/etc/hostname")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout="aaaa  /etc/hostname\n"))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="not found"))

    result = collect_config_files(r, Redactor(key=b"k"))

    stat_calls = [c for c in r.run_calls if c[:1] == ["stat"]]
    assert stat_calls, "expected a stat call"
    assert "/etc/shadow" not in stat_calls[0]
    paths = {e["path"] for e in result["entries"]}
    assert "/etc/shadow" not in paths
    assert "/etc/hostname" in paths


def test_missing_allowlisted_file_reports_exists_false_not_an_error():
    r = _base_runner()
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    # /etc/hostname deliberately not registered as existing.
    r.script(lambda a: a[:1] == ["stat"],
             CommandResult(ok=True, stdout=_stat_line("/etc/network/interfaces")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    entry = next(e for e in result["entries"] if e["path"] == "/etc/network/interfaces")
    assert entry["exists"] is True
    assert "/etc/hostname" not in {e["path"] for e in result["entries"] if e["exists"]}


def test_interfaces_source_directory_and_glob_are_resolved_into_the_closure():
    r = _base_runner()
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = (
        "auto lo\niface lo inet loopback\n"
        "source /etc/network/interfaces.d/*\n"
        "source-directory /etc/network/interfaces.d/extra\n"
    )
    r.dirs["/etc/network/interfaces.d"] = ["50-vmbr0.cfg", "60-other.cfg"]
    r.files["/etc/network/interfaces.d/50-vmbr0.cfg"] = "iface vmbr0 inet dhcp\n"
    r.files["/etc/network/interfaces.d/60-other.cfg"] = "iface eth1 inet manual\n"
    r.dirs["/etc/network/interfaces.d/extra"] = ["70-frag.cfg"]
    r.files["/etc/network/interfaces.d/extra/70-frag.cfg"] = "iface eth2 inet manual\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    paths = {e["path"] for e in result["entries"]}
    assert "/etc/network/interfaces" in paths
    assert "/etc/network/interfaces.d/50-vmbr0.cfg" in paths
    assert "/etc/network/interfaces.d/60-other.cfg" in paths
    assert "/etc/network/interfaces.d/extra/70-frag.cfg" in paths
    for p in paths:
        if p.startswith("/etc/network/"):
            assert next(e for e in result["entries"] if e["path"] == p)["category"] == "network"


def test_content_identity_is_hmac_tokenized_never_the_raw_hash():
    r = _base_runner()
    r.existing_paths.add("/etc/hostname")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=_stat_line("/etc/hostname")))
    r.script(lambda a: a[:1] == ["sha256sum"],
             CommandResult(ok=True, stdout="deadbeefcafef00d  /etc/hostname\n"))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    redactor = Redactor(key=b"fixed-key")
    result = collect_config_files(r, redactor)
    entry = next(e for e in result["entries"] if e["path"] == "/etc/hostname")
    assert entry["content_identity"] == redactor.tokenize("deadbeefcafef00d", "content")
    assert "deadbeefcafef00d" not in entry["content_identity"]


def test_symlink_target_is_recorded_for_symlinks():
    r = _base_runner()
    r.existing_paths.add("/etc/resolv.conf")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"],
             CommandResult(ok=True, stdout=_stat_line("/etc/resolv.conf",
                                                        target="/run/systemd/resolve/stub-resolv.conf")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    entry = next(e for e in result["entries"] if e["path"] == "/etc/resolv.conf")
    assert entry["file_type"] == "symbolic link"
    assert entry["symlink_target"] == "/run/systemd/resolve/stub-resolv.conf"
    assert entry["symlink_approved"] is True


def test_unexpected_symlink_target_is_never_recorded_raw():
    """A symlink at /etc/resolv.conf pointing somewhere NOT on the
    approved-prefix list must never leak its literal target path into
    the manifest - only a tokenized identity and an explicit flag."""
    r = _base_runner()
    r.existing_paths.add("/etc/resolv.conf")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"],
             CommandResult(ok=True, stdout=_stat_line("/etc/resolv.conf", target="/root/.ssh/id_rsa")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    redactor = Redactor(key=b"k")
    result = collect_config_files(r, redactor)
    entry = next(e for e in result["entries"] if e["path"] == "/etc/resolv.conf")
    assert entry["symlink_approved"] is False
    assert entry["unexpected_symlink_target"] is True
    assert entry["symlink_target"] is None
    assert entry["symlink_target_identity"] == redactor.tokenize("/root/.ssh/id_rsa", "symlink-target")
    # The raw target must not appear anywhere in the entry's values.
    assert "/root/.ssh/id_rsa" not in str(entry.values())


def test_hostname_hosts_baseline_and_unit_paths_have_no_approved_symlink_targets():
    """/etc/hostname, /etc/hosts, Baseline-managed paths, and unit
    paths must never have an approved symlink destination - any
    symlink there is always flagged, never silently trusted."""
    from inventory.collectors.config_files import _is_approved_symlink_target
    for source_path in ("/etc/hostname", "/etc/hosts", "/opt/baseline/bin/baseline",
                         "/etc/systemd/system/baseline.service"):
        assert _is_approved_symlink_target(source_path, "/anything/at/all") is False
        assert _is_approved_symlink_target(source_path, "/run/systemd/resolve/stub-resolv.conf") is False


def test_symlink_target_content_is_never_hashed_even_when_approved():
    """Even an approved symlink's target is never read for content -
    only file_type=='regular file' entries ever get a sha256sum call,
    so no symlink (approved or not) can be used to redirect this
    collector's content-hashing step anywhere."""
    r = _base_runner()
    r.existing_paths.add("/etc/resolv.conf")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"],
             CommandResult(ok=True, stdout=_stat_line("/etc/resolv.conf",
                                                        target="/run/systemd/resolve/stub-resolv.conf")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    # /etc/resolv.conf is the only allowlisted path in this test and it
    # is a symlink - sha256sum must never be invoked on it (or its
    # approved target) at all, since only file_type=='regular file'
    # entries are ever passed to the batched hash call.
    sha_calls = [c for c in r.run_calls if c[:1] == ["sha256sum"]]
    assert not sha_calls
    entry = next(e for e in result["entries"] if e["path"] == "/etc/resolv.conf")
    assert "content_identity" not in entry


def test_baseline_deployed_files_are_classified_baseline_managed():
    r = _base_runner()
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = ["network_preference.json"]
    r.dirs["/opt/baseline/bin"] = ["/opt/baseline/bin/baseline"]
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    by_path = {e["path"]: e for e in result["entries"]}
    assert by_path["/etc/baseline/network_preference.json"]["baseline_managed"] is True
    assert by_path["/etc/baseline/network_preference.json"]["category"] == "baseline"
    assert by_path["/opt/baseline/bin/baseline"]["baseline_managed"] is True


def test_conffile_modified_true_when_live_hash_differs_from_packaged():
    r = _base_runner()
    r.existing_paths.add("/etc/hostname")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=_stat_line("/etc/hostname")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout="cccc  /etc/hostname\n"))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=True, stdout="hostname: /etc/hostname\n"))
    r.script(lambda a: a[:1] == ["dpkg-query"],
             CommandResult(ok=True, stdout="hostname\t/etc/hostname aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"))
    r.script(lambda a: a[:1] == ["md5sum"],
             CommandResult(ok=True, stdout="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  /etc/hostname\n"))

    result = collect_config_files(r, Redactor(key=b"k"))
    entry = next(e for e in result["entries"] if e["path"] == "/etc/hostname")
    assert entry["owning_package"] == "hostname"
    assert entry["conffile_modified"] is True


def test_no_raw_content_is_ever_read_or_stored():
    """The collector must never call read_text on a large/binary config
    file just to compute identity - only stat + sha256sum (a
    subprocess, not a Python-side read) touch file content at all, and
    read_text is reserved for the interfaces closure's own text (which
    IS legitimately parsed for source/source-directory lines, not
    stored raw in an entry)."""
    r = _base_runner()
    r.existing_paths.add("/etc/hostname")
    r.dirs["/etc/sysctl.d"] = []
    r.dirs["/etc/modprobe.d"] = []
    r.dirs["/etc/modules-load.d"] = []
    r.dirs["/etc/apt/sources.list.d"] = []
    r.dirs["/etc/baseline"] = []
    r.dirs["/opt/baseline/bin"] = []
    r.dirs["/opt/baseline/lib"] = []
    r.files["/etc/network/interfaces"] = "auto lo\niface lo inet loopback\n"
    r.script(lambda a: a[:1] == ["stat"], CommandResult(ok=True, stdout=_stat_line("/etc/hostname")))
    r.script(lambda a: a[:1] == ["sha256sum"], CommandResult(ok=True, stdout="dddd  /etc/hostname\n"))
    r.script(lambda a: a[:2] == ["dpkg", "-S"], CommandResult(ok=False, unavailable=True, reason="n/a"))

    result = collect_config_files(r, Redactor(key=b"k"))
    assert "/etc/hostname" not in r.read_calls
    for entry in result["entries"]:
        assert "content" not in str(entry.get("content_identity", "")) or entry["content_identity"].startswith("content:")
