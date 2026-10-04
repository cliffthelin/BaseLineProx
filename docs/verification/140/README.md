# DR140 verification

Isolated source based on3dd98f9 plus scoped review fixes/AppData mapping,
implementation20c193f. Final full suite:3136 passed in125.92s. No tests skipped.
Before the review fixes, scoped DR137 probes were activated on the parent:
24 failed,1 passed. The completed earlier review evidence is retained under
136/137; this integration does not claim destructive physical verification.

Actual headless Chromium/loopback HTTP exercised discovered target selection,
two persona mappings on another synthetic enrolled disk, stage preview/export
and unenrolled target refusal with no page errors. mapping.png uses synthetic
disks. No physical data were moved or mounted by that test. Separate native
physical metadata discovery found the actual six-volume drive and correctly
refused missing AppData targets. physical-summary.json contains selected
Baseline identities only. No formatting, physical writes, mounts or operator credentials handled.

Actual ISO builder remastered the publisher Proxmox9.2 installer. Its publisher
SHA256 and both official release signatures were freshly verified. Independent
xorriso extraction matched all497 staged files. Isolated KVM CPU host/one vCPU
booted the final artifact to the Proxmox menu with no network or target disks.
The artifact is a manual installer/source package, not unattended provisioning.
Final verification notes/manifest are outside the packaging snapshot (self-hash
would be circular). ISO checksum/content/boot facts are in installer-manifest.json.

Private browser-session token, raw discovery, source snapshots, ISO and Runner
logs stay local. Other concurrent root working-tree changes, including the
production operations audit, were excluded and preserved. No physical
provisioning/firstboot or independent encrypted recovery proof is added.
