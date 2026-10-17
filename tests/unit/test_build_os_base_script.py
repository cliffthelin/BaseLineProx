"""The parts of baseline-build-os-base that do not boot anything: how the QEMU command lines are put together, and the guard that stops a stalled install."""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "baseline" / "bin" / "baseline-build-os-base"


@pytest.fixture(scope="module")
def builder():
    loader = importlib.machinery.SourceFileLoader("baseline_build_os_base", str(SCRIPT))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_every_listed_system_that_is_built_has_a_builder_and_the_rest_are_said_to_be_missing(builder):
    import os_build
    source = SCRIPT.read_text()
    for os_id in ("debian", "ubuntu", "nixos", "omarchy", "bazzite", "fydeos", "cachyos"):
        assert f'"{os_id}": build_{os_id}' in source and callable(getattr(builder, f"build_{os_id}"))
    assert "qubes" in os_build.METHODS and "build_qubes" not in source           # Qubes is deliberately not built


def test_the_base_command_line_boots_uefi_from_a_virtio_disk_with_nat_and_no_display(builder, tmp_path):
    argv = builder.qemu_base(tmp_path / "d.qcow2", memory_mb=8192, cpus=4, vars_file=tmp_path / "vars.fd")
    text = " ".join(argv)
    assert "-enable-kvm" in argv and "-m 8192" in text and "-smp 4" in text and "q35" in argv
    assert "OVMF_CODE_4M.fd" in text and f"file={tmp_path / 'vars.fd'}" in text and "virtio-net-pci" in text
    assert argv[argv.index("-display") + 1] == "none"


def test_the_installer_image_is_first_in_the_boot_order_with_the_disk_after_it(builder, tmp_path):
    argv = builder.installer_boot_drives(tmp_path / "d.qcow2", tmp_path / "os.iso", [tmp_path / "cidata.iso"])
    text = " ".join(argv)
    assert "ide-cd,drive=cd0,bootindex=1" in text and "drive=hd0,bootindex=2" in text and f"file={tmp_path / 'cidata.iso'},media=cdrom" in text


def test_a_run_that_stops_growing_its_disk_is_stopped_with_the_reason(builder, tmp_path, monkeypatch):
    import os_build
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"x" * 10)
    killed = []

    class Done:
        def __init__(self, *a, **k):
            (tmp_path / "vm.pid").write_text("4242")

    def fake_run(argv, *a, **k):
        if argv[0] == "kill":
            killed.append(argv[1])
        else:
            (tmp_path / "vm.pid").write_text("4242")
        return Done()
    clock = {"t": 0.0}
    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    monkeypatch.setattr(builder.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(builder.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + 600))
    monkeypatch.setattr(builder, "Path", Path)
    monkeypatch.setattr(Path, "stat", lambda self, *a, **k: type("S", (), {"st_size": 10, "st_mode": 0o100644})())
    with pytest.raises(os_build.BuildError, match="stopped making progress"):
        builder.run_until_exit(["qemu"], tmp_path, disk, timeout=10 ** 9)
    assert killed == ["4242"]
