# DR247 - Retry only the network change the person confirmed, until the connection verifies

Date: 2026-10-11
Status: implemented; mechanism proven on the offline rehearsal VM, success path proven only by unit tests.
Follows DR245/DR246. Decision by the operator (2026-10-11): "Yes, same change only".

## Decision

First boot confirms one network change with a CONFIRM keystroke. When it cannot verify (no cable, no DHCP yet) it rolls
back and commits offline. `network_retry.py` + `baseline-network-retry.timer` (2 min after boot, then 5 min after each
run) re-apply exactly that change until it verifies, then disable the timer. Rules, each covered by a test:

- nothing before first boot has committed; nothing once verified (by the retry, or by itself: `verified_without_change`);
- waits, changing nothing, while no physical link has carrier;
- applies only if a fresh diagnosis equals the confirmed one (mode, target, diff); otherwise records `proposal_changed`
  and leaves it for a new CONFIRM (REAL-012: only a CONFIRM keystroke authorizes);
- the existing transactional repair does the work (independent rollback armed first, target-bound verification), with
  `operator_present=False`, which also makes it refuse while anyone is connected through the affected device;
- every attempt is recorded in `/var/lib/baseline-firstboot/network-retry.json` (last 50 kept, total counted); the
  first-boot journal is never written.

## Evidence (rehearsal VM, no internet, 2026-10-11)

- `systemctl is-enabled baseline-network-retry.timer`: enabled; it ran by itself 2 minutes after boot.
- attempt 1 (timer): `applied_failed`, `rewrite_error: refusing to rewrite: interfaces config was not confidently
  parsed (duplicates={'vmbr0'} ...)` - first boot's own change was still inside its rollback window, so two `vmbr0`
  stanzas existed; the repair refused rather than stack a third. Correct and safe.
- attempt 2 (manual start): `applied_failed`, `target-bound verification failed (vmbr0 has an address but no default
  route via it); independent rollback remains armed and will restore the original config`.
- The same verification failure is what first boot itself recorded. It is the known additive-DHCP route gap on this lab
  network (DR14, DR17), not something this change introduced; it was not investigated here.

## Not proven

- A real attempt that ends `applied_ok`. Only the unit tests exercise that path (the repair is injected at the same
  seam production uses; the system probes are not mocked, but the repair result is supplied).
