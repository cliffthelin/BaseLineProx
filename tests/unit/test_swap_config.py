"""Host swap as a setting the user can change (operator 2026-10-16): size (including none) and kind, applied safely on a running machine.

kind "file":     a swap file in SESSION_TEMP, written once (the existing choice: it keeps swap from ever finding a missing block in a full thin pool).
kind "reserved": a regular volume in the volume group: the space is reserved, nothing is written (operator: "as long as you're just reserving").

The host is simulated (swap devices, volumes, free space) so the real command sequences and the failure paths are checked without touching
a machine. The new swap is always brought up BEFORE the old one is released, so the host never runs without swap in between."""
import pytest
from fake_runner import FakeProc, FakeRunner

import swap_config as sc

GIB = 2**30
VG = "baseline_abc"


class World(FakeRunner):
    def __init__(self, active=None, lvs=(), files=(), vg_free=200 * GIB, fstab=None):
        super().__init__()
        self.active = dict(active or {})                 # name -> bytes
        self.lvs, self.files, self.vg_free = set(lvs), set(files), vg_free
        self.fail = set()                                # command words that fail: "dd", "swapoff:<name>", "lvcreate", ...
        self.log = []
        self.fstab = fstab if fstab is not None else ""
        self.grown = []

    def read_text(self, path):
        assert path == "/etc/fstab"
        return self.fstab

    def write_text_atomic(self, path, content):
        assert path == "/etc/fstab"
        self.fstab = content

    def listdir(self, path):
        prefix = path.rstrip("/") + "/"
        return sorted(f[len(prefix):] for f in self.files if f.startswith(prefix) and "/" not in f[len(prefix):])

    def path_exists(self, path):
        return path in self.files or (path.startswith("/dev/") and path.split("/")[-1] in self.lvs)

    def remove(self, path):
        self.files.discard(path)
        self.log.append(["remove", path])

    def run(self, argv, timeout=10):
        argv = list(argv)
        self.calls.append(argv)
        self.log.append(argv)
        tool = argv[0]
        if tool == "swapon" and argv[1:2] == ["--noheadings"]:
            return FakeProc(0, "".join(f"{self._listed(n)} {s}\n" for n, s in self.active.items()), "")
        if tool == "lvs":
            return FakeProc(0, "".join(f"  {lv},{self._minor(lv)}\n" for lv in sorted(self.lvs)), "")
        if tool == "swapon":
            self.active[argv[1]] = self._size_of(argv[1])
            return FakeProc(0, "", "")
        if tool == "swapoff":
            if f"swapoff:{argv[1]}" in self.fail or "swapoff" in self.fail:
                return FakeProc(1, "", "swapoff: failed to swapoff: Cannot allocate memory")
            self.active.pop(argv[1], None)
            return FakeProc(0, "", "")
        if tool == "dd":
            if "dd" in self.fail:
                self.files.add(next(a[3:] for a in argv if a.startswith("of=")))       # a partial file is left behind
                return FakeProc(1, "", "dd: error writing: No space left on device")
            path = next(a[3:] for a in argv if a.startswith("of="))
            count = int(next(a[6:] for a in argv if a.startswith("count=")))
            self.files.add(path)
            self.sizes = getattr(self, "sizes", {})
            self.sizes[path] = count * 2**20
            return FakeProc(0, "", "")
        if tool == "mkswap":
            return FakeProc(0, "", "")
        if tool == "chmod":
            return FakeProc(0, "", "")
        if tool == "lvcreate":
            if "lvcreate" in self.fail:
                return FakeProc(5, "", "lvcreate: insufficient free space")
            size = int(argv[argv.index("-L") + 1].rstrip("G")) * GIB
            self.lvs.add(argv[argv.index("-n") + 1])
            self.sizes = getattr(self, "sizes", {})
            self.sizes["/dev/%s/%s" % (argv[-1], argv[argv.index("-n") + 1])] = size
            self.vg_free -= size
            return FakeProc(0, "", "")
        if tool == "lvremove":
            name = argv[-1].split("/")[-1]
            self.lvs.discard(name)
            return FakeProc(0, "", "")
        if tool == "vgs":
            return FakeProc(0, f"  {self.vg_free}\n", "")
        return FakeProc(0, "", "")

    def _minor(self, lv):
        self.minors = getattr(self, "minors", {})
        return self.minors.setdefault(lv, 10 + len(self.minors))

    def _listed(self, name):
        """/proc/swaps shows a logical volume as /dev/dm-N, not as /dev/<vg>/<lv>."""
        if name.startswith(f"/dev/{VG}/"):
            return f"/dev/dm-{self._minor(name.split('/')[-1])}"
        return name

    def _size_of(self, name):
        return getattr(self, "sizes", {}).get(name, 0)


def grow(world):
    return lambda runner, label, needed: world.grown.append((label, needed))


def dd_calls(world):
    return [c for c in world.log if c[0] == "dd"]


# --- validation --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gib,kind", [(0, "file"), (4, "file"), (8, "reserved"), (64, "reserved")])
def test_valid_choices(gib, kind):
    assert sc.validate(gib, kind) == (gib, kind)


@pytest.mark.parametrize("gib,kind", [(-1, "file"), (65, "file"), ("4", "file"), (True, "file"), (4.5, "file"), (4, "zeroed"), (4, None), (None, "file")])
def test_invalid_choices_are_refused(gib, kind):
    with pytest.raises(ValueError):
        sc.validate(gib, kind)


# --- what is active now --------------------------------------------------------------------------------------------------------------

def test_the_current_swap_is_recognised_by_kind():
    assert sc.current(World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}), VG) == {"kind": "file", "gib": 4, "names": ["/mnt/SESSION_TEMP/swapfile"]}
    reserved = sc.current(World(active={f"/dev/{VG}/baseline_swap_8g": 8 * GIB}, lvs={"baseline_swap_8g"}), VG)
    assert reserved["kind"] == "reserved" and reserved["gib"] == 8 and reserved["names"] == [f"/dev/{VG}/baseline_swap_8g"]
    assert sc.current(World(active={f"/dev/{VG}/swap": 2 * GIB}, lvs={"swap"}), VG)["kind"] == "proxmox-default"
    none = sc.current(World(), VG)
    assert none["kind"] is None and none["gib"] == 0
    assert sc.current(World(active={"/dev/sdz9": 8 * GIB}), VG)["kind"] is None          # someone else's swap is not ours


# --- applying ----------------------------------------------------------------------------------------------------------------------

def test_asking_for_what_is_already_active_changes_nothing():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB})
    result = sc.apply(w, VG, 4, "file", ensure_room=grow(w))
    changing = [c for c in w.log if c[0] in ("dd", "mkswap", "lvcreate", "lvremove", "swapoff", "remove", "chmod")
                or (c[0] == "swapon" and c[1:2] != ["--noheadings"])]
    assert result["changed"] is False and changing == [] and w.fstab == ""


def test_moving_from_the_proxmox_default_volume_to_a_file_writes_one_file_of_the_requested_size():
    w = World(active={f"/dev/{VG}/swap": 2 * GIB}, lvs={"swap"}, fstab=f"/dev/{VG}/swap none swap sw 0 0\nUUID=x / ext4 defaults 0 1\n")
    result = sc.apply(w, VG, 4, "file", ensure_room=grow(w))
    assert result["changed"] and [c[3:5] for c in dd_calls(w)] == [["bs=1M", "count=4096"]]
    assert "/mnt/SESSION_TEMP/swapfile-4G" in w.active and f"/dev/{VG}/swap" not in w.active and "swap" not in w.lvs
    assert "/mnt/SESSION_TEMP/swapfile-4G none swap sw 0 0" in w.fstab and f"/dev/{VG}/swap" not in w.fstab and "UUID=x / ext4" in w.fstab
    assert w.grown and w.grown[0][0] == "SESSION_TEMP"


def test_a_reserved_swap_reserves_the_space_and_writes_none_of_it():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"})
    result = sc.apply(w, VG, 8, "reserved", ensure_room=grow(w))
    assert result["changed"] and dd_calls(w) == []                                   # reserving, never writing
    assert ["lvcreate", "-y", "-L", "8G", "-n", "baseline_swap_8g", VG] in w.log
    assert f"/dev/{VG}/baseline_swap_8g" in w.active and "/mnt/SESSION_TEMP/swapfile" not in w.active
    assert "/mnt/SESSION_TEMP/swapfile" not in w.files                               # the old file was released and removed
    assert f"/dev/{VG}/baseline_swap_8g none swap sw 0 0" in w.fstab
    assert w.vg_free == 192 * GIB                                                    # the group's free space went down by exactly what was reserved


def test_going_back_from_reserved_to_a_file_gives_the_volume_back():
    w = World(active={f"/dev/{VG}/baseline_swap_8g": 8 * GIB}, lvs={"baseline_swap_8g"}, fstab=f"/dev/{VG}/baseline_swap_8g none swap sw 0 0\n")
    sc.apply(w, VG, 4, "file", ensure_room=grow(w))
    assert "baseline_swap_8g" not in w.lvs and "/mnt/SESSION_TEMP/swapfile-4G" in w.active
    assert "baseline_swap_8g" not in w.fstab


def test_changing_the_size_of_a_file_makes_the_new_one_before_releasing_the_old():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"})
    sc.apply(w, VG, 8, "file", ensure_room=grow(w))
    on = [i for i, c in enumerate(w.log) if c[:2] == ["swapon", "/mnt/SESSION_TEMP/swapfile-8G"]]
    off = [i for i, c in enumerate(w.log) if c[:2] == ["swapoff", "/mnt/SESSION_TEMP/swapfile"]]
    assert on and off and on[0] < off[0], "the host would run without swap in between"
    assert [c[4] for c in dd_calls(w)] == ["count=8192"]


def test_none_releases_every_swap_this_product_manages_and_leaves_no_fstab_line():
    w = World(active={"/mnt/SESSION_TEMP/swapfile-4G": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile-4G"},
              fstab="/mnt/SESSION_TEMP/swapfile-4G none swap sw 0 0\nUUID=x / ext4 defaults 0 1\n")
    result = sc.apply(w, VG, 0, "file", ensure_room=grow(w))
    assert result["changed"] and w.active == {} and not w.files and "swap" not in w.fstab.replace("UUID=x / ext4", "")
    assert dd_calls(w) == []


def test_swap_that_is_not_ours_is_never_touched():
    w = World(active={"/dev/sdz9": 8 * GIB, "/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"},
              fstab="/dev/sdz9 none swap sw 0 0\n/mnt/SESSION_TEMP/swapfile none swap sw 0 0\n")
    sc.apply(w, VG, 0, "file", ensure_room=grow(w))
    assert "/dev/sdz9" in w.active and "/dev/sdz9 none swap sw 0 0" in w.fstab
    assert not any(c[:2] == ["swapoff", "/dev/sdz9"] for c in w.log)


# --- failures never leave the host worse off ------------------------------------------------------------------------------------------

def test_a_failed_write_removes_the_partial_file_and_leaves_the_old_swap_and_fstab_alone():
    w = World(active={f"/dev/{VG}/swap": 2 * GIB}, lvs={"swap"}, fstab=f"/dev/{VG}/swap none swap sw 0 0\n")
    w.fail.add("dd")
    with pytest.raises(sc.SwapError, match="No space left"):
        sc.apply(w, VG, 4, "file", ensure_room=grow(w))
    assert f"/dev/{VG}/swap" in w.active and "swap" in w.lvs and not w.files
    assert w.fstab == f"/dev/{VG}/swap none swap sw 0 0\n"


def test_a_volume_group_without_room_is_refused_before_anything_changes():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"}, vg_free=5 * GIB)
    with pytest.raises(sc.SwapError, match="8 GiB.*5 GiB|only 4 GiB|not enough"):
        sc.apply(w, VG, 8, "reserved", ensure_room=grow(w))
    assert not any(c[0] in ("lvcreate", "swapoff", "dd") for c in w.log)


def test_a_failed_volume_creation_changes_nothing_else():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"})
    w.fail.add("lvcreate")
    with pytest.raises(sc.SwapError, match="insufficient free space"):
        sc.apply(w, VG, 8, "reserved", ensure_room=grow(w))
    assert "/mnt/SESSION_TEMP/swapfile" in w.active and w.fstab == ""


def test_when_the_old_swap_cannot_be_released_the_new_one_stays_and_the_old_is_kept_for_the_next_restart():
    w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"},
              fstab="/mnt/SESSION_TEMP/swapfile none swap sw 0 0\n")
    w.fail.add("swapoff:/mnt/SESSION_TEMP/swapfile")
    result = sc.apply(w, VG, 8, "file", ensure_room=grow(w))
    assert "/mnt/SESSION_TEMP/swapfile-8G" in w.active and "/mnt/SESSION_TEMP/swapfile" in w.active
    assert "/mnt/SESSION_TEMP/swapfile" in w.files, "a swap file that is still in use must not be deleted"
    assert w.fstab.count("swap sw") == 1 and "swapfile-8G" in w.fstab                     # after a restart only the new one remains
    assert any("next restart" in n for n in result["notes"])


def test_a_leftover_from_an_earlier_partial_release_is_cleaned_up_on_the_next_change():
    w = World(active={"/mnt/SESSION_TEMP/swapfile-8G": 8 * GIB}, files={"/mnt/SESSION_TEMP/swapfile", "/mnt/SESSION_TEMP/swapfile-8G"})
    result = sc.apply(w, VG, 4, "file", ensure_room=grow(w))
    assert "/mnt/SESSION_TEMP/swapfile" not in w.files and "/mnt/SESSION_TEMP/swapfile-8G" not in w.files
    assert "/mnt/SESSION_TEMP/swapfile-4G" in w.active and result["changed"]


def test_only_the_file_kind_ever_runs_the_zero_writer():
    for gib in (1, 8, 32):
        w = World(active={"/mnt/SESSION_TEMP/swapfile": 4 * GIB}, files={"/mnt/SESSION_TEMP/swapfile"})
        sc.apply(w, VG, gib if gib != 4 else 5, "reserved", ensure_room=grow(w))
        assert dd_calls(w) == []
