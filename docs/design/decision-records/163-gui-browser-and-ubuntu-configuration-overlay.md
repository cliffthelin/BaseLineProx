# DR163 — GUI browser storage and Ubuntu configuration overlays

Date: 2026-10-05
Status: implementation and unit/native-artifact verification complete;
requested live host-GUI and Ubuntu-GUI acceptance blocked, not working-proven.

## Problem and resulting behavior

The operator requested continued work until the host GUI/browser and GUI Ubuntu
with configuration overlays both work and are tested. The Ubuntu builder exposed
Desktop/Server and homepage, but no locale configuration, and offered no native
check of the effective guest settings. The kiosk browser profile used the default
root/substrate path, and its service was omitted from the storage gate.

Ubuntu creation now validates the selected locale before allocation, writes a
versioned configuration-only overlay (desktop, locale and homepage) into cloud-init
and retained metadata, and reapplies it when rebuilding the disposable OS. The
retained home disk is kept and rebuild seeds contain no formatting command.
The GUI has locale selection. A guarded native Proxmox guest-agent action checks
configuration bytes, effective locale, actual home attachment, cloud-init result,
readiness marker, guest-agent/display-manager services and installed Firefox policy.
Missing/failed/mismatched observations refuse confirmation. Job records retain
this configuration report. The report explicitly does not claim logged-in desktop
or rendered browser-page verification. Older profiles without an explicit overlay
are refused by this new verification action; legacy rebuild behavior stays supported.
General recipe-stack/application deployment is still open under queue76.

The host Chromium kiosk uses /mnt/APPDATA_ADMIN/chromium/kiosk. Startup requires
firstboot completion plus actual storage-policy verification including APPDATA_ADMIN;
it cannot silently create its retained browser profile on root. Provisioning adds
the kiosk to the storage gate; systemd orders/requires pveproxy before opening its
homepage. The combined readiness page also checks baseline-kiosk.service. Existing
installations without the verified role/policy need storage completion before this
new kiosk gate can pass. No old private browser profile was inspected or migrated.

## Verification and scope

Tests reproduced missing configuration support, missing native verification action
and missing kiosk storage/service requirements before their implementations.
164 focused tests passed, including seed/configuration continuity, incorrect guest
observations, job persistence, VM/Proxmox adapters, kiosk/readiness/firstboot gates
and provisioning import coverage. These are fake/direct-handler evidence.

Separately, real qemu-img/qemu-io/xorriso operations passed for synthetic blank
backing images: immutable base stayed unchanged, reset removed OS-disk writes,
retained disk stayed byte-for-byte unchanged, and extracted rebuilt seed ISO
preserved locale/browser configuration. No publisher Ubuntu image or filesystem
containing user documents was used by that native artifact test. No guest booted.

Actual HTTP test failed at socket creation with EPERM. Actual Playwright Chromium
launch aborted with sandbox_host_linux.cc shutdown EPERM before page creation.
/dev/kvm and /dev/dri are absent in this execution session, as are qm/pvesh.
Current permission policy does not allow a sandbox override; no restriction was
circumvented. Browser and VM runtime acceptance requires a runtime-capable session.
Evidence is under docs/verification/163. Shell syntax/whitespace checks passed.

## Remaining acceptance

Queue72/74/75/76/78 remains open. On a runtime-capable disposable target, run the
current provision.sh and firstboot/storage gates, observe the actual Cage/Chromium
homepage, create Ubuntu Desktop through the production web application, boot and
log in with its fresh project-generated credential, observe actual Firefox page
rendering, verify the selected guest configuration, then cleanly rebuild and repeat
while checking retained user data. Finally prove the physical target cold boot.
Historical DR117 GUI proof used older source and a transient kiosk service, so it
cannot substitute for this final acceptance. No physical drive changed or operator
credential handled in this increment. INSTALL, checklist and handoff are updated;
DR117 remains append-only history.

## Update 2026-10-11 (DR257)

The host Chromium kiosk profile moved from `/mnt/APPDATA_ADMIN/chromium/kiosk` to `/mnt/USER_ADMIN/chromium/kiosk`. The kiosk browser is part of
SUBSTRATE (the publishable build); its profile holds cookies and Proxmox login tickets, which are personal data and belong on USER_ADMIN, never
in SUBSTRATE or application data. The start-up mount requirement follows (`RequiresMountsFor=/mnt/USER_ADMIN`).
