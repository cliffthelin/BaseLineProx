# DR133 — Native five-application builds and retained Debian OS rebuild

2026-10-03. Accepted, partial rows74/76 and59/60; follows DR132.

The shared `application_bundle.py` and `baseline-apps` CLI implement exact-source
prepare/acquire/verify, native payload install, per-app private-home launch,
stopped backup/restore, approved configuration capture/apply, suite composition,
explicit platform retargeting, suite rebuild and desktop launcher generation.
Supported targets are Ubuntu24.04/26.04 and Debian13 amd64; actual integration
below covers Ubuntu24.04.5 and Debian13.7 only. Unsupported platforms refuse.
All five use native publisher packages: VS Code, Spotify, Chrome, ChatGPT Linux
preview and Claude Desktop Linux beta. There is no AI-dependent runtime installer.

Sources are HTTPS plus SHA256, not detached publisher signatures. Native DEB
payloads are extracted without running package maintainer scripts; selected OS
APT dependencies are installed separately. This does not lock dependency bytes,
reproduce the entire OS, or promise old bytes at ChatGPT's mutable latest URL.
Generations, raw package cache and private state must have disjoint paths.
Storage-class/UUID routing is not integrated; interrupted downloads can leave an
unverified file requiring review. Do not point preparation workspace at a final
INSTALLER_CACHE volume or call incomplete downloads a verified vanilla cache.

Each app receives its own HOME/XDG paths and writable state. Bubblewrap supplies
user/PID/IPC/UTS namespaces, read-only OS/code, fresh proc/dev/tmp and an explicit
optional exchange directory. A root-owned, checked helper with a narrow userns
AppArmor exception enables nested Chromium sandboxes without --no-sandbox or a
global AppArmor disable. Private D-Bus sessions were necessary for Spotify's UI.
Optional URI permission binds only Chrome code; the browser profile is inside
the requesting app's private HOME. Own-app schemes come from publisher manifests:
vscode, spotify, codex and claude. Other schemes and file URIs refuse.
This is not distinct per-app Linux UIDs or full phone/Qubes confinement: X11,
audio and networking remain shared. Extension/update/user-home dependencies are
not all immutable. Launch exit, namespace preflight and install receipts never
infer GUI readiness or authenticated account success.

Portable native settings cover five VS Code settings and Chrome's homepage.
Spotify/ChatGPT/Claude recipe export covers Baseline scale only, explicitly marked
as launch-options coverage. Their full native state stays private. Richer native
preference extraction/apply, portable keyrings and authenticated migration remain
unimplemented; do not present scale as a native preferences backup.

TDD RED preceded implementation, including CLI argument parsing, homepage opening,
URI grants, helper updates and desktop path handling. See verification/133 for
unit results (2,979 passed) and runtime evidence; synthetic package/network/process tests are
not native application proof.

Actual disposable integration:

- All five publisher payloads rendered native windows on Ubuntu24.04.5 in a
  Proxmox9.2.2 KVM clone and on Debian13.7 in a separate KVM VM. Earlier Spotify
  black windows were failures; the private D-Bus change produced its login UI.
- Stopped, unauthenticated Ubuntu profiles were archived/restored, checked by
  regular-file contents and retained identity, and reopened with new payloads.
  Temporary IPC/Chromium singleton files and regenerated ChatGPT tmp are excluded.
- Debian's dirty OS root was replaced with a fresh verified publisher-cloud-image
  overlay. Its separate retained home was kept, grown4→16GiB and mounted by virtio
  serial. Exactly one authenticated human user retained UID1000; no guest users.
  The real suite CLI reacquired all five pinned packages and installed fresh code.
  Before launch, all five identities and30,827 retained regular files matched:
  VS Code124, Spotify4, Chrome307, ChatGPT29,734, Claude658. All five reopened.
- Actual Debian namespace probes read/write only the app home, could not see
  another private home, could not modify code and did not inherit a synthetic
  host variable. Explicit exchange was absent without a grant and present with it.
- Claude's granted URI helper opened the public ChatGPT website in its own private
  Chrome profile and opened the official native Claude action. Cross-app codex
  and file URIs returned refusal. No OAuth account was authenticated.
- Chrome's initial space-form profile argument opened a directory as a file URL;
  corrected to --user-data-dir=PATH. Crash recovery then suppressed startup pages;
  launcher now explicitly opens the validated current homepage. Both guest OSes
  reach the actual Proxmox endpoint and display its untrusted-certificate screen.
  TLS trust/identity acceptance and actual Proxmox login remain user-side work.

Capacity/failure findings are evidence, not concealed success: /tmp user quota
caused COW I/O errors; stopped clone overlay moved to disk-backed workspace, then
restarted. Clone root24→48GiB, Ubuntu root12→24GiB; physical drives were unchanged.
ChatGPT created about2.2GiB of runtime SDK state in its private home. Debian needed
UEFI. Initial clean-root bootstrap hit a CLI parser bug; fixed under RED/GREEN and
resumed the same root, without another rebuild. CLI termination kills the sandbox;
these stopped-file proofs are not graceful active-database checkpoint/power-loss
proofs. Debian GDM is active and generated application menu entries exist, but
human interactive login/Wayland/desktop audio have not been verified.

No physical deployment or physical write occurred. The Proxmox source remained
read-only behind a disposable overlay. No operator account credentials were read
or entered. Private seeds/test credentials/profiles/images remain untracked;
publication includes only source, approved settings and reviewed evidence.

Still open: rows72/73 shipped installer/physical ordinary-network build, row74
UID/access isolation and managed mounts, row76 general stack/web/durable guest
reconciliation, richer native preferences and dependency locks, rows59/60/75
active/crash-consistent recovery and row77 independent encrypted replacement.
Current INSTALL and remaining-work/queue docs are corrected in place. DR131/132
remain historical; their narrower evidence has not been rewritten.
