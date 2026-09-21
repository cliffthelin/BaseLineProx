# Decision record: Automated installer availability

Date: 2026-09-20
Investigator: Claude Code
Status: complete

## Host facts (actual, not assumed)

The PRD had assumed Ubuntu 26.04 in several places; the user's most recent message asserted the real development host was Ubuntu 24.04.3. Neither assumption should have stood without checking — direct evidence from this machine:

```
$ cat /etc/os-release
PRETTY_NAME="Ubuntu 26.04.1 LTS"
VERSION_ID="26.04"
VERSION_CODENAME=resolute
```

- Architecture: `x86_64`
- Kernel: `Linux 7.0.0-31-generic #31-Ubuntu SMP PREEMPT_DYNAMIC Sat Aug 1 04:26:38 UTC 2026`
- QEMU: `QEMU emulator version 10.2.1 (Debian 1:10.2.1+ds-1ubuntu3.2)`
- KVM acceleration: `/dev/kvm` present (`crw-rw----+ root kvm`), CPU reports `AMD-V`
- Free workspace capacity: 230G free on `/run/media/cane/CACHE` (where `experiments/` lives), 232G free on `/`
- `dpkg --print-architecture`: `amd64`

**Correction to the user's stated assumption**: this host is genuinely Ubuntu 26.04.1 LTS, not 24.04.3. The PRD's "26.04" language was actually accurate for this machine; no PRD correction needed on that point. If a different physical machine is the actual intended build host, its `/etc/os-release` should be checked the same way before trusting either number.

## Evidence collected

All commands below were run from `experiments/m0-inv1/` (gitignored workspace). Nothing was installed to the host; no APT sources were added; no host packages, boot configuration, or services were modified.

**1. Target Proxmox VE release / ISO**
Already established and verified earlier this session: `proxmox-ve_9.2-1.iso`, SHA256 `4e88fe416df9b527624a175f24c9aa07c714d3332afb1ee3dbf3879573ef2c6c`, 1,706,178,560 bytes. Re-confirmed via `WebFetch` against `proxmox.com/en/downloads/proxmox-virtual-environment/iso` this session — same version, same hash, currently the latest 9.x point release (9.2-1, updated 2026-05-21).

**2. Official distribution source for the ISO**
`https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso` — official Proxmox download page, direct download and torrent options listed.

**3. Official package source for `proxmox-auto-install-assistant`**
Repository: `deb http://download.proxmox.com/debian/pve trixie pve-no-subscription` (PVE 9 targets Debian 13 "trixie" per `pve.proxmox.com/wiki/Package_Repositories`).

GPG key: `https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg`, fetched over TLS this session:
```
$ curl -sS -o proxmox-archive-keyring-trixie.gpg https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg
HTTP 200
$ sha256sum proxmox-archive-keyring-trixie.gpg
136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45
```

**Note on `download.proxmox.com` TLS**: direct `https://download.proxmox.com/...` fails TLS hostname verification from this network path (`Hostname/IP does not match certificate's altnames`); the cert's SAN list only covers named regional CDN hosts (`na.cdn.proxmox.com`, `de.cdn.proxmox.com`, etc.). Those regional CDN hosts in turn returned `401 Unauthorized` on direct access (likely hotlink/referrer protection, not a security concern with the mirror itself). Plain `http://download.proxmox.com/...` (port 80) succeeded and was used for the package/index files below — **integrity was established independently via the GPG-signed `Release` file, not via transport encryption**, which is the correct trust model for an APT-style mirror in the first place (see verification below). This TLS-hostname-mismatch behavior should be re-checked from whatever machine actually runs Milestone 1+ — it may be specific to this environment's network path (a proxy or sandboxed egress), not necessarily Proxmox's mirror infrastructure.

**4. Chain-of-trust verification actually performed**

```
$ curl -sS -o Release http://download.proxmox.com/debian/pve/dists/trixie/Release
$ curl -sS -o Release.gpg http://download.proxmox.com/debian/pve/dists/trixie/Release.gpg
$ gpgv --keyring ./proxmox-archive-keyring-trixie.gpg Release.gpg Release
gpgv: Signature made Fri 18 Sep 2026 08:22:00 AM MDT
gpgv:                using RSA key 24B30F06ECC1836A4E5EFECBA7BCD1420BFE778E
gpgv: Good signature from "Proxmox Trixie Release Key <proxmox-release@proxmox.com>"
```

```
$ curl -sS -o Packages.gz http://download.proxmox.com/debian/pve/dists/trixie/pve-no-subscription/binary-amd64/Packages.gz
$ gunzip -kf Packages.gz
$ sha256sum Packages Packages.gz
70e0d43d0c53d7bfbbe29fb7a172f94384d0f5d12f1fd2d3311a43e3d349d979  Packages
2deff25830139e3450672b2efea7b4d7be98dbb2182134d48e542841341fdb40  Packages.gz
```
Both hashes match the `SHA256:` block inside the GPG-verified `Release` file exactly. Full chain: TLS-fetched keyring → GPG-verified `Release` → hash-verified `Packages` → hash-verified `.deb` (below). No step in this chain trusted an unauthenticated source.

**5. Package entry located**

Multiple versions of `proxmox-auto-install-assistant` are present in the `trixie`/`pve-no-subscription` index (9.0.6 through 9.2.8 observed). Selected the latest, 9.2.8, matching the 9.2.x family of the target ISO:

```
Package: proxmox-auto-install-assistant
Version: 9.2.8
Architecture: amd64
Source: proxmox-installer
Depends: libc6 (>= 2.39), libcrypt1 (>= 1:4.1.0), libgcc-s1 (>= 4.2), libssl3t64 (>= 3.0.0), libzstd1 (>= 1.5.5)
Recommends: xorriso
Filename: dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.2.8_amd64.deb
Size: 1074452
SHA256: 94b562ac026bf9a989e0a5834538ad24e38606f8858367af0e665af0bcbdc2e2
```

**6. Package downloaded and hash-verified against the GPG-signed index**

```
$ curl -sS -o assistant.deb http://download.proxmox.com/debian/pve/dists/trixie/pve-no-subscription/binary-amd64/proxmox-auto-install-assistant_9.2.8_amd64.deb
HTTP 200
$ sha256sum assistant.deb
94b562ac026bf9a989e0a5834538ad24e38606f8858367af0e665af0bcbdc2e2  assistant.deb
```
Exact match against the index entry above.

**7. Extracted, not installed**

```
$ mkdir -p extracted
$ dpkg-deb -x assistant.deb extracted
```
`dpkg-deb -x` extracts without touching `dpkg`'s host package database — confirmed afterward: `dpkg -l | grep proxmox-auto-install-assistant` returns nothing, `/etc/apt/sources.list.d/` has no Proxmox entry. Contents: `usr/bin/proxmox-auto-install-assistant` (3,761,280 bytes, stripped x86-64 ELF PIE), `usr/share/doc/.../{changelog.gz,copyright}`.

**8. Direct execution on the actual Ubuntu 26.04.1 host, no installation**

```
$ ldd extracted/usr/bin/proxmox-auto-install-assistant
    libzstd.so.1 => /usr/lib/x86_64-linux-gnu/libzstd.so.1
    libcrypt.so.1 => /usr/lib/x86_64-linux-gnu/libcrypt.so.1
    libcrypto.so.3 => /usr/lib/x86_64-linux-gnu/libcrypto.so.3
    libgcc_s.so.1 => /usr/lib/x86_64-linux-gnu/libgcc_s.so.1
    libc.so.6 => /usr/lib/x86_64-linux-gnu/libc.so.6
    libz.so.1 => /usr/lib/x86_64-linux-gnu/libz.so.1
$ extracted/usr/bin/proxmox-auto-install-assistant --version
proxmox-installer-common v9.2.8
$ which xorriso
/usr/bin/xorriso
```
**Every dynamic dependency resolved against the host's own existing libraries.** `xorriso` (a `Recommends`, needed for `prepare-iso`) was already present on this host. Nothing was installed to reach this state.

**9. Functional check — `validate-answer` against a synthetic answer file (no real secrets)**

```toml
[global]
keyboard = "en-us"
country = "us"
fqdn = "test.example.invalid"
mailto = "root@test.example.invalid"
timezone = "UTC"
root-password-hashed = "$6$rounds=656000$testsaltvalue$Yb...(synthetic, not a real hash)"

[network]
source = "from-dhcp"

[disk-setup]
filesystem = "ext4"
disk-list = ["sda"]
```
```
$ extracted/usr/bin/proxmox-auto-install-assistant validate-answer test-answer.toml
The answer file was parsed successfully, no errors found!
```
Confirms `root-password-hashed` is a real, accepted, mutually-exclusive alternative to plaintext `root-password` (per `--help` output and the CLI's own acceptance of a hash-shaped string with no password field present).

**10. `system-info` requires root** (read-only hardware/DMI query — errored `Are you running as root or with sudo?` when run unprivileged). Not escalated in this investigation; deferred to whichever later investigation actually needs device-match/device-info output (§7 storage-ancestry or §8 exclusive-access), since it wasn't needed to answer this investigation's questions and running anything as root wasn't necessary to establish core feasibility.

**11. Explicitly not run this investigation**: `prepare-iso` (would begin ISO preparation — out of scope per instruction: "Do not prepare or boot an installer ISO yet; that begins only after the acquisition path and trust chain are understood").

**12. Workspace/host-state check**

```
$ du -sh experiments/m0-inv1
7.2M
$ dpkg -l | grep proxmox-auto-install-assistant   # (before and after, both empty)
$ ls /etc/apt/sources.list.d/ | grep proxmox      # (before and after, both empty)
$ find /home /tmp -newer <first-downloaded-file> -type f  # nothing outside experiments/ and normal app state
```
Host package state, APT sources, and filesystem outside `experiments/m0-inv1/` are unchanged before/after.

**13. Licensing**: the assistant tool itself (`proxmox-installer` source package) ships under AGPLv3 (`extracted/usr/share/doc/.../copyright`). This covers the tool's own redistribution, not the licensing of a *prepared* Proxmox ISO produced with it — Proxmox VE's own ISO carries a mix of GPL components and Proxmox's standard VE distribution terms; redistribution of a *prepared* (answer-file-embedded) ISO to anyone outside this project wasn't evaluated here since it's out of scope for personal/internal use, but is flagged as a remaining unknown below if redistribution is ever considered.

## Result

1. **Target release/ISO**: Proxmox VE 9.2-1 (`proxmox-ve_9.2-1.iso`), already downloaded and checksum-verified earlier this session — confirmed still current.
2. **Official ISO source**: `proxmox.com/en/downloads/proxmox-virtual-environment/iso`.
3. **Official assistant source**: `download.proxmox.com/debian/pve`, `trixie`/`pve-no-subscription` component — a real Proxmox-operated APT repository, not a community mirror.
4. **Compatible assistant version**: 9.2.8 (latest available in the 9.2.x family at time of check), verified against the target ISO's major/minor series.
5. **Checksum/signature procedure**: works exactly as documented for a standard APT-style repo — GPG-signed `Release` file, hash-pinned `Packages` index, hash-pinned `.deb`. Fully reproduced and verified this session, not merely read about.
6. **Runs directly on the actual Ubuntu 26.04.1 host — no isolated Debian environment needed.** This overturns the PRD §11/§9 open risk that assumed a chroot/nspawn might be required; the extracted binary's dynamic deps are satisfied entirely by Ubuntu 26.04.1's own libraries, and `xorriso` was already present.
7. N/A — see #6.
8. Runtime deps: `libc6 >= 2.39`, `libcrypt1 >= 1:4.1.0`, `libgcc-s1 >= 4.2`, `libssl3t64 >= 3.0.0`, `libzstd1 >= 1.5.5`, all satisfied by Ubuntu 26.04.1 out of the box; `xorriso` (Recommends) already present.
9. No writes outside `experiments/m0-inv1/` were observed from extraction or the three invocations run (`--version`, `--help`, `validate-answer`).
10. Assistant tool license: AGPLv3. Prepared-ISO redistribution terms: not evaluated, not needed for personal/internal use — flagged as a remaining unknown, not a blocker.

**Significant additional finding beyond the ten questions**: `prepare-iso --fetch-from http` exists as a first-class, officially documented mode. The answer file is **not** embedded in the ISO at all in this mode — the booted installer fetches it via an HTTPS POST at boot time, optionally pinned to a specific TLS certificate fingerprint via `--cert-fingerprint`. This is materially better for PRD §7.1's "prepared ISO is itself sensitive" concern than the `--fetch-from iso` mode the PRD had implicitly assumed: an ISO prepared with `--fetch-from http` carries **no credential material at all**, shifting the secret-handling problem to a short-lived local HTTP(S) server instead of a file that has to be tracked, secured, and cleaned up. This should be the default direction for Investigation 2, not a fallback.

A second notable finding: `--on-first-boot <script>` is an official mechanism for including an executable that Proxmox's own installer runs on first boot (gated by an answer-file setting). This may be a more direct, better-supported path for staging Baseline's first-boot state machine (PRD §5.6, Investigation 6) than building an independent systemd-unit-staging mechanism from scratch — worth evaluating in Investigation 5/6 rather than assuming a from-scratch approach.

## Remaining uncertainty

- Whether the `download.proxmox.com` TLS hostname mismatch is specific to this environment's network egress or a genuine upstream cert configuration issue — re-check from the actual build host before relying on HTTPS transport to that specific hostname; the GPG-signature chain used here doesn't depend on it, so this doesn't block anything, but it's worth a clean answer.
- `system-info`/`device-info`/`device-match` behavior under root was not exercised — needed later (storage-ancestry/exclusive-access investigations), not here.
- Redistribution terms for a *prepared* (answer-file-embedded or first-boot-script-embedded) ISO, if this project ever needs to share one outside personal/internal use.
- Whether 9.2.8 is the assistant version that should be pinned long-term, or whether the PRD should track "latest 9.2.x at time of Milestone 1" — this decision record fixes 9.2.8 as the version actually tested; a version-pinning policy is a Milestone 1 concern, not decided here.

## Accepted / rejected approach

**Accepted**: acquire `proxmox-auto-install-assistant` as a standalone `.deb` from the official `trixie`/`pve-no-subscription` repository, verify it via the GPG → Release → Packages → .deb hash chain reproduced above, extract with `dpkg-deb -x` into a controlled workspace, and invoke the extracted binary directly — no `apt install`, no APT source added to the host, no isolated Debian chroot/nspawn required.

**Rejected**: adding the Proxmox APT repository to the Ubuntu host and using `apt install` — unnecessary given direct execution works, and it would violate this investigation's "do not modify APT sources" constraint for no benefit.

**Rejected (not evaluated further)**: any unreviewed community install-helper script — none were needed; the official repository and package were sufficient on the first attempt.

## Security implications

- The trust chain that matters for this whole pipeline is the GPG signature on the `Release` file, not TLS on the download itself — this should be stated explicitly in Milestone 1 tooling (verify GPG every time a package/ISO is fetched, not just once during this investigation) rather than assumed carried-forward.
- `--fetch-from http` changes the shape of PRD §7.1 considerably: it's plausible the "prepared ISO contains sensitive material" problem can be avoided almost entirely by not embedding the answer file in the ISO in the first place, serving it instead from a short-lived local server for the duration of the QEMU boot only. This should be evaluated as the primary approach in Investigation 2, not the plaintext-ISO fallback path the PRD had focused on.
- No secret material of any kind was used or generated in this investigation — only a synthetic, clearly-fake password hash in a throwaway file that was never applied to anything.

## Tests added

None yet — this investigation is research/acquisition, not implementation. The finding that `root-password-hashed` is real and functional directly informs `test_secret_handling.py` and `test_answer_file.py` from PRD §8.1, which will be written in Milestone 1 once the answer-file generation module exists.

## Whether Investigation 2 is unblocked

**Yes.** The acquisition path, trust chain, and host-compatibility questions are answered with reproduced evidence. Investigation 2 (answer-file and credential behavior) can proceed, and should prioritize evaluating `--fetch-from http` as the primary credential-delivery design given the finding above.
