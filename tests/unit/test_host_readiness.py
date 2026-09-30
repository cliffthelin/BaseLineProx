"""Tests for host_readiness.py (hardened-appliance-prd.md, H1).
Pure: evaluate() takes a snapshot dict; collect() takes an injected reader."""
import host_readiness as hr

GOOD = {
    "cmdline": "BOOT_IMAGE=/vmlinuz root=/dev/x ro amd_iommu=on iommu=pt",
    "iommu_groups": 29,
    "gpus": [
        {"addr": "0000:01:00.0", "vendor": "10de", "driver": "vfio-pci", "group": 13},
        {"addr": "0000:05:00.0", "vendor": "10de", "driver": "vfio-pci", "group": 16},
        {"addr": "0000:0f:00.0", "vendor": "1002", "driver": "amdgpu", "group": 20},
    ],
    "tpm_version": "2",
    "secure_boot": True,
    "tools": {"tpm2_pcrextend": True, "cryptsetup": True, "systemd-cryptenroll": True},
}


def status(snap, check):
    return {f["id"]: f["status"] for f in hr.evaluate(snap)}[check]


def test_fully_ready_host_has_no_failures():
    assert not [f for f in hr.evaluate(GOOD) if f["status"] != "ok"]


def test_missing_iommu_cmdline_flags_warn_not_fail():
    snap = dict(GOOD, cmdline="ro quiet")
    assert status(snap, "iommu-cmdline") == "warn"


def test_no_iommu_groups_is_a_fail():
    assert status(dict(GOOD, iommu_groups=0), "iommu-groups") == "fail"


def test_missing_igpu_is_a_fail_with_bios_hint():
    snap = dict(GOOD, gpus=[g for g in GOOD["gpus"] if g["vendor"] != "1002"])
    f = {x["id"]: x for x in hr.evaluate(snap)}["igpu-present"]
    assert f["status"] == "fail" and "BIOS" in f["detail"]


def test_nvidia_on_host_driver_is_info_not_error_because_mode_is_operator_chosen():
    snap = dict(GOOD, gpus=[dict(g, driver="nvidia" if g["vendor"] == "10de" else g["driver"]) for g in GOOD["gpus"]])
    assert status(snap, "nvidia-host-driver") == "info"


def test_gpus_sharing_an_iommu_group_warn():
    gpus = [dict(g) for g in GOOD["gpus"]]
    gpus[1]["group"] = gpus[0]["group"]
    assert status(dict(GOOD, gpus=gpus), "gpu-group-isolation") == "warn"


def test_no_tpm_fails():
    assert status(dict(GOOD, tpm_version=None), "tpm2") == "fail"


def test_secure_boot_off_warns():
    assert status(dict(GOOD, secure_boot=False), "secure-boot") == "warn"


def test_missing_tools_are_reported_per_tool():
    snap = dict(GOOD, tools={"tpm2_pcrextend": False, "cryptsetup": True, "systemd-cryptenroll": True})
    assert status(snap, "tool-tpm2_pcrextend") == "warn"
    assert status(snap, "tool-cryptsetup") == "ok"


class FakeFs:
    def __init__(self, files, dirs, links=None):
        self.files, self.dirs, self.links = files, dirs, links or {}

    def read_text(self, p):
        if p not in self.files:
            raise FileNotFoundError(p)
        return self.files[p]

    def listdir(self, p):
        return self.dirs.get(p, [])

    def realpath(self, p):
        return self.links.get(p, p)

    def which(self, name):
        return "/usr/bin/" + name if name in ("cryptsetup",) else None


def test_collect_builds_snapshot_from_sysfs_like_reader():
    pci = "/sys/bus/pci/devices/0000:01:00.0"
    fs = FakeFs(
        files={
            "/proc/cmdline": "ro amd_iommu=on\n",
            f"{pci}/class": "0x030000\n",
            f"{pci}/vendor": "0x10de\n",
            "/sys/class/tpm/tpm0/tpm_version_major": "2\n",
        },
        dirs={
            "/sys/kernel/iommu_groups": ["0", "1", "2"],
            "/sys/bus/pci/devices": ["0000:01:00.0"],
        },
        links={f"{pci}/driver": "/sys/bus/pci/drivers/nvidia", f"{pci}/iommu_group": "/sys/kernel/iommu_groups/13"},
    )
    snap = hr.collect(fs)
    assert snap["iommu_groups"] == 3
    assert snap["tpm_version"] == "2"
    assert snap["gpus"] == [{"addr": "0000:01:00.0", "vendor": "10de", "driver": "nvidia", "group": 13}]
    assert snap["tools"]["cryptsetup"] is True and snap["tools"]["tpm2_pcrextend"] is False
