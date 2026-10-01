"""A temporary RAM-backed stand-in for a drive, for tests. A folder under pytest's tmp dir (tmpfs here) holds a
marker file, and a table records 'mounts'. Fake actions mutate it, so a test can show that a drive's contents
survive an unconfirmed request and change exactly once after a human confirmation. No device node is ever opened."""
from pathlib import Path

import drive_admin as da


class RamDrive:
    def __init__(self, root: Path, serial: str = "MD89N41071210AP4E"):
        self.root = Path(root)
        self.root.mkdir(parents=True)
        self.serial = serial
        self.marker = self.root / "important.txt"
        self.marker.write_text("precious")
        self.mounted = {}
        self.installs = 0

    def intact(self) -> bool:
        return self.marker.exists() and self.marker.read_text() == "precious"

    def install(self) -> None:
        """Stand-in for build_self_installer: it wipes the drive."""
        self.installs += 1
        if self.marker.exists():
            self.marker.unlink()

    def mount(self, mountpoint: str, lv_name: str) -> None:
        self.mounted[mountpoint] = lv_name

    def unmount(self, mountpoint: str) -> None:
        self.mounted.pop(mountpoint, None)

    def install_fake_actions(self, monkeypatch) -> None:
        """Replace the real, hardware-reaching actions with ones that act on this RAM drive."""
        def fake_install(runner, device_path, **p):
            self.install()
            return da.ActionResult(True, "installed onto the RAM drive")

        def fake_mount(runner, device_path, lv_name="root", mountpoint="/mnt/ram-inspect", **p):
            self.mount(mountpoint, lv_name)
            return da.ActionResult(True, f"mounted {lv_name} at {mountpoint}")

        def fake_unmount(runner, device_path, lv_name="root", mountpoint="/mnt/ram-inspect", **p):
            self.unmount(mountpoint)
            return da.ActionResult(True, f"unmounted {mountpoint}")

        for action_id, fn in (("build_self_installer", fake_install), ("mount_volume", fake_mount),
                              ("unmount_volume", fake_unmount)):
            monkeypatch.setitem(da.ACTIONS, action_id, da.ActionSpec(action_id, f"RAM-drive stand-in for {action_id}", fn,
                                                                     requires_device=True))
