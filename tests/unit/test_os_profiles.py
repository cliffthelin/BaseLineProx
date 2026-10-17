"""How each supported OS is created as a VM from its carried image: sizes, firmware, and honest refusals (DR262)."""
import os_profiles as op


def entry(ident, iso="x.iso"):
    return {"id": ident, "name": ident.title(), "kind": "vm", "iso": iso, "apps": [], "notes": ""}


def test_a_carried_image_gets_a_stopped_uefi_plan_with_the_systems_own_sizes():
    got = op.plan_for(entry("bazzite", "bazzite-stable-amd64.iso"), image_carried=True, host_mb=65536)
    assert got == {"plan": {"name": "bazzite", "iso": "bazzite-stable-amd64.iso", "disk_gb": 80, "memory_mb": 8192, "cpus": 4, "firmware": "uefi"}}
    assert op.plan_for(entry("debian"), image_carried=True)["plan"]["memory_mb"] == 4096          # no host figure: nothing is cut down


def test_an_unknown_system_gets_the_default_sizes_not_a_refusal():
    assert op.plan_for(entry("somenewos"), image_carried=True)["plan"]["disk_gb"] == 32


def test_qubes_is_refused_with_the_reason_even_when_its_image_is_carried():
    got = op.plan_for(entry("qubes", "Qubes-R4.3.2-x86_64.iso"), image_carried=True)
    assert "plan" not in got and "Xen" in got["blocked"]


def test_fydeos_is_refused_because_its_desktop_needs_an_intel_gpu_even_when_its_base_is_carried():
    for kwargs in ({"image_carried": True}, {"image_carried": True, "base_carried": True}):
        got = op.plan_for(entry("fydeos", "FydeOS-VMWare-v23.0-Preview2-x86_64-io.ova"), **kwargs)
        assert "Intel GPU" in got["blocked"] and "plan" not in got


def test_an_ova_for_any_other_system_is_still_refused_because_importing_appliances_is_not_built():
    got = op.plan_for(entry("someappliance", "thing.ova"), image_carried=True)
    assert "appliance" in got["blocked"] and "plan" not in got


def test_a_carried_ready_made_base_makes_a_plan_that_needs_no_installer_image():
    got = op.plan_for(entry("debian", "debian.iso"), image_carried=False, base_carried=True)
    assert got["plan"] == {"name": "debian", "prebuilt": True, "os": "debian", "disk_gb": 32, "memory_mb": 4096, "cpus": 2, "firmware": "uefi"}
    assert "plan" not in op.plan_for(entry("debian", "debian.iso"), image_carried=False)                  # without the base the missing image still refuses
    small = op.plan_for(entry("omarchy", ""), image_carried=False, host_mb=8192, base_carried=True)["plan"]
    assert small["memory_mb"] == 4096                                                                       # still never more than half of a small host
    assert "Xen" in op.plan_for(entry("qubes", "q.iso"), image_carried=True, base_carried=True)["blocked"]   # a base cannot unblock what cannot be a plain VM


def test_a_missing_image_or_no_image_is_refused_naming_which():
    assert "not carried" in op.plan_for(entry("debian", "debian.iso"), image_carried=False)["blocked"]
    assert "no image" in op.plan_for(entry("debian", ""), image_carried=True)["blocked"]


def test_memory_is_cut_to_half_of_a_small_host_and_a_tiny_host_is_refused():
    assert op.plan_for(entry("omarchy"), image_carried=True, host_mb=12288)["plan"]["memory_mb"] == 6144
    assert op.plan_for(entry("omarchy"), image_carried=True, host_mb=16384)["plan"]["memory_mb"] == 8192
    assert "too little" in op.plan_for(entry("omarchy"), image_carried=True, host_mb=3072)["blocked"]


def test_every_sized_system_is_within_what_the_vm_library_accepts():
    for disk, memory, cpus in list(op.SIZES.values()) + [op.DEFAULT]:
        assert 1 <= disk <= 4096 and 256 <= memory <= 1048576 and 1 <= cpus <= 128
