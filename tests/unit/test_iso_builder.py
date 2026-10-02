"""Tests for iso_builder.py - remastering the already-verified Proxmox
auto-install ISO (drive_setup_answer.py's own output) to also carry
this repo's current boot/provision.sh + baseline/ tree, so a fresh
install needs no separate git-clone/copy step afterward.

FakeIsoBuilderRunner mirrors test_drive_setup_answer.py's own
FakeAnswerRunner style (script(predicate, proc) + a files/dirs dict)
rather than inventing a new fake shape for the same kind of interface.
"""
from pathlib import Path

import iso_builder as ib


class FakeIsoBuilderRunner(ib.IsoBuilderRunner):
    def __init__(self):
        self.files = {}  # path -> size (int) - content itself is irrelevant to this module's own logic
        self.dirs = set()
        self.copied_trees = []  # (src, dst) pairs
        self.removed_trees = []
        self.removed_files = []
        self.command_responses = []
        self.calls = []

    def script(self, predicate, proc: "ib.IsoBuilderProc"):
        self.command_responses.append((predicate, proc))

    def run(self, argv, timeout=300):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                if (proc.returncode == 0 and argv[:1] == ["xorriso"] and "-outdev" in argv
                        and getattr(self, "_pending_output", None)):
                    outdev, size = self._pending_output
                    self.files[outdev] = size
                return proc
        return ib.IsoBuilderProc(0, "", "")

    def path_exists(self, path):
        return str(path) in self.files or str(path) in self.dirs

    def file_size(self, path):
        return self.files[str(path)]

    def makedirs(self, path):
        self.dirs.add(str(path))

    def copytree(self, src, dst):
        self.copied_trees.append((str(src), str(dst)))
        self.dirs.add(str(dst))

    def remove_tree(self, path):
        self.removed_trees.append(str(path))
        self.dirs.discard(str(path))

    def remove_file(self, path):
        self.removed_files.append(str(path))
        self.files.pop(str(path), None)


def _base_runner(*, source_size=400_000, output_size=460_000):
    r = FakeIsoBuilderRunner()
    r.files["/src/source.iso"] = source_size
    r.script(lambda a: a[:2] == ["xorriso", "-indev"] and "-outdev" in a,
              ib.IsoBuilderProc(0, "", ""))
    r.script(lambda a: "-find" in a,
              ib.IsoBuilderProc(0, "'/baseline-src/boot/provision.sh'\n", ""))
    # remaster "creates" the output file as a real side effect of a
    # successful xorriso call - simulated via run()'s own special-case
    # (real bug found live, 2026-09-29: build_current_iso now removes
    # any stale pre-existing output file *before* calling xorriso, so
    # pre-registering the file here directly would just be immediately
    # wiped by that real removal before the postcondition checks ever
    # see it).
    r._pending_output = ("/out/current.iso", output_size)
    return r


def test_stage_baseline_source_copies_boot_and_baseline_as_siblings():
    r = FakeIsoBuilderRunner()
    ib.stage_baseline_source(r, repo_root=Path("/repo"), staging_dir=Path("/ws/staging"))
    assert ("/repo/boot", "/ws/staging/boot") in r.copied_trees
    assert ("/repo/baseline", "/ws/staging/baseline") in r.copied_trees


def test_installer_carries_the_desktop_packaging_that_provision_requires():
    r = FakeIsoBuilderRunner()
    ib.stage_baseline_source(r, repo_root=Path("/repo"), staging_dir=Path("/ws/staging"))
    assert ("/repo/packaging", "/ws/staging/packaging") in r.copied_trees


def test_stage_baseline_source_removes_a_stale_staging_dir_before_copying():
    """Real bug found live, 2026-09-29: the workspace is a fixed,
    reused path across real retries (by design - the cached assistant
    binary under `workspace/acquire/` is meant to survive a retry) -
    but a prior *failed* attempt's own `staging/boot` directory was
    left behind too, and a bare `shutil.copytree` into an already-
    existing destination raised a real `FileExistsError`. Every real
    retry must start from a genuinely clean staging directory."""
    r = FakeIsoBuilderRunner()
    r.dirs.add("/ws/staging")
    r.dirs.add("/ws/staging/boot")  # leftover from a prior failed attempt
    ib.stage_baseline_source(r, repo_root=Path("/repo"), staging_dir=Path("/ws/staging"))
    assert "/ws/staging" in r.removed_trees
    assert ("/repo/boot", "/ws/staging/boot") in r.copied_trees


def test_remaster_argv_shape():
    """`patch`, not `replay` and not `keep` (real bug found live,
    2026-09-29, corrected same-day): the real Proxmox source ISO's
    quadruple-hybrid boot record (El Torito + MBR grub2-mbr + GPT +
    APM) makes `replay` fail for real with `Overlapping MBR partition
    entries requested`. `keep` completes cleanly but a real, isolated
    QEMU boot test proved its actual output ISO never boots (hangs
    forever at SeaBIOS's "Booting from DVD/CD..."). `patch` was then
    boot-tested the same real way and genuinely works - boots all the
    way into the real Proxmox installer environment."""
    argv = ib.remaster_argv(Path("/src/source.iso"), Path("/out/current.iso"), Path("/ws/staging"))
    assert argv == [
        "xorriso", "-indev", "/src/source.iso", "-outdev", "/out/current.iso",
        "-boot_image", "any", "patch", "-map", "/ws/staging", "/baseline-src", "--",
    ]


def test_find_in_iso_argv_shape():
    argv = ib.find_in_iso_argv(Path("/out/current.iso"), "/baseline-src/boot/provision.sh")
    assert argv == ["xorriso", "-indev", "/out/current.iso", "-find", "/baseline-src/boot/provision.sh"]


def test_build_current_iso_success_all_postconditions_pass():
    r = _base_runner()
    result = ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert result.ok is True
    assert result.output_path == Path("/out/current.iso")
    assert all(c.ok for c in result.postconditions)
    assert ("/repo/boot", "/ws/staging/boot") in r.copied_trees
    assert ("/repo/baseline", "/ws/staging/baseline") in r.copied_trees


def test_build_current_iso_removes_a_stale_output_file_before_remastering():
    """Real bug found live, 2026-09-29: a prior real attempt's own
    output ISO (~1.7GB, real non-zero ISO9660 session data) was still
    sitting at this same fixed, reused workspace path - xorriso
    refuses to write a fresh `-outdev` over one that already holds
    real data: `FAILURE: -indev differs from -outdev and -outdev
    media holds non-zero data`. Every real retry must remove it first."""
    r = _base_runner()
    ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert "/out/current.iso" in r.removed_files


def test_build_current_iso_fails_when_xorriso_remaster_exits_nonzero():
    r = FakeIsoBuilderRunner()
    r.files["/src/source.iso"] = 400_000
    r.script(lambda a: a[:2] == ["xorriso", "-indev"] and "-outdev" in a,
              ib.IsoBuilderProc(1, "", "xorriso: FAILURE: ..."))
    result = ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert result.ok is False
    assert result.output_path is None
    failed = [c for c in result.postconditions if not c.ok]
    assert any(c.name == "xorriso_remaster_exit_zero" for c in failed)


def test_build_current_iso_fails_when_output_does_not_exist_despite_zero_exit():
    """Never trust the exit code alone - matches
    drive_setup_answer.prepare_iso_defensively's own standing
    discipline for exactly this class of external-tool unreliability."""
    r = FakeIsoBuilderRunner()
    r.files["/src/source.iso"] = 400_000
    r.script(lambda a: a[:2] == ["xorriso", "-indev"] and "-outdev" in a,
              ib.IsoBuilderProc(0, "", ""))
    # output_iso deliberately never registered in r.files
    result = ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert result.ok is False
    assert result.output_path is None
    assert any(c.name == "output_exists" and not c.ok for c in result.postconditions)


def test_build_current_iso_fails_when_output_smaller_than_source():
    r = _base_runner(source_size=500_000, output_size=100_000)
    result = ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert result.ok is False
    failed_names = [c.name for c in result.postconditions if not c.ok]
    assert "output_not_smaller_than_source" in failed_names


def test_build_current_iso_fails_when_provision_sh_not_found_in_output():
    r = _base_runner()
    # override the -find response to report absence
    r.command_responses = [
        (lambda a: a[:2] == ["xorriso", "-indev"] and "-outdev" in a, ib.IsoBuilderProc(0, "", "")),
        (lambda a: "-find" in a, ib.IsoBuilderProc(5, "", "xorriso: FAILURE: Cannot find path")),
    ]
    result = ib.build_current_iso(
        r, source_iso=Path("/src/source.iso"), repo_root=Path("/repo"),
        output_iso=Path("/out/current.iso"), workspace=Path("/ws"),
    )
    assert result.ok is False
    failed_names = [c.name for c in result.postconditions if not c.ok]
    assert "provision_sh_present_in_output_iso" in failed_names


def test_real_iso_builder_runner_run_uses_real_subprocess():
    r = ib.RealIsoBuilderRunner()
    proc = r.run(["true"], timeout=5)
    assert proc.returncode == 0
