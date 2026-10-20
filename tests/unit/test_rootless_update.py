import os

import rootless_update as ru

PROVISION = '''
cp "$SRC/baseline/lib/a.py" /opt/baseline/lib/a.py               # a comment
cp "$SRC/baseline/lib/b.py" /opt/baseline/lib/
cp "$SRC/boot/x.service" /etc/systemd/system/x.service
cp "$SRC/baseline/lib/z.py" /mnt/USER_ADMIN/z.py
sync_tree "$SRC/baseline/lib/inventory" /opt/baseline/lib/inventory
chmod 755 /opt/baseline/bin/tool
systemctl enable x.service
apt-get install -y podman
update-grub
echo hello
'''


def test_the_plan_is_read_from_provision_sh_and_root_only_actions_are_named():
    plan = ru.deploy_plan(PROVISION)
    assert plan["copies"][0] == ("baseline/lib/a.py", "/opt/baseline/lib/a.py") and len(plan["copies"]) == 4
    assert plan["trees"] == [("baseline/lib/inventory", "/opt/baseline/lib/inventory")]
    assert plan["modes"] == [(0o755, "/opt/baseline/bin/tool")] and plan["enables"] == ["x.service"]
    assert plan["needs_root"] == ["apt-get install -y podman", "update-grub"]


def make(tmp_path):
    src, root = tmp_path / "src", tmp_path / "root"
    (src / "baseline/lib/inventory").mkdir(parents=True)
    (src / "boot").mkdir()
    (src / "baseline/lib/a.py").write_text("new a")
    (src / "baseline/lib/b.py").write_text("b")
    (src / "baseline/lib/z.py").write_text("z")
    (src / "baseline/lib/inventory/i.py").write_text("i")
    (src / "boot/x.service").write_text("[Install]\nWantedBy=multi-user.target\n")
    (root / "opt/baseline/lib").mkdir(parents=True)
    (root / "opt/baseline/bin").mkdir(parents=True)
    (root / "opt/baseline/bin/tool").write_text("#!/bin/sh")
    (root / "opt/baseline/lib/a.py").write_text("old a")
    (root / "opt/baseline/lib/b.py").write_text("b")
    os.utime(root / "opt/baseline/lib/b.py", ns=(1, 1))
    return src, root


def test_only_files_that_differ_are_written_and_other_volumes_are_never_touched(tmp_path):
    src, root = make(tmp_path)
    report = ru.apply_plan(ru.deploy_plan(PROVISION), src, root)
    assert (root / "opt/baseline/lib/a.py").read_text() == "new a" and os.stat(root / "opt/baseline/lib/b.py").st_mtime_ns == 1
    assert report["skipped_dest"] == ["/mnt/USER_ADMIN/z.py"] and not (root / "mnt").exists()
    assert (root / "opt/baseline/lib/inventory/i.py").read_text() == "i" and oct(os.stat(root / "opt/baseline/bin/tool").st_mode & 0o777) == "0o755"
    assert report["enabled"] == ["x.service"] and os.readlink(root / "etc/systemd/system/multi-user.target.wants/x.service") == "/etc/systemd/system/x.service"
    assert report["needs_root"] == ["apt-get install -y podman", "update-grub"]
    again = ru.apply_plan(ru.deploy_plan(PROVISION), src, root)
    assert again["copied"] == 0 and again["modes_set"] == 0 and again["enabled"] == []                 # a second pass writes nothing
