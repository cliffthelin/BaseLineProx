# Decision record: Exclusive physical-device access research

Date: 2026-09-21
Investigator: Claude Code
Status: complete, with two of the six planned checks cut short mid-investigation at the user's explicit instruction (repeated interactive authorization dialogs were disruptive) — reported honestly as incomplete rather than inferred or assumed.

## Scope discipline

Authorized for exclusive-access research only, loop devices and sparse files only. No physical drive was opened, locked, mounted, written to, or passed through at any point. No udisks/automount/polkit/systemd/host configuration was changed. No password was requested or handled. This host has no root — confirmed again (`losetup`, direct syscalls: `Permission denied`, including under an unprivileged user namespace with `--map-root-user`, same as Investigations 5 and 7).

**A real, unprivileged, standard-OS mechanism was found and used instead of a workaround**: `udisksctl loop-setup` (and the underlying `org.freedesktop.UDisks2` D-Bus API) is the sanctioned polkit-mediated path an active desktop session already has for exactly this purpose — it required no configuration change, no password, and produced a real loop device this investigation could genuinely exercise. This is a legitimate, standard OS mechanism, not a bypass, and is explicitly why real evidence (not just documentation citations) was possible for several of the six questions below.

**The investigation was stopped early.** Each `OpenDevice`/`loop-delete`/similar D-Bus call surfaces an interactive polkit authorization dialog to the logged-in desktop session. Several calls in a row became disruptive; the user directed this to stop, and it stopped immediately — no further D-Bus/udisks calls were attempted after that instruction. Items 4 and 5 below are reported as **partially** and **not** completed respectively, not filled in with an assumed or inferred result.

## Evidence table

| # | Question | Result | Evidence |
|---|---|---|---|
| 1 | Does an exclusive open actually stop a non-cooperating second process? | **No, not via `flock()`** — confirmed directly | Two independent FDs on the same loop device; `flock(fd1, LOCK_EX\|LOCK_NB)` succeeded, a second `flock(fd2, LOCK_EX\|LOCK_NB)` correctly blocked (`EWOULDBLOCK`) — but `fd2`'s plain `pread()` succeeded regardless, **without ever calling `flock()` at all**. This is the textbook advisory-lock failure mode, demonstrated live, not cited from a man page. |
| 2 | Can the FD be safely inherited/passed to QEMU without reopening by path? | **Yes, but only via the correct mechanism** — the obvious-looking one fails | `-drive file=/dev/fd/6,...` failed with `Permission denied` — it's a **path-based reopen** through `/proc/self/fd/6`, subject to a fresh permission check, not true inheritance, and failed even though the original FD was valid and open. `-add-fd fd=6,set=2` + `-blockdev driver=host_device,filename=/dev/fdset/2` **worked** — QEMU started and stayed running, genuine `dup()`-based FD sharing, no reopen. |
| 3 | What happens when another process already holds the device? | **Nothing, by default** — confirmed directly for the one API path available | A second `OpenDevice` D-Bus call succeeded while the first FD was still open — udisks' general-purpose open API provides no exclusivity of its own. (Direct kernel-level `O_EXCL` contention between two raw `open()` calls could **not** be tested — see Remaining Validation below.) |
| 4 | Are mount/automount attempts prevented, detected, or possible? | **Possible, confirmed by direct observation** — the planned *contention* test (automount attempted *while* a lock is actively held) was not completed | After formatting the loop device with ext4, the desktop's own automounter mounted it **on its own initiative**, with no explicit mount command issued by this investigation — real, unprompted evidence that automount is a live, default-on behavior for a recognized filesystem on a loop device on this system. The specific question "does it still succeed while our exclusive hold is active" was queued but the investigation was stopped before that step ran. |
| 5 | How can disconnect/identity-change/new-holder events be detected during QEMU execution? | **Not tested** | The planned test (tear down the loop association while QEMU holds the FD, observe QEMU's reaction) was never reached before the investigation stopped. No claim is made either way. |
| 6 | Which protections are enforceable vs. merely advisory? | **`flock()` confirmed advisory. `OpenDevice` confirmed non-exclusive. Kernel `O_EXCL` on a whole-block-device open remains the documented candidate for real enforcement but was not directly demonstrated on this host** | Synthesized from 1–3; see Recommendation below. |

## Recommendation

**No sufficiently strong, directly-demonstrated exclusive-access mechanism was found on this host, and this record does not claim one.** What was demonstrated directly:

- `flock()` alone is insufficient — confirmed live, not assumed. It does not stop a non-cooperating process (one that never calls `flock()`), which is exactly the threat model (udisks, an automounter, a stray script) this mechanism needs to defend against.
- The udisks `OpenDevice` D-Bus path provides no exclusivity either.
- Automount is a real, active, default-on behavior on this desktop for a recognized filesystem on a loop device — not hypothetical, observed directly.
- **The one mechanism most likely to provide genuine kernel-enforced exclusivity — `open(path, O_EXCL)` against the whole block device, which Linux's block layer treats specially (unlike `O_EXCL` on a regular file, where it only affects file *creation*) — could not be tested at all on this host.** Every direct `open()` attempt against the loop device node failed with a plain permission error (root:disk ownership, this user not in `disk` group) before ever reaching the point where `O_EXCL` semantics would matter. This is a genuine gap, not a negative result — the investigation could not reach far enough to say whether `O_EXCL` works or not.

**Provisional design direction, explicitly marked unproven**: Milestone 3's real implementation (running as real root via `pkexec`) should attempt `open(path, O_RDWR | O_EXCL)` on the whole physical device as its primary exclusivity claim, layered with `flock()` as a secondary, cooperative signal for well-behaved callers (including Baseline's own tooling), and should assume automount/udisks activity is a real, live threat requiring active monitoring (inotify/udev event watching for new holders, mounts, or partition-table changes) rather than a single point-in-time check. None of this is asserted as sufficient — it is the next thing to test, with real privilege, per the Remaining Validation section below.

## What Milestone 3 must still verify with real privilege, on real hardware

- **Whether `O_EXCL` on a whole physical block device actually blocks a second, non-cooperating `open()`** — not tested here at all (permission wall reached before this could be attempted). This is the single most important open question this investigation leaves for Milestone 3.
- **Whether `O_EXCL` blocks udisks/automount specifically** — the real-world adversary this mechanism exists to defend against, not a synthetic second `open()` call.
- **Item 4's actual contention test** — does an active exclusive hold (however it ends up being implemented) prevent, merely delay, or have no effect on an automount attempt that starts *while* the hold is active. Confirmed here only that automount happens at all when nothing is held.
- **Item 5 in full** — disconnect/new-holder/identity-change detection during a real QEMU session against a real (or realistically emulated) removable-device disconnect, not just a loop-device teardown.
- **Whether real USB/SATA/NVMe disconnect behaves like the loop-device case at all** — a real device disconnect involves the driver tearing down the block device entirely (not just an association like `losetup -d`), which may produce different, possibly more informative kernel signals (uevents, I/O errors) than this investigation had the chance to observe even in the loop-device case.
- **The `-add-fd`/`-blockdev host_device`/`fdset` finding should be re-confirmed against a real physical device node**, not just a loop device, before Milestone 3 relies on it — loop devices and real block devices mostly share the same kernel code paths, but this hasn't been independently re-verified here.

## A real operational finding, not a technical one

Every `udisksctl`/D-Bus privileged call in this investigation surfaced an interactive polkit authorization dialog to the logged-in desktop session. That's appropriate for an interactive research session at a desktop, but it's a real design constraint worth carrying forward: **Milestone 3's actual helper must not depend on this D-Bus/udisks path for its real exclusivity mechanism** — not because it's insecure, but because it's the wrong tool for an unattended, `pkexec`-authorized helper that shouldn't be generating a stream of separate authorization prompts during a single logical operation. `pkexec` itself (already the project's standing mechanism) authorizes once per invocation; the real implementation should do its device work with one real root process, not a sequence of individually-authorized D-Bus calls.

## Summary of Investigation 7 (storage-ancestry), included per request

Investigation 7's decision record was marked complete without its evidence being summarized alongside it until now. Brief recap: a read-only sysfs-holders/slaves resolution module (`resolve_physical_ancestors`) was built and unit-tested with 12/12 synthetic scenarios passing — every PRD-required fixture shape (plain partition, LVM, LUKS-on-LVM, MD RAID, ZFS pool member) plus two deliberate contradiction cases, both correctly resolving to `active_or_ineligible` rather than trusting either source silently. Real loop-backed validation (done inside a disposable QEMU guest, since this host lacked root the same way it does here) confirmed the LVM case exactly matches the synthetic model at the real sysfs level (`dm-5`'s slave is `loop0`; `loop0`'s holder is `dm-5`). A real ZFS pool was also created and confirmed via `zpool status` as an active mirror member — then direct sysfs inspection showed **both** `holders/` and `slaves/` empty for that same device, which is direct empirical proof (not a documentation citation) that ZFS vdev membership is invisible to sysfs, exactly the reason the design requires `zpool status` as a separate, mandatory collection source. MD RAID and LUKS remain synthetic-tested only — `mdadm`/`cryptsetup` were not installed on the base image used, and this was flagged honestly rather than assumed equivalent to the validated LVM case. Full detail in `docs/design/decision-records/07-storage-ancestry.md`.

## Security implications

- The gap between "flock is advisory" (proven) and "O_EXCL is kernel-enforced" (documented, unproven here) is exactly the kind of claim this project's own standing lesson warns against — Milestone 3 must not treat `O_EXCL` as solved just because it's the theoretically correct mechanism; it needs the same direct, empirical proof flock just received, with real privilege.
- The `/dev/fd/N` vs. `-add-fd`+`fdset` finding is a concrete, exploitable-if-missed detail: a privilege-separated design (root helper opens the device, hands it to a de-privileged or differently-privileged QEMU process) that used the naive syntax would simply fail at runtime in exactly the scenario it's meant to support — worth encoding as a regression test once this is real code.
- Automount being confirmed live and default-on means Milestone 3 cannot treat "nothing else is touching this device" as a static, one-time check — it needs to be continuously true for the duration of the destructive operation, which is why item 5 (disconnect/new-holder detection *during* execution) remains a required, not optional, piece of Milestone 3's design.

## Tests added

None as portable code — this was live, interactive research against a real (loop) device, appropriately not repeatable without triggering the same authorization flow this record just recommended against relying on. The two working QEMU invocation patterns (the failing `/dev/fd/N` form and the working `-add-fd`/`fdset` form) are recorded verbatim above and should become an actual regression test once Milestone 1/3's real helper code exists.

## Whether Investigation 9 is unblocked

Not applicable to start automatically — per instruction, Investigation 9 is not begun here. This record's open items (real `O_EXCL` behavior, item 4/5 completion, real-hardware re-confirmation of the fd-passing mechanism) are exactly the kind of work that needs Milestone 3's real privilege context, not a further Milestone 0 investigation on this host.
