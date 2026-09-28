"""Orchestrates the full "make a real drive a self-installer" pipeline
- direct instruction: "make one of the 512GB SK Hynix disks ready to
prove itself as a self installer for my laptop", via the web
application (`drive_admin.py`'s `build_self_installer` action), not a
bare CLI invocation this time.

Real safety gate first, always: `physical_device_safety.validate_target_device`
runs before a single byte is written anywhere - no destructive step in
this module accepts a bare device path, matching every other
destructive helper in this codebase (AGENTS.md's own absolute rule).

Three already-real, already-tested stages, composed here rather than
reimplemented:

1. `drive_setup_acquire` - real, GPG+hash-verified `proxmox-auto-install-assistant`
   (skipped if already extracted at `assistant_binary`).
2. `drive_setup_answer.prepare_iso_defensively(fetch_from="http")` - the
   only accepted mode for a real (non-QEMU-only-test) install (decision
   record 02); embeds nothing recoverable in the ISO itself. Disk
   targeted by `filter.ID_SERIAL_SHORT`, never a device letter.
3. `iso_builder.build_current_iso` - remasters that into a genuinely
   self-contained ISO (this repo's own `boot/provision.sh` + `baseline/`
   tree baked in at `/baseline-src`, so no separate deployment step is
   needed after install - the whole point of "self installer").

Then launches the real automated install against the *real* device
path (`drive_setup_install.build_sparse_install_invocation`, its
`target_image` pointed at the real block device, never a QEMU sparse
file) and starts the matching `EphemeralAnswerServer`.

**Honest limitation, inherited from `drive_setup_install.py`, not
solved here**: this module cannot itself confirm the installer
actually reached real completion - that still needs a human or
vision-capable agent reading a screendump (no OCR tooling installed,
by design). `build_and_write_self_installer` returns once the QEMU
process is launched and capturing screendumps; its result says
"launched", never "installed successfully" - a caller must not treat
this function's own success as proof of a finished install.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import drive_setup_acquire as dsa
    import drive_setup_answer as dsan
    import drive_setup_install as dsi
    import iso_builder as ib
    import physical_device_safety as pds
except ImportError:  # pragma: no cover - direct-script execution fallback
    dsa = dsan = dsi = ib = pds = None


# Real, already-verified (this session, decision record 60) Proxmox
# repo coordinates - the same ones drive_setup_acquire's own real run
# used successfully. Re-verify by hand if this is ever stale; never
# silently widen the trust chain.
ACQUIRE_KWARGS = dict(
    keyring_url="https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg",
    release_url="http://download.proxmox.com/debian/pve/dists/trixie/Release",
    release_gpg_url="http://download.proxmox.com/debian/pve/dists/trixie/Release.gpg",
    packages_url="http://download.proxmox.com/debian/pve/dists/trixie/pve-no-subscription/binary-amd64/Packages.gz",
    packages_relative_path="pve-no-subscription/binary-amd64/Packages.gz",
    package_name="proxmox-auto-install-assistant",
    package_version="9.2.8",
    mirror_base_url="http://download.proxmox.com/debian/pve",
)

ANSWER_TEMPLATE = """[global]
keyboard = "en-us"
country = "us"
fqdn = "{fqdn}"
mailto = "root@baseline.test"
timezone = "UTC"
root-password-hashed = "{password_hash}"

[network]
source = "from-dhcp"

[disk-setup]
filesystem = "ext4"
filter.ID_SERIAL_SHORT = "{disk_serial}"
lvm.maxroot = "{lvm_maxroot}"
lvm.maxvz = "{lvm_maxvz}"
lvm.swapsize = "{lvm_swapsize}"
"""


@dataclass
class SelfInstallerResult:
    outcome: str  # "applied" | "refused"
    detail: str
    qemu_process: object = None
    workspace: str | None = None


def _cert_fingerprint(runner, cert_path: Path) -> str:
    proc = runner.run(["openssl", "x509", "-in", str(cert_path), "-noout", "-fingerprint", "-sha256"], timeout=10)
    return proc.stdout.strip().split("=", 1)[1]


def build_and_write_self_installer(
    *,
    device_path: str,
    expected_serial: str,
    device_min_size_bytes: int,
    pds_runner,
    acquire_runner,
    answer_runner,
    iso_builder_runner,
    install_runner,
    workspace: Path,
    repo_root: Path,
    proxmox_source_iso: Path,
    assistant_binary: Path,
    server_host: str,
    cert_path: Path,
    key_path: Path,
    server_port: int = 8443,
    fqdn: str = "baseline.local",
    lvm_maxroot: str = "40G",
    lvm_maxvz: str = "60G",
    lvm_swapsize: str = "4G",
    target_mac: str | None = None,
    target_dmi_product: str | None = None,
    memory_mb: int = 3072,
) -> SelfInstallerResult:
    """The real, composed pipeline. Every stage's own real postcondition
    checks (acquire's hash chain, prepare_iso_defensively's byte scan,
    build_current_iso's provision.sh-reachability check) still run -
    this function adds no new trust of its own, it only sequences
    already-verified stages and stops at the first failure."""
    # 1. Safety gate - real device validation before anything else.
    try:
        pds.validate_target_device(
            device_path, expected_serial=expected_serial,
            min_size_bytes=device_min_size_bytes, runner=pds_runner,
        )
    except pds.PhysicalDeviceSafetyError as exc:
        return SelfInstallerResult("refused", f"device safety check failed: {exc}")

    workspace = Path(workspace)
    acquire_runner.makedirs(workspace)

    # 2. Acquire the real, verified assistant binary (skip if cached).
    if not acquire_runner.path_exists(assistant_binary):
        acquire_ws = workspace / "acquire"
        result = dsa.acquire_and_verify(acquire_runner, acquire_ws, **ACQUIRE_KWARGS)
        if not result.ok:
            failed = next((s for s in result.steps if not s.ok), None)
            return SelfInstallerResult("refused", f"acquiring proxmox-auto-install-assistant failed at {failed.name if failed else '?'}: {failed.detail if failed else ''}")
        extract = dsa.extract_deb(acquire_runner, result.package_path, acquire_ws / "extracted")
        if not extract.ok:
            return SelfInstallerResult("refused", f"extracting assistant failed: {extract.detail}")

    # 3. Build the real answer file, targeting this exact drive by serial.
    import secrets
    pw = dsan.generate_one_time_password()
    pw_hash = dsan.hash_password_sha512crypt(pw, secrets.token_hex(8))
    del pw
    answer_toml = ANSWER_TEMPLATE.format(
        fqdn=fqdn, password_hash=pw_hash, disk_serial=expected_serial,
        lvm_maxroot=lvm_maxroot, lvm_maxvz=lvm_maxvz, lvm_swapsize=lvm_swapsize,
    )
    session_id = secrets.token_urlsafe(24)
    fingerprint = _cert_fingerprint(answer_runner, cert_path)
    url = f"https://{server_host}:{server_port}/answer/{session_id}"

    # 4. prepare_iso_defensively --fetch-from http (real hardware rule).
    answer_iso = workspace / "answer-embedded.iso"
    prep_outcome = dsan.prepare_iso_defensively(
        answer_runner, binary=assistant_binary, source_iso=proxmox_source_iso,
        answer_file=None, fetch_from="http",
        output_path=answer_iso, tmp_dir=workspace / "prep-tmp", workspace_root=workspace,
        expected_fetch_mode="http", expected_url=url, expected_fingerprint=fingerprint,
        min_size=1_000_000_000, max_size=3_000_000_000,
        forbidden_iso_strings=[pw_hash.encode(), answer_toml.encode()],
        extra_args=["--url", url, "--cert-fingerprint", fingerprint],
    )
    if not prep_outcome.ok:
        failed = next((c for c in prep_outcome.postconditions if not c.ok), None)
        return SelfInstallerResult("refused", f"prepare-iso failed at {failed.name if failed else '?'}: {failed.detail if failed else ''}")

    # 5. iso_builder.build_current_iso - bake in boot/provision.sh + baseline/.
    final_iso = workspace / "baseline-self-installer.iso"
    build_result = ib.build_current_iso(
        iso_builder_runner, source_iso=answer_iso, repo_root=repo_root,
        output_iso=final_iso, workspace=workspace / "iso-build",
    )
    if not build_result.ok:
        failed = next((c for c in build_result.postconditions if not c.ok), None)
        return SelfInstallerResult("refused", f"self-contained ISO build failed at {failed.name if failed else '?'}: {failed.detail if failed else ''}")

    # 6. Launch the real automated install against the REAL device.
    invocation = dsi.build_sparse_install_invocation(
        target_image=Path(device_path), prepared_iso=final_iso,
        mac=target_mac or "52:54:00:ba:5e:20", smbios_product="baseline-self-installer",
        serial_log=workspace / "serial.log", memory_mb=memory_mb,
        monitor_socket=workspace / "monitor.sock",
    )
    process = install_runner.popen(invocation.argv, monitor_socket=workspace / "monitor.sock")

    session = dsan.SessionState(
        session_id=session_id, answer_toml=answer_toml,
        expected_mac=target_mac, expected_dmi_product=target_dmi_product, ttl_seconds=1800.0,
    )
    server = dsan.EphemeralAnswerServer(
        bind_host="0.0.0.0", bind_port=server_port,
        cert_path=str(cert_path), key_path=str(key_path), session=session,
    )
    server.start()

    return SelfInstallerResult(
        "applied",
        f"Real automated install launched against {device_path} - QEMU running (PID-equivalent process "
        f"handle returned), answer server listening on {server_host}:{server_port}, screendumps/serial log "
        f"under {workspace}. NOT yet confirmed complete - a human or vision-capable agent must review the "
        f"final screendump before treating this drive as a proven self-installer.",
        qemu_process=process, workspace=str(workspace),
    )
