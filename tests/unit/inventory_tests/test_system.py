from inventory.runner import CommandResult
from inventory.collectors import system

from .fake_runner import FakeRunner


def test_conffiles_queried_in_one_batched_pass_not_per_package():
    r = FakeRunner()
    r.binaries.update({"dpkg-query": "/usr/bin/dpkg-query", "apt-mark": "/usr/bin/apt-mark", "dpkg": "/usr/bin/dpkg"})

    def dpkg_query_handler(argv):
        joined = " ".join(argv)
        if "Conffiles" in joined:
            return CommandResult(ok=True, stdout="pkg-a\t/etc/pkg-a.conf abc\npkg-b\t/etc/pkg-b.conf def\n")
        return CommandResult(ok=True, stdout="pkg-a\t1.0\tinstall ok installed\npkg-b\t2.0\tinstall ok installed\n")

    r.script(lambda a: a[0] == "dpkg-query", dpkg_query_handler)
    r.script(lambda a: a[0] == "apt-mark", CommandResult(ok=True, stdout=""))
    r.script(lambda a: a[0] == "dpkg" and "--print-architecture" in a, CommandResult(ok=True, stdout="amd64\n"))
    r.script(lambda a: a[0] == "dpkg" and "--print-foreign-architectures" in a, CommandResult(ok=True, stdout=""))

    result = system.collect_packages(r)

    dpkg_query_calls = [c for c in r.run_calls if c[0] == "dpkg-query"]
    assert len(dpkg_query_calls) == 2  # package listing + one batched Conffiles pass
    assert result["conffile_state_by_package"] == {
        "pkg-a": "/etc/pkg-a.conf abc",
        "pkg-b": "/etc/pkg-b.conf def",
    }
    assert result["architecture"] == "amd64"


def test_firmware_drivers_drops_serials_keeps_allowlisted_bios_fields():
    r = FakeRunner()
    r.binaries.update({"lsmod": "/sbin/lsmod", "lspci": "/usr/bin/lspci", "dmidecode": "/usr/sbin/dmidecode"})
    r.script(lambda a: a[0] == "lsmod", CommandResult(ok=True, stdout="module_a 1234 0\n"))
    r.script(lambda a: a[0] == "lspci", CommandResult(ok=True, stdout="pci binding text\n"))
    r.script(
        lambda a: a == ["dmidecode", "-t", "bios"],
        CommandResult(ok=True, stdout="Vendor: Dell Inc.\nVersion: 1.2.3\nRelease Date: 01/01/2026\n"),
    )
    r.script(
        lambda a: a == ["dmidecode", "-t", "system"],
        CommandResult(ok=True, stdout="Manufacturer: Dell Inc.\nProduct Name: Latitude 5290\n"
                                       "Serial Number: SUPERSECRETSERIAL123\nUUID: 11111111-2222-3333-4444-555555555555\n"),
    )
    result = system.collect_firmware_drivers(r)
    assert result["bios_summary"]["bios_vendor"] == "Dell Inc."
    assert result["bios_summary"]["system_product"] == "Latitude 5290"
    assert "SUPERSECRETSERIAL123" not in str(result)
    assert "11111111-2222-3333-4444-555555555555" not in str(result)


def test_missing_tool_is_unavailable_not_an_exception():
    r = FakeRunner()  # nothing registered in r.binaries at all
    result = system.collect_platform_versions(r)
    assert result["kernel"] is None
    assert result["proxmox"] is None
    assert result["debian"] is None
    # Missing-tool state must be visibly reported, not just a silent None
    # (pre-run-safeguard requirement) - every field here failed for the
    # same reason (nothing on PATH / nothing at that path).
    assert len(result["_collection_notes"]) == 3
    assert all(n["status"] == "unavailable" for n in result["_collection_notes"])
