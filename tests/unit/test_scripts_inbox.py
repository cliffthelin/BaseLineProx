"""Tests for scripts_inbox.py - real file CRUD for the scripts inbox
folder, so a client (a phone, a laptop, anything with network+CRUD
access) can push a script that an operator later runs by hand from a
real Proxmox/Baseline terminal. This module never executes anything -
only stores files.

Path-traversal safety is proven directly: is_safe_name refuses
separators, `..`, and leading dots by construction, matching
gui_brokers.file_picker's own established discipline for this exact
threat class.
"""
import scripts_inbox as si


class FakeInboxRunner:
    def __init__(self):
        self.files = {}  # path -> content (str)
        self.dirs = set()

    def makedirs(self, path):
        self.dirs.add(str(path))

    def listdir(self, path):
        prefix = str(path).rstrip("/") + "/"
        return [p[len(prefix):] for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def path_exists(self, path):
        return str(path) in self.files or str(path) in self.dirs

    def read_text(self, path):
        return self.files[str(path)]

    def write_text_atomic(self, path, content):
        self.files[str(path)] = content

    def remove(self, path):
        del self.files[str(path)]


# -- is_safe_name: path-traversal refused by construction ------------------

def test_is_safe_name_accepts_a_plain_filename():
    assert si.is_safe_name("deploy.sh") is True


def test_is_safe_name_accepts_dots_and_dashes_and_underscores_mid_name():
    assert si.is_safe_name("run-task_v2.1.py") is True


def test_is_safe_name_refuses_path_traversal():
    assert si.is_safe_name("../../etc/shadow") is False


def test_is_safe_name_refuses_a_slash_anywhere():
    assert si.is_safe_name("sub/dir/script.sh") is False


def test_is_safe_name_refuses_a_leading_dot():
    assert si.is_safe_name(".hidden") is False
    assert si.is_safe_name("..") is False


def test_is_safe_name_refuses_empty_string():
    assert si.is_safe_name("") is False


def test_is_safe_name_refuses_an_absurdly_long_name():
    assert si.is_safe_name("a" * 200) is False


# -- list_scripts ------------------------------------------------------------

def test_list_scripts_creates_inbox_dir_and_returns_empty_when_none_exist():
    r = FakeInboxRunner()
    assert si.list_scripts(r, inbox_dir="/mnt/USER/scripts_inbox") == []
    assert "/mnt/USER/scripts_inbox" in r.dirs


def test_list_scripts_returns_sorted_names():
    r = FakeInboxRunner()
    r.files["/inbox/b.sh"] = "b"
    r.files["/inbox/a.sh"] = "a"
    assert si.list_scripts(r, inbox_dir="/inbox") == ["a.sh", "b.sh"]


# -- read_script -------------------------------------------------------------

def test_read_script_returns_content_for_an_existing_script():
    r = FakeInboxRunner()
    r.files["/inbox/deploy.sh"] = "#!/bin/bash\necho hi\n"
    assert si.read_script(r, "deploy.sh", inbox_dir="/inbox") == "#!/bin/bash\necho hi\n"


def test_read_script_returns_none_for_a_missing_script():
    r = FakeInboxRunner()
    assert si.read_script(r, "missing.sh", inbox_dir="/inbox") is None


def test_read_script_refuses_traversal_without_ever_touching_the_filesystem():
    r = FakeInboxRunner()
    r.files["/inbox/../../etc/shadow"] = "root:x:0:0"  # pathological fake state
    assert si.read_script(r, "../../etc/shadow", inbox_dir="/inbox") is None


# -- write_script -------------------------------------------------------------

def test_write_script_creates_a_new_script():
    r = FakeInboxRunner()
    result = si.write_script(r, "new.sh", "echo new\n", inbox_dir="/inbox")
    assert result.ok is True
    assert r.files["/inbox/new.sh"] == "echo new\n"


def test_write_script_overwrites_an_existing_script():
    r = FakeInboxRunner()
    r.files["/inbox/existing.sh"] = "old content\n"
    result = si.write_script(r, "existing.sh", "new content\n", inbox_dir="/inbox")
    assert result.ok is True
    assert r.files["/inbox/existing.sh"] == "new content\n"


def test_write_script_refuses_unsafe_name():
    r = FakeInboxRunner()
    result = si.write_script(r, "../evil.sh", "rm -rf /\n", inbox_dir="/inbox")
    assert result.ok is False
    assert "/inbox/../evil.sh" not in r.files
    assert not any("evil" in k for k in r.files)


def test_write_script_refuses_oversized_content():
    r = FakeInboxRunner()
    huge = "x" * (si.MAX_SCRIPT_BYTES + 1)
    result = si.write_script(r, "huge.sh", huge, inbox_dir="/inbox")
    assert result.ok is False
    assert "/inbox/huge.sh" not in r.files


def test_write_script_creates_inbox_dir_if_missing():
    r = FakeInboxRunner()
    si.write_script(r, "first.sh", "echo hi\n", inbox_dir="/inbox")
    assert "/inbox" in r.dirs


# -- delete_script -------------------------------------------------------------

def test_delete_script_removes_an_existing_script():
    r = FakeInboxRunner()
    r.files["/inbox/gone.sh"] = "bye\n"
    result = si.delete_script(r, "gone.sh", inbox_dir="/inbox")
    assert result.ok is True
    assert "/inbox/gone.sh" not in r.files


def test_delete_script_refuses_a_missing_script():
    r = FakeInboxRunner()
    result = si.delete_script(r, "missing.sh", inbox_dir="/inbox")
    assert result.ok is False


def test_delete_script_refuses_unsafe_name_without_touching_the_filesystem():
    r = FakeInboxRunner()
    r.files["/inbox/real.sh"] = "content\n"
    result = si.delete_script(r, "../real.sh", inbox_dir="/inbox")
    assert result.ok is False
    assert "/inbox/real.sh" in r.files


# -- inbox_dir_for: persona-aware wiring (work-queue item 25) ---------------

def test_inbox_dir_for_defaults_to_the_legacy_singular_inbox_dir():
    assert si.inbox_dir_for() == si.DEFAULT_INBOX_DIR
    assert si.inbox_dir_for(None) == si.DEFAULT_INBOX_DIR


def test_inbox_dir_for_a_real_persona_uses_its_own_mountpoint():
    assert si.inbox_dir_for("admin") == "/mnt/USER_ADMIN/scripts_inbox"
    assert si.inbox_dir_for("personal") == "/mnt/USER_PERSONAL/scripts_inbox"


def test_inbox_dir_for_different_personas_never_collide():
    assert si.inbox_dir_for("admin") != si.inbox_dir_for("personal")
