# Baseline build walkthrough: native applications and repeatable tasks

Status: DR134, 2026-10-03. The working demonstration is disposable KVM:
Ubuntu 24.04.5 under Proxmox and Debian 13.7. No physical drive deployment
is implied. Read INSTALL.md before storage changes. No guest human account
is created; application tasks run as the named administrator.

## Inspect the actual demonstration

The local Proxmox clone is available at https://127.0.0.1:18006; its Ubuntu
VM is 100. Debian's actual desktop test display is VNC 127.0.0.1:5996.
The five native windows were verified using Xvfb; GDM and application menu
entries exist, but an interactive human GDM login is still to be verified.
Do not provide your account passwords to an agent. Sign in yourself when
ready. Account login/playback/chat and browser callback authentication are
not part of the recorded proof. Chrome reaches Proxmox's untrusted TLS
certificate screen; certificate trust remains a human setup step.

## Understand the three paths

The recipe separates unmodified publisher packages (cache), replaceable
application files (generation), and private retained homes (data). An OS
rebuild must keep the data disk and reattach it before rebuilding the suite.
A shared suite contains approved configuration and source locks, never raw
profiles, credentials, conversations or documents. A private restore uses
private backups separately. A cache is not the required source of all builds:
a missing locked package can be downloaded from its publisher.

Defaults below are paths inside a guest. They are not proof of physical
BASELINE/INSTALLER_CACHE/USER volume routing. The installer cache must be
structurally separate from user persistence. Do not bind a subdirectory of
a user volume as an installer-cache substitute. A generation is disposable;
private homes are not. A customized ISO belongs in staging/artifact storage,
not the vanilla publisher cache.

## Prepare a controller and target

Use a Python 3.12 or newer controller:

```sh
python3 -m venv tasker-env
tasker-env/bin/python -m pip install -r automation/requirements-tasker.txt
```

Deploy reviewed Baseline source using boot/provision.sh on the target. It now
carries baseline-apps, baseline-tasker, their modules, Ansible roles and docs.
Full current provision.sh execution is still unverified; the native tests
copied and checked the required source directly in disposable guests.
The role requires root-owned, non-writable source under /opt/baseline and
checks its bytes against the recipe's backend fingerprints. It refuses stale
or writable source. Ansible must have an already-authorized management route,
strict SSH host keys, and permission to become root for prerequisites and the
administrator for app files. Keep inventories and SSH keys private. The role
does not generate an administrator, configure a desktop or partition disks.

## Capture, compose and autofill

For an installed managed application, inspect its INSTALL.json and retained
private directory; capture only approved configuration:

```sh
baseline/bin/baseline-apps capture-installed GENERATION/chrome PRIVATE/chrome > chrome-capture.json
```

The capture report contains a recipe field with source/version/platform locks
and approved configuration. Use that recipe field, not the whole report, in
the applications.json array.
Repeat for the five applications, review every export, then put the recipe
objects in a JSON array named applications.json. VS Code exports five approved
settings; Chrome exports its homepage. Spotify, ChatGPT and Claude currently
export Baseline scale options only, not their complete native preferences.

```sh
baseline/bin/baseline-apps compose applications.json > suite.json
baseline/bin/baseline-apps verify-suite suite.json
baseline/bin/baseline-tasker template suite.json --with-runtime > install.json
```

The last command actually autofills an ordinary Ansible playbook. Inspect it
before use. Customize --run-as, --cache, --generation and --data when generating
the template. Defaults are baseline-admin, /var/lib/baseline-app-cache,
/var/lib/baseline-apps/generations/build-SUITE_DIGEST and
/home/baseline-admin/baseline-managed-apps. Paths must be absolute, disjoint
and free of parent traversal. Variables are literal values; arbitrary Jinja
expressions and unregistered tasks are refused. Regenerate templates after
backend updates so they carry the new source fingerprints.

A different supported Linux target uses baseline-apps retarget suite.json --os debian --release 13 before generating its playbook. This is an expected-support
mapping, not proof that the new platform works. Unsupported OSes need a real
adapter, tests and registered components; the tasker does not relabel a distro.

## Execute and inspect evidence

Create a private Ansible inventory whose host group is baseline_target. Use
Ansible's normal inventory fields for host, interpreter, SSH and become. Keep
real personal credentials out of files; follow the repository credential rules.

```sh
tasker-env/bin/python baseline/bin/baseline-tasker run install.json --inventory inventory.json --registry compatibility.sqlite --workspace run-check-1 --check
tasker-env/bin/python baseline/bin/baseline-tasker run install.json --inventory inventory.json --registry compatibility.sqlite --workspace run-install-1
baseline/bin/baseline-tasker compatibility compatibility.sqlite > compatibility.json
```

Every run needs a new workspace. Check mode never records native-install proof.
A completed real run records target OS, application version/source checksum,
component revision, backend hashes, virtualization/kernel facts and capability.
Expected compatibility is separate from observations; proven_current excludes
older component revisions. Native materialization does not mean GUI/login or
full confinement. Failed runs retain artifacts and record failure without
promoting their partial results. Interrupted runs still need explicit manual
inspection; automated restart reconciliation remains open.

An identical completed generation is inspected rather than rebuilt. Repeat
with a new workspace to test idempotence. A changed suite requires a new
generation path. Preserve the private data path and identity; do not replace
it with an empty profile during a retained-data rebuild.

## Launch and customize

Use baseline-apps launch with the application's generation directory and matching
private directory from inside the administrator's graphical session. For
explicit website/native callback access, pass --login-browser pointing to the
Chrome generation directory. This grants Chrome code, not another application's Chrome
profile. Add --share only for a deliberately selected exchange directory.
Desktop launchers can be generated into a new target directory using
baseline-apps desktop-launchers; they do not automatically grant browser access.
Shared X11, audio, network and one administrator UID are current limitations,
not phone-level confinement. Do not assume everything an app writes is durable
until stopped and backed up.

## What still prevents a complete Baseline drive build

Physical volume autodiscovery/mapping and an apply wizard, current full
provisioning/firstboot, ordinary-network management, durable app jobs and
promote/rollback, richer native preference adapters, signed/dependency locks,
cache quarantine, stronger identities/display/network isolation, and independent
encrypted replacement-device restore remain open. See queue rows72,74–77 and
59/60. The autofill delivered here is the app task template; it is not a complete
hardware installer. DR133 proves retained Debian homes across clean OS-root
replacement; it does not prove an ocean-loss/cloud replacement restore.

## Updated installer artifact

The local DR134 ISO is .runtime-proof133/installer134/baseline-134.iso.
Its publisher source was checksum/signature verified. It carries /baseline-src
with current code, Ansible collection and this walkthrough. Independent extraction
and isolated KVM boot verify content and the Proxmox menu. This is a manual
Proxmox installer: it does not automatically execute Baseline provisioning.
After an authorized target install, copy its reviewed /baseline-src tree before
following INSTALL.md and boot/provision.sh. End-to-end current provisioning is
still unverified. For unattended installs use the existing ephemeral HTTP answer
flow; never embed an operator password/hash in this ISO.
