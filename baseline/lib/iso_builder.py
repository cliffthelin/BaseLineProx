"""Builds a self-contained, "current" Baseline installer ISO: takes
the already-verified Proxmox auto-install ISO
(drive_setup_answer.prepare_iso_defensively's own output) and remasters
it with xorriso to also carry this repo's own boot/provision.sh +
baseline/ tree at /baseline-src, so a fresh install needs no separate
git-clone/copy step afterward - the installer already carries the
exact code that was live in this repo the moment the ISO was built.

`-boot_image any replay` is the real reason this is safe: it copies
the source ISO's own, already-working El Torito boot record onto the
new ISO unchanged rather than rebuilding one from scratch, so remaster
can never turn a bootable input ISO into an unbootable output one
(verified directly against a real synthetic bootable ISO with real
xorriso before writing this module - `boot.catalog` and the boot file
came through unchanged in that run).

Never trusts a single signal for success - matches
drive_setup_answer.prepare_iso_defensively's own standing discipline
for exactly this class of external-tool unreliability: checks
xorriso's exit code, that the output file genuinely exists, that it is
not smaller than the source (only files were ever added), and that
provision.sh is actually reachable inside the real output ISO via a
second, independent `xorriso -find` rather than assuming the remaster
step's own success implies it.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class IsoBuilderRunner:
    def run(self, argv: list[str], timeout: float = 300) -> "IsoBuilderProc":
        raise NotImplementedError

    def path_exists(self, path: Path) -> bool:
        raise NotImplementedError

    def file_size(self, path: Path) -> int:
        raise NotImplementedError

    def makedirs(self, path: Path) -> None:
        raise NotImplementedError

    def copytree(self, src: Path, dst: Path) -> None:
        raise NotImplementedError


@dataclass
class IsoBuilderProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class RealIsoBuilderRunner(IsoBuilderRunner):
    def run(self, argv, timeout=300):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return IsoBuilderProc(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return IsoBuilderProc(returncode=-1, stderr=str(exc))

    def path_exists(self, path):
        return Path(path).exists()

    def file_size(self, path):
        return Path(path).stat().st_size

    def makedirs(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)

    def copytree(self, src, dst):
        shutil.copytree(str(src), str(dst))


@dataclass
class PostconditionResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class IsoBuildResult:
    ok: bool
    output_path: Path | None = None
    postconditions: list = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


ISO_TARGET_DIR = "/baseline-src"


def remaster_argv(source_iso: Path, output_iso: Path, staging_dir: Path,
                   iso_target_dir: str = ISO_TARGET_DIR) -> list:
    return ["xorriso", "-indev", str(source_iso), "-outdev", str(output_iso),
            "-boot_image", "any", "replay", "-map", str(staging_dir), iso_target_dir, "--"]


def find_in_iso_argv(iso_path: Path, iso_target_path: str) -> list:
    return ["xorriso", "-indev", str(iso_path), "-find", iso_target_path]


def stage_baseline_source(runner: IsoBuilderRunner, *, repo_root: Path, staging_dir: Path) -> None:
    """Mirrors provision.sh's own expected layout exactly - it locates
    itself at <SRC>/boot/provision.sh and reads $SRC/baseline/... via
    SRC="$(dirname "$0")/.." - so the staged tree keeps boot/ and
    baseline/ as siblings, never flattened, so provision.sh runs
    unmodified once copied off the ISO onto the real target."""
    runner.makedirs(staging_dir)
    runner.copytree(repo_root / "boot", staging_dir / "boot")
    runner.copytree(repo_root / "baseline", staging_dir / "baseline")


def build_current_iso(runner: IsoBuilderRunner, *, source_iso: Path, repo_root: Path,
                       output_iso: Path, workspace: Path,
                       iso_target_dir: str = ISO_TARGET_DIR) -> IsoBuildResult:
    checks: list[PostconditionResult] = []
    runner.makedirs(workspace)
    staging_dir = workspace / "staging"
    stage_baseline_source(runner, repo_root=repo_root, staging_dir=staging_dir)

    proc = runner.run(remaster_argv(source_iso, output_iso, staging_dir, iso_target_dir), timeout=600)
    checks.append(PostconditionResult("xorriso_remaster_exit_zero", proc.returncode == 0, proc.stderr.strip()[-500:]))
    if proc.returncode != 0:
        return IsoBuildResult(ok=False, postconditions=checks, stdout=proc.stdout, stderr=proc.stderr)

    exists = runner.path_exists(output_iso)
    checks.append(PostconditionResult("output_exists", exists))
    if not exists:
        return IsoBuildResult(ok=False, postconditions=checks, stdout=proc.stdout, stderr=proc.stderr)

    source_size = runner.file_size(source_iso)
    output_size = runner.file_size(output_iso)
    checks.append(PostconditionResult(
        "output_not_smaller_than_source", output_size >= source_size,
        f"source={source_size} output={output_size}",
    ))

    find_proc = runner.run(find_in_iso_argv(output_iso, f"{iso_target_dir}/boot/provision.sh"), timeout=60)
    checks.append(PostconditionResult(
        "provision_sh_present_in_output_iso",
        find_proc.returncode == 0 and "provision.sh" in find_proc.stdout,
        find_proc.stdout.strip()[-200:] or find_proc.stderr.strip()[-200:],
    ))

    ok = all(c.ok for c in checks)
    return IsoBuildResult(ok=ok, output_path=output_iso if ok else None, postconditions=checks,
                           stdout=proc.stdout, stderr=proc.stderr)
