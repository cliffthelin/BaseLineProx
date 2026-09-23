# Decision record: 5 diagnostic tools real-installed and real-tested; headless answer-file install path proven

Date: 2026-09-23
Investigator: Claude Code
Status: complete. Per direct instruction, this redefines "Milestone 1"/"Milestone 2" for the diagnostic-tools effort specifically (distinct from the drive-install Milestone 1 Gates A-F): **Milestone 1 = prove each tool can be automatically installed** (done, this record); **Milestone 2 = confirm each tool performs its general expected function after install** (also done, this record - both closed in one pass).

## What changed: the headless answer-file path, not TUI keystroke-driving

Per direct instruction ("manually walking through the installer should be avoided... populated headlessly and then simply next, next, next... applies all the settings"), this pass abandoned `tui_wizard_driver.py`'s keystroke-driven navigation for a genuinely unattended path:

1. Fetched `proxmox-auto-install-assistant` 9.2.8 directly (hash-verified against the real Packages index - `94b562ac...` matched exactly), the same version decision record 18 already validated the GPG/hash trust chain for.
2. Built a real `answer.toml` (`[global]`/`[network]`/`[disk-setup]`), validated with `validate-answer` - passed clean.
3. `prepare-iso --fetch-from iso --answer-file answer.toml` - the answer file is **embedded directly in the ISO**, not fetched over the network. This sidesteps decision record 16's guestfwd blocker entirely, since that blocker is specific to `--fetch-from http`'s network-based answer delivery - `iso` mode needs no network communication to deliver the answer at all.
4. `inspect-iso` confirmed the embedded answer (`Fetch mode: iso`, all fields present, password redacted).
5. Booted the prepared ISO: the boot menu's **default entry was "Install Proxmox VE (Automated)"** with a 5-second countdown - genuinely zero keystrokes needed. The installer ran its own verbose `INFO: progress NN% - <step>` log to completion (99% "make system bootable") and auto-rebooted.

**A real near-miss, caught and avoided, not hypothetical**: after the automated install completed and rebooted, the boot menu reappeared with "Install Proxmox VE (Automated)" as the default again with a countdown - exactly decision record 04's known defect (installer media left first in boot order silently re-entering itself against the now-installed disk). Recognized this immediately from a screendump and sent `quit` over the monitor socket before the countdown expired, rather than letting it re-run. The disk was then booted separately and safely via `build_postinstall_boot_invocation` (no CD-ROM attached, `order=c`), exactly the mechanism that function exists for.

**An unrelated, unexplained anomaly, reported honestly rather than glossed over**: partway through an earlier attempt in this same session (a different QEMU instance, since discarded), a screendump appeared to show GRUB's edit-mode displaying text that superficially resembled fragments of recent chat messages. There is no code path by which chat text could reach QEMU's keyboard input, so this is almost certainly a vision-reading misinterpretation of small, upscaled VGA-font glyphs (a known LLM failure mode: pattern-completing ambiguous visual input against what's contextually salient) rather than an actual injection event. The affected VM instance was discarded and a fresh one used for the successful run documented here; the anomaly was not reproduced and is not fully explained.

## The 5 tools: installed and functionally verified for real

Against the automated-install disk, booted with real internet access (`restrict=off`), `apt-get install -y lm-sensors nvme-cli smartmontools iperf3 ethtool` (no-subscription repo, enterprise repos removed since this test VM has no subscription) - all 5 installed cleanly (`dpkg -l` confirmed `ii` for all five). Then, individually:

| Tool | Command | Result |
|---|---|---|
| `lm-sensors` | `sensors` | `No sensors found!`, RC=1 - correct, expected outcome on QEMU virtual hardware (no lm-sensors-compatible chips exist), not a tool or install failure. |
| `nvme-cli` | `nvme list` | RC=0, empty device table - correct: the disk is virtio, not NVMe, so zero devices is the right answer, not an error. |
| `smartmontools` | `smartctl --scan-open` | RC=0, no output - correct: virtio isn't ATA/SCSI/SAT-compatible for smartctl's default scan, so no scannable devices is expected on this VM. |
| `ethtool` | `ethtool vmbr0` | Real, populated output - Speed 1000Mb/s, Auto-negotiation off, **Link detected: yes**. Functions exactly as expected. |
| `iperf3` | `iperf3 -s -1 -D` + `iperf3 -c 127.0.0.1 -t 2` | Real client/server run over loopback, 56.5 Gbits/sec, RC=0 - genuinely functional, not just "binary present." |

Also confirmed, matching PRD SS5.9's explicit requirement: `systemctl is-enabled iperf3` -> `disabled`, `systemctl is-active iperf3` -> `inactive`. The package installs a service unit but it is not running or enabled by default - exactly the required state.

The three "no hardware found" results (sensors/nvme/smartctl) are the **expected, correct** outcome for this environment, not partial failures - PRD SS5.9a explicitly requires every collector to produce a clean `available: false` result on exactly this kind of minimal VM, and that is what happened at the raw-tool level (the normalized `diagnostics.py` collector module itself still doesn't exist - see below).

## What this does and doesn't prove

**Proven**: all 5 tools install cleanly via normal `apt-get` against a real, automated-install Proxmox VE 9.2 system; each runs and produces a sane result (populated where hardware exists, clean-empty where it doesn't); `iperf3` is safely disabled/inactive by default. The headless `--fetch-from iso` install path works end-to-end on real tooling, is faster and far more reliable than TUI keystroke-driving, and doesn't depend on decision record 16's still-unresolved guestfwd blocker.

**Not proven, not attempted**: PRD SS5.9a's actual `baseline/lib/diagnostics.py` collector module (structured JSON output, `Runner`-injectable, unit-tested) still does not exist - this record verified the underlying tools work, which is the module's foundation, but not the module itself. Self-tests (`smartctl -t short/long`) were deliberately not run, matching PRD SS5.9a's requirement that they stay a separate, explicitly operator-initiated action. `sensors`/`nvme`/`smartctl` were only exercised in the "no hardware" case - real populated output for those three remains unverified (needs real corresponding hardware, e.g. a real NVMe-backed QEMU target or real physical hardware).

## Cleanup

QEMU shut down via the real monitor-socket `quit` command (not killed). Disk image and screendump/serial captures deleted or checked for the test password before deletion (none found). `prepared-diag.iso` (1.7GB) and the raw `Packages` index deleted; the extracted `proxmox-auto-install-assistant` binary and `answer.toml` template kept (4.7MB) since they're immediately reusable for the next headless test. No push to `cliffthelin/baseline`, no physical device, no host package installation, no privilege escalation.
