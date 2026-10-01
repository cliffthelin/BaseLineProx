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

# Real bug found live, 2026-09-29 (decision record 115): the previous
# run's own `EphemeralAnswerServer` was never stopped before a new one
# tried to bind the same port - confirmed live via a real
# `OSError: [Errno 98] Address already in use` on a retry, and (on an
# earlier retry where the bind happened to still succeed) a real
# `Fetching answer file via HTTP failed: timeout` where the VM's
# request silently reached a *stale* server from an even older run
# whose session token didn't match. `EphemeralAnswerServer` is a
# real, process-wide OS resource (one process, one port) - like
# `baseline_web.py`'s own `_JOBS` registry, tracking the single
# currently-active instance here (not per-call state) is the correct
# shape for it, mirroring decision record 113's same fix for the
# QEMU process.
_active_answer_server: "dsan.EphemeralAnswerServer | None" = None


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
lvm.maxroot = {lvm_maxroot}
lvm.maxvz = {lvm_maxvz}
lvm.swapsize = {lvm_swapsize}
"""


# Matches settings_store.py's "self_installer.lvm_size_preset" options
# exactly - the pre-populated, dropdown-selected sizing an operator
# chose ahead of time on the Admin tab, never typed at install time.
#
# Plain numbers (GB), never a quoted "NNG" string - real bug found by
# the QEMU disposable-install smoke test (decision record 93): Proxmox's
# own answer-file schema requires lvm.maxroot/maxvz/swapsize as f64,
# and a quoted string value there is a hard TOML-schema parse error
# ("invalid type: string \"40G\", expected f64") that would have failed
# every real self-installer run - invisible to every prior unit test,
# since none of them ever ran the real assistant binary's own
# `validate-answer`/`prepare-iso` against the actual generated TOML.
LVM_SIZE_PRESETS = {
    # The real installer default (2026-09-29 sizing-defaults instruction:
    # "ProxMox 5GB - Expandable to 50GB"): root starts small on purpose.
    # "Expandable to 50GB" is a real, later `lvextend`+`resize2fs` action
    # this project intends to make against a live install, not something
    # enforced by this preset alone - it's only practical if `lvm_maxvz`
    # doesn't consume the whole disk, which is why this preset keeps
    # `lvm_maxvz`/`lvm_swapsize` at "small"'s own already-real values
    # rather than guessing new ones for a figure the instruction didn't
    # specify.
    "minimal": dict(lvm_maxroot=5, lvm_maxvz=30, lvm_swapsize=2),
    "small": dict(lvm_maxroot=20, lvm_maxvz=30, lvm_swapsize=2),
    "medium": dict(lvm_maxroot=40, lvm_maxvz=60, lvm_swapsize=4),
    "large": dict(lvm_maxroot=80, lvm_maxvz=120, lvm_swapsize=8),
}

# Real bug found live, 2026-09-29 (a regression from decision record
# 03's own already-proven fix): `10.0.2.2` is SLIRP's own gateway
# address - real DHCP/DNS traffic reaches it because SLIRP implements
# those protocols internally, but a real host-bound TCP service is
# NOT reachable there at all under `restrict=on` (confirmed directly,
# twice: the actual installer's own answer-file POST, and an
# independent bash `/dev/tcp` probe against an unrelated test server -
# both got a real `Connection refused`). `10.0.2.100` is the
# guestfwd-forwarded address decision record 03 already established
# and proved working - distinct from the real gateway, reachable
# specifically because `drive_setup_install._network_argv`'s real
# `guestfwd=tcp:10.0.2.100:<port>-tcp:127.0.0.1:<port>` rule punches
# exactly this one exception through `restrict=on`. Still never a
# network address a human has to type - a human still never sees
# this, it's baked into the answer file and the QEMU invocation
# together, automatically.
DEFAULT_SERVER_HOST = "10.0.2.100"

# Real, conventional cache locations checked in order when no source
# ISO is explicitly supplied - matches this project's own
# INSTALLER_CACHE storage-class convention (testpersistence-prd.md), so
# a drive that was ever set up as Baseline persistence already has one
# of these populated and needs no manual path entry either.
DEFAULT_SOURCE_ISO_SEARCH_PATHS = [
    Path("/mnt/INSTALLER_CACHE/isos/proxmox-ve-source.iso"),
    Path("/var/lib/baseline/installer-cache/proxmox-ve-source.iso"),
]


@dataclass
class SelfInstallerResult:
    outcome: str  # "applied" | "refused"
    detail: str
    qemu_process: object = None
    workspace: str | None = None


def _cert_fingerprint(runner, cert_path: Path) -> str:
    proc = runner.run(["openssl", "x509", "-in", str(cert_path), "-noout", "-fingerprint", "-sha256"], timeout=10)
    return proc.stdout.strip().split("=", 1)[1]


def _generate_ephemeral_cert(runner, cert_path: Path, key_path: Path) -> None:
    """Self-signed, 1-day TLS cert for the answer server - generated
    fresh per install so a human never has to run openssl by hand and
    paste paths into a form just to click a drive."""
    proc = runner.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "1", "-nodes",
        "-subj", "/CN=baseline-self-installer",
        "-keyout", str(key_path), "-out", str(cert_path),
    ], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"generating ephemeral TLS cert failed: {proc.stderr.strip()}")


def _locate_proxmox_source_iso(runner) -> Path | None:
    for candidate in DEFAULT_SOURCE_ISO_SEARCH_PATHS:
        if runner.path_exists(candidate):
            return candidate
    return None


def build_and_write_self_installer(
    *,
    device_path: str,
    device_min_size_bytes: int,
    pds_runner,
    acquire_runner,
    answer_runner,
    iso_builder_runner,
    install_runner,
    workspace: Path,
    repo_root: Path,
    assistant_binary: Path,
    expected_serial: str | None = None,
    proxmox_source_iso: Path | None = None,
    server_host: str = DEFAULT_SERVER_HOST,
    cert_path: Path | None = None,
    key_path: Path | None = None,
    server_port: int = 8443,
    fqdn: str = "baseline.local",
    lvm_maxroot: int = 5,
    lvm_maxvz: int = 30,
    lvm_swapsize: int = 2,
    target_mac: str | None = None,
    target_dmi_product: str | None = None,
    memory_mb: int = 3072,
    on_progress=None,
    admin_password: str | None = None,
) -> SelfInstallerResult:
    """The real, composed pipeline. Every stage's own real postcondition
    checks (acquire's hash chain, prepare_iso_defensively's byte scan,
    build_current_iso's provision.sh-reachability check) still run -
    this function adds no new trust of its own, it only sequences
    already-verified stages and stops at the first failure.

    `on_progress` (direct instruction, 2026-09-29 - "add a console log
    of what is running and doing"): an optional `str -> None` callback,
    called once per real stage with a short, honest description of
    what's actually happening right now - never a fake/simulated
    progress percentage, just the real stage this call is currently
    inside. Defaults to a no-op so every existing caller/test is
    unaffected.

    `admin_password` (direct instruction, 2026-09-29 - "It has to
    accept my root password in Linux now"): when given, the new
    Proxmox install's real root password is set to this exact value
    instead of a randomly generated one-time password - the operator
    can then log into the freshly-installed Proxmox with the same
    password they already know and use on this machine, rather than
    having to go find a generated one in a progress console. This is a
    real password-reuse tradeoff (the same password now protects two
    separate systems) - accepted deliberately, by direct instruction,
    for this single-operator machine (this project's own earlier
    finding: every real account on this machine already shares one
    password). When omitted (the default), the prior random-one-time-
    password behavior is unchanged - existing callers/tests are
    unaffected."""
    progress = on_progress or (lambda line: None)
    # 1. Safety gate - real device validation before anything else.
    progress(f"Validating {device_path} is a real, safe, non-boot target...")
    try:
        pds.validate_target_device(
            device_path, expected_serial=expected_serial,
            min_size_bytes=device_min_size_bytes, runner=pds_runner,
        )
    except pds.PhysicalDeviceSafetyError as exc:
        return SelfInstallerResult("refused", f"device safety check failed: {exc}")
    # A second, independent data-protection check (the web layer already made one): a drive that holds data and
    # has no installer-generated UUID is never installed over. No option relaxes it.
    import drive_guard
    try:
        drive_guard.require_may_format(
            device_path, run=lambda argv: (0, pds_runner.run(argv)) if pds_runner is not None else drive_guard._default_run(argv))
    except drive_guard.DataProtectionError as exc:
        return SelfInstallerResult("refused", str(exc))
    except Exception as exc:  # noqa: BLE001 - failing to look means "unknown", which protects the drive
        return SelfInstallerResult("refused", f"refused: could not check whether {device_path} holds data: {exc}")

    # The real hardware serial of the *selected* drive - used to target
    # the unattended install at the right disk (filter.ID_SERIAL_SHORT).
    # Independent of `expected_serial`, which is an opt-in extra
    # restriction on top of the safety gate, not a value a human should
    # ever type in: the drive was already chosen by clicking it.
    disk_serial = pds.get_device_serial(pds_runner, device_path)
    if not disk_serial:
        return SelfInstallerResult("refused", f"{device_path} reports no hardware serial - cannot target the automated install at it safely")
    progress(f"Target confirmed: {device_path} (serial {disk_serial})")

    workspace = Path(workspace)
    acquire_runner.makedirs(workspace)

    if proxmox_source_iso is None:
        progress("Looking for a cached Proxmox source ISO (no internet needed if one is already cached)...")
        proxmox_source_iso = _locate_proxmox_source_iso(answer_runner)
        if proxmox_source_iso is None:
            searched = ", ".join(str(p) for p in DEFAULT_SOURCE_ISO_SEARCH_PATHS)
            return SelfInstallerResult("refused", f"no Proxmox source ISO found in any of: {searched}")
    progress(f"Using cached Proxmox source ISO: {proxmox_source_iso}")

    if cert_path is None or key_path is None:
        cert_path = workspace / "answer-server-cert.pem"
        key_path = workspace / "answer-server-key.pem"
        progress("Generating a fresh ephemeral TLS certificate for the answer server...")
        try:
            _generate_ephemeral_cert(answer_runner, cert_path, key_path)
        except RuntimeError as exc:
            return SelfInstallerResult("refused", str(exc))

    # 2. Acquire the real, verified assistant binary (skip if cached).
    if not acquire_runner.path_exists(assistant_binary):
        progress("Acquiring and verifying the real proxmox-auto-install-assistant package...")
        acquire_ws = workspace / "acquire"
        result = dsa.acquire_and_verify(acquire_runner, acquire_ws, **ACQUIRE_KWARGS)
        if not result.ok:
            failed = next((s for s in result.steps if not s.ok), None)
            return SelfInstallerResult("refused", f"acquiring proxmox-auto-install-assistant failed at {failed.name if failed else '?'}: {failed.detail if failed else ''}")
        progress("Extracting the verified assistant binary...")
        extract = dsa.extract_deb(acquire_runner, result.package_path, acquire_ws / "extracted")
        if not extract.ok:
            return SelfInstallerResult("refused", f"extracting assistant failed: {extract.detail}")
    else:
        progress(f"Assistant binary already present at {assistant_binary} - skipping acquisition.")

    # 3. Build the real answer file, targeting this exact drive by serial.
    progress("Building the real answer file (fqdn, disk target, LVM sizing) and the admin password...")
    import secrets
    if admin_password:
        # Direct instruction, 2026-09-29: "It has to accept my root
        # password in Linux now" - reuse the exact password the
        # operator just submitted to authorize this run as the new
        # Proxmox install's real root password, instead of generating
        # one they'd have to go find. Never echoed back - it's already
        # known to whoever just typed it. `hash_password_sha512crypt`
        # needs real `bytes` (it checks `b"\n" in password`) - a bare
        # `pw = admin_password` here previously passed a `str` straight
        # through and crashed with a real `TypeError` the moment this
        # branch was ever actually exercised.
        pw = admin_password.encode("utf-8")
        pw_display = None  # never shown - the operator already knows it
        progress("Using the password you submitted to authorize this run as the new Proxmox root password.")
    else:
        # Real bug found live, 2026-09-29: this password used to be
        # `del`d immediately after hashing - generated, baked into the
        # real Proxmox answer file as `root-password-hashed`, then
        # discarded before anyone (including the operator) ever saw
        # the plaintext. Direct instruction: the code must actually
        # tell the operator what it is. Surfaced twice - once now,
        # live, in the progress console (visible the moment it's
        # generated, not buried at the end) and again in the final
        # result's own detail text (so it survives past the console
        # history) - shown, never written to any retained file or log
        # of its own.
        #
        # Real bug found live in that very fix: `generate_one_time_
        # password()` returns `bytes` - embedding it directly in an
        # f-string rendered Python's own `b'...'` repr wrapper (quotes
        # and the `b` prefix included) as if it were part of the real
        # password. Decoded to a clean, displayable string here instead.
        pw = dsan.generate_one_time_password()
        pw_display = pw.decode("ascii")
        progress(f"Generated one-time Proxmox root password: {pw_display}  <-- write this down now, "
                  "it is shown only this once and is never saved anywhere.")
    pw_hash = dsan.hash_password_sha512crypt(pw, secrets.token_hex(8))
    # Real bug found live, 2026-09-29: this used to read
    # `disk_serial=expected_serial` - `expected_serial` is the
    # optional, usually-`None` human-override param (decision record
    # 86: "I will never fill in a serial number"), not the real,
    # already-detected device serial computed above (`disk_serial`,
    # confirmed via `pds.get_device_serial` a few lines earlier). The
    # answer file's own `filter.ID_SERIAL_SHORT` was getting the
    # literal string `"None"` baked in, which Proxmox's own installer
    # correctly refused: "Installation failed: filter did not match
    # any device" - a genuine variable-name collision, not a real
    # disk-targeting ambiguity.
    answer_toml = ANSWER_TEMPLATE.format(
        fqdn=fqdn, password_hash=pw_hash, disk_serial=disk_serial,
        lvm_maxroot=lvm_maxroot, lvm_maxvz=lvm_maxvz, lvm_swapsize=lvm_swapsize,
    )
    session_id = secrets.token_urlsafe(24)
    fingerprint = _cert_fingerprint(answer_runner, cert_path)
    url = f"https://{server_host}:{server_port}/answer/{session_id}"

    # 4. prepare_iso_defensively --fetch-from http (real hardware rule).
    progress("Preparing the install ISO with the real assistant binary (prepare-iso --fetch-from http)...")
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
    progress("Baking boot/provision.sh + the real baseline/ tree into a self-contained ISO...")
    final_iso = workspace / "baseline-self-installer.iso"
    build_result = ib.build_current_iso(
        iso_builder_runner, source_iso=answer_iso, repo_root=repo_root,
        output_iso=final_iso, workspace=workspace / "iso-build",
    )
    if not build_result.ok:
        failed = next((c for c in build_result.postconditions if not c.ok), None)
        return SelfInstallerResult("refused", f"self-contained ISO build failed at {failed.name if failed else '?'}: {failed.detail if failed else ''}")

    # 6. Launch the real automated install against the REAL device.
    #
    # Real bug found live, 2026-09-29 (decision record 113): nothing
    # here ever killed a *previous* run's own QEMU process before
    # launching a new one. A prior attempt's monitor socket file
    # surviving at this same workspace path is real, direct evidence
    # that process is (or was) still alive - confirmed live via a real
    # install whose QEMU process outlived the very ISO/answer-server
    # files it was supposedly still booting from by five minutes,
    # sitting stalled (real I/O counters essentially flat) while a
    # fresh job's own progress log claimed a new install was running.
    monitor_socket = workspace / "monitor.sock"
    if install_runner.path_exists(monitor_socket):
        progress("A previous run's install process is still using this workspace - stopping it first...")
        install_runner.kill_process_using_path(monitor_socket)

    progress(f"Launching the real automated install under QEMU against {device_path}...")
    invocation = dsi.build_sparse_install_invocation(
        target_image=Path(device_path), prepared_iso=final_iso,
        mac=target_mac or "52:54:00:ba:5e:20", smbios_product="baseline-self-installer",
        serial_log=workspace / "serial.log", memory_mb=memory_mb,
        monitor_socket=monitor_socket,
        guestfwd_host=server_host, guestfwd_port=server_port,
        target_serial=disk_serial,
    )
    process = install_runner.popen(invocation.argv, monitor_socket=monitor_socket)

    global _active_answer_server
    if _active_answer_server is not None:
        progress("A previous run's answer server is still listening - stopping it first...")
        _active_answer_server.stop()
        _active_answer_server = None

    session = dsan.SessionState(
        session_id=session_id, answer_toml=answer_toml,
        expected_mac=target_mac, expected_dmi_product=target_dmi_product, ttl_seconds=1800.0,
    )
    server = dsan.EphemeralAnswerServer(
        bind_host="0.0.0.0", bind_port=server_port,
        cert_path=str(cert_path), key_path=str(key_path), session=session,
    )
    server.start()
    _active_answer_server = server
    progress(f"Real QEMU install running, answer server listening on {server_host}:{server_port}.")

    password_note = (
        "Proxmox root password (root@pam): the same password you used to authorize this run."
        if admin_password else
        f"Proxmox root password (root@pam), shown only this once: {pw_display} ."
    )
    return SelfInstallerResult(
        "applied",
        f"Real automated install launched against {device_path} - QEMU running (PID-equivalent process "
        f"handle returned), answer server listening on {server_host}:{server_port}, screendumps/serial log "
        f"under {workspace}. {password_note} "
        f"NOT yet confirmed complete - a human or vision-capable agent must review the "
        f"final screendump before treating this drive as a proven self-installer.",
        qemu_process=process, workspace=str(workspace),
    )
