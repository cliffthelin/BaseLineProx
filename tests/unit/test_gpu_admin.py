"""Tests for gpu_admin.py (decision record 94) - real GPU detection plus
real, evidenced per-device mode compatibility. `_parse_lspci` is tested
against actual `lspci -Dmmnnk` output captured from a real machine (an
RTX 3070 + Tesla P40), not an idealized guess at the format - the exact
kind of gap that already caught one real regex bug (a greedy match
leaving a trailing space in `pci_class`) before this file existed.
conftest.py's autouse fixture isolates `registry.GLOBAL_DB_PATH` per
test, same as every other registry-backed module."""
import gpu_admin as ga


REAL_LSPCI_OUTPUT = (
    '0000:01:00.0 "VGA compatible controller [0300]" "NVIDIA Corporation [10de]" '
    '"GA104 [GeForce RTX 3070] [2484]" -ra1 -p00 "Gigabyte Technology Co., Ltd [1458]" "Device [404c]"\n'
    '0000:05:00.0 "3D controller [0302]" "NVIDIA Corporation [10de]" '
    '"GP102GL [Tesla P40] [1b38]" -ra1 -p00 "NVIDIA Corporation [10de]" "Device [11d9]"\n'
    '0000:00:14.0 "SMBus [0c05]" "Advanced Micro Devices, Inc. [AMD] [1022]" "FCH SMBus Controller [790b]" '
    '-r71 -p00 "ASUSTeK Computer Inc. [1043]" "Device [8877]"\n'
)

RTX_3070_ADDR = "0000:01:00.0"
P40_ADDR = "0000:05:00.0"


class FakeGpuRunner:
    def __init__(self, *, lspci_output=REAL_LSPCI_OUTPUT, paths=None, dirs=None,
                 realpaths=None, which_map=None, cat_files=None):
        self.lspci_output = lspci_output
        self.paths = paths or set()
        self.dirs = dirs or {}
        self.realpaths = realpaths or {}
        self.which_map = which_map or {}
        self.cat_files = cat_files or {}

    def run(self, argv, timeout=10):
        if argv[0] == "lspci":
            return ga.GpuProc(0, self.lspci_output, "")
        if argv[0] == "cat":
            path = argv[1]
            if path in self.cat_files:
                return ga.GpuProc(0, self.cat_files[path], "")
            return ga.GpuProc(1, "", "No such file or directory")
        raise AssertionError(f"unexpected command: {argv}")

    def path_exists(self, path):
        return path in self.paths

    def listdir(self, path):
        return self.dirs.get(path, [])

    def realpath(self, path):
        return self.realpaths.get(path, path)

    def which(self, name):
        return self.which_map.get(name)


def _real_machine_runner(**overrides):
    """Matches this session's own real detection output: two DRM render
    nodes, both bound to the `nvidia` driver, neither with mdev/sriov
    active right now, no NVIDIA Container Toolkit installed."""
    defaults = dict(
        paths={
            "/sys/class/drm",
            f"/sys/class/drm/renderD128/device", f"/sys/class/drm/renderD129/device",
            f"/sys/bus/pci/devices/{RTX_3070_ADDR}/driver",
            f"/sys/bus/pci/devices/{P40_ADDR}/driver",
        },
        dirs={"/sys/class/drm": ["renderD128", "renderD129", "card0", "card1", "by-path"]},
        realpaths={
            "/sys/class/drm/renderD128/device": f"/sys/devices/pci0000:00/.../{RTX_3070_ADDR}",
            "/sys/class/drm/renderD129/device": f"/sys/devices/pci0000:00/.../{P40_ADDR}",
            f"/sys/bus/pci/devices/{RTX_3070_ADDR}/driver": "/sys/bus/pci/drivers/nvidia",
            f"/sys/bus/pci/devices/{P40_ADDR}/driver": "/sys/bus/pci/drivers/nvidia",
        },
        which_map={},
    )
    defaults.update(overrides)
    return FakeGpuRunner(**defaults)


# -- _parse_lspci, against real captured output -----------------------

def test_parse_lspci_finds_only_gpu_class_devices():
    rows = ga._parse_lspci(REAL_LSPCI_OUTPUT)
    assert len(rows) == 2
    assert {r["addr"] for r in rows} == {RTX_3070_ADDR, P40_ADDR}


def test_parse_lspci_strips_no_trailing_whitespace_from_pci_class():
    rows = ga._parse_lspci(REAL_LSPCI_OUTPUT)
    row = next(r for r in rows if r["addr"] == RTX_3070_ADDR)
    assert row["pci_class"] == "VGA compatible controller"  # real bug once left a trailing space here


def test_parse_lspci_handles_a_model_name_with_its_own_bracketed_marketing_name():
    rows = ga._parse_lspci(REAL_LSPCI_OUTPUT)
    row = next(r for r in rows if r["addr"] == RTX_3070_ADDR)
    assert row["model"] == "GA104 [GeForce RTX 3070]"
    assert row["device_id"] == "2484"


def test_parse_lspci_gets_the_3d_controller_class_right_for_a_compute_only_card():
    rows = ga._parse_lspci(REAL_LSPCI_OUTPUT)
    row = next(r for r in rows if r["addr"] == P40_ADDR)
    assert row["pci_class"] == "3D controller"
    assert row["model"] == "GP102GL [Tesla P40]"


# -- detect_gpus --------------------------------------------------------

def test_detect_gpus_returns_both_real_devices_with_correct_pci_ids():
    runner = _real_machine_runner()
    devices = ga.detect_gpus(runner)
    assert {d.pci_id for d in devices} == {"10de:2484", "10de:1b38"}


def test_detect_gpus_finds_the_render_node_for_each_device():
    runner = _real_machine_runner()
    devices = {d.pci_address: d for d in ga.detect_gpus(runner)}
    assert devices[RTX_3070_ADDR].render_node == "/dev/dri/renderD128"
    assert devices[P40_ADDR].render_node == "/dev/dri/renderD129"


def test_detect_gpus_reports_no_render_node_when_none_maps_to_the_device():
    runner = _real_machine_runner(dirs={"/sys/class/drm": []})
    devices = ga.detect_gpus(runner)
    assert all(d.render_node is None for d in devices)


def test_detect_gpus_reports_the_kernel_driver_in_use():
    runner = _real_machine_runner()
    devices = {d.pci_address: d for d in ga.detect_gpus(runner)}
    assert devices[RTX_3070_ADDR].kernel_driver == "nvidia"


def test_detect_gpus_reports_none_driver_when_undriven():
    runner = _real_machine_runner(paths=set(), realpaths={})
    devices = ga.detect_gpus(runner)
    assert all(d.kernel_driver is None for d in devices)


def test_detect_gpus_returns_empty_when_lspci_fails():
    runner = FakeGpuRunner()
    runner.run = lambda argv, timeout=10: ga.GpuProc(1, "", "lspci not found")
    assert ga.detect_gpus(runner) == []


# -- available_modes: host_display ---------------------------------------

def test_host_display_available_for_a_vga_controller():
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.HOST_DISPLAY].available is True


def test_host_display_not_available_for_a_3d_controller_with_no_video_output():
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == P40_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.HOST_DISPLAY].available is False
    assert "no video output" in modes[ga.HOST_DISPLAY].evidence


# -- available_modes: vfio_passthrough ------------------------------------

def test_vfio_passthrough_always_available():
    runner = _real_machine_runner()
    for device in ga.detect_gpus(runner):
        modes = {m.mode: m for m in ga.available_modes(runner, device)}
        assert modes[ga.VFIO_PASSTHROUGH].available is True


# -- available_modes: vgpu_mdev_split - the two-kinds-of-evidence case ----

def test_mdev_split_active_now_when_sysfs_types_present():
    runner = _real_machine_runner(paths={f"/sys/bus/pci/devices/{P40_ADDR}/mdev_supported_types"},
                                   dirs={f"/sys/bus/pci/devices/{P40_ADDR}/mdev_supported_types": ["nvidia-63"]})
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == P40_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.VGPU_MDEV_SPLIT].available is True
    assert "active now" in modes[ga.VGPU_MDEV_SPLIT].evidence


def test_mdev_split_hardware_capable_but_not_active_for_known_id_p40():
    """The real, current state of this session's own Tesla P40: no
    mdev_supported_types directory yet (the vGPU-enabled driver isn't
    loaded), but the card's own PCI ID is a known, confirmed-capable
    one - two different kinds of evidence, not collapsed into one bit."""
    runner = _real_machine_runner()  # no mdev_supported_types path set
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == P40_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.VGPU_MDEV_SPLIT].available is True
    assert "not active right now" in modes[ga.VGPU_MDEV_SPLIT].evidence


def test_mdev_split_unavailable_for_a_consumer_card_not_in_the_known_list():
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.VGPU_MDEV_SPLIT].available is False
    assert "no known vGPU capability" in modes[ga.VGPU_MDEV_SPLIT].evidence


# -- available_modes: sriov -----------------------------------------------

def test_sriov_available_when_totalvfs_nonzero():
    path = f"/sys/bus/pci/devices/{P40_ADDR}/sriov_totalvfs"
    runner = _real_machine_runner(paths={path}, cat_files={path: "16\n"})
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == P40_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.SRIOV].available is True
    assert "16" in modes[ga.SRIOV].evidence


def test_sriov_unavailable_when_file_absent():
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == P40_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.SRIOV].available is False


# -- available_modes: virtio_gpu_shared -----------------------------------

def test_virtio_gpu_shared_available_when_render_node_present():
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.VIRTIO_GPU_SHARED].available is True


def test_virtio_gpu_shared_unavailable_with_no_render_node():
    runner = _real_machine_runner(dirs={"/sys/class/drm": []})
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.VIRTIO_GPU_SHARED].available is False


# -- available_modes: container_passthrough -------------------------------

def test_container_passthrough_unavailable_for_nvidia_without_the_toolkit_installed():
    """The real, current state of this machine: nvidia-smi is present
    but nvidia-ctk/nvidia-container-cli are not - container passthrough
    genuinely isn't usable yet even though the render node exists."""
    runner = _real_machine_runner()
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.CONTAINER_PASSTHROUGH].available is False
    assert "Toolkit" in modes[ga.CONTAINER_PASSTHROUGH].evidence


def test_container_passthrough_available_for_nvidia_with_the_toolkit_installed():
    runner = _real_machine_runner(which_map={"nvidia-ctk": "/usr/bin/nvidia-ctk"})
    device = next(d for d in ga.detect_gpus(runner) if d.pci_address == RTX_3070_ADDR)
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.CONTAINER_PASSTHROUGH].available is True


def test_container_passthrough_for_non_nvidia_needs_only_a_render_node():
    runner = _real_machine_runner(
        lspci_output='0000:10:00.0 "VGA compatible controller [0300]" "Advanced Micro Devices, Inc. [AMD] [1022]" '
                     '"Raphael [1002]" -ra1 -p00 "" ""\n',
        dirs={"/sys/class/drm": ["renderD130"]},
        paths={"/sys/class/drm", "/sys/class/drm/renderD130/device"},
        realpaths={"/sys/class/drm/renderD130/device": "/sys/devices/pci0000:00/.../0000:10:00.0"},
    )
    device = ga.detect_gpus(runner)[0]
    modes = {m.mode: m for m in ga.available_modes(runner, device)}
    assert modes[ga.CONTAINER_PASSTHROUGH].available is True


# -- registry persistence: sync/get/set/list ------------------------------

def test_sync_detected_gpus_registers_both_real_devices():
    runner = _real_machine_runner()
    devices = ga.sync_detected_gpus(runner)
    assert {d.pci_address for d in devices} == {RTX_3070_ADDR, P40_ADDR}


def test_get_gpu_mode_returns_none_when_never_set():
    runner = _real_machine_runner()
    ga.sync_detected_gpus(runner)
    assert ga.get_gpu_mode(RTX_3070_ADDR) is None


def test_set_gpu_mode_refuses_a_mode_not_available_for_this_device():
    runner = _real_machine_runner()
    ga.sync_detected_gpus(runner)
    try:
        ga.set_gpu_mode(RTX_3070_ADDR, ga.VGPU_MDEV_SPLIT)  # consumer card, genuinely can't
        assert False, "should have raised"
    except ValueError as exc:
        assert "cannot run in" in str(exc)


def test_set_gpu_mode_refuses_for_a_device_never_synced():
    try:
        ga.set_gpu_mode("0000:99:00.0", ga.HOST_DISPLAY)
        assert False, "should have raised"
    except KeyError:
        pass


def test_set_gpu_mode_accepts_a_real_available_mode_and_get_reflects_it():
    runner = _real_machine_runner()
    ga.sync_detected_gpus(runner)
    ga.set_gpu_mode(P40_ADDR, ga.VGPU_MDEV_SPLIT)  # hardware-capable per the known-ID seed
    assert ga.get_gpu_mode(P40_ADDR) == ga.VGPU_MDEV_SPLIT


def test_resyncing_never_clobbers_a_previously_chosen_mode():
    runner = _real_machine_runner()
    ga.sync_detected_gpus(runner)
    ga.set_gpu_mode(RTX_3070_ADDR, ga.VFIO_PASSTHROUGH)
    ga.sync_detected_gpus(runner)  # simulates a rescan / page reload
    assert ga.get_gpu_mode(RTX_3070_ADDR) == ga.VFIO_PASSTHROUGH


def test_list_gpus_with_modes_includes_current_mode_and_evidence():
    runner = _real_machine_runner()
    ga.sync_detected_gpus(runner)
    ga.set_gpu_mode(P40_ADDR, ga.VGPU_MDEV_SPLIT)
    listing = {g["pci_address"]: g for g in ga.list_gpus_with_modes(runner)}
    assert listing[P40_ADDR]["current_mode"] == ga.VGPU_MDEV_SPLIT
    assert listing[RTX_3070_ADDR]["current_mode"] is None
    assert any(m["mode"] == ga.HOST_DISPLAY for m in listing[RTX_3070_ADDR]["modes"])
