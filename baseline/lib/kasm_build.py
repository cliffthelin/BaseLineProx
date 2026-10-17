"""Building the Kasm base image: Debian 13 with Docker, Kasm's installer and its container images preloaded (operator 2026-10-16, DR260).

The base is vanilla and reproducible, so it can be carried on INSTALLER_CACHE like any other OS image. It holds no Kasm install state and no secrets:
Kasm's own installer runs at the target's first boot, so every setup generates its own passwords, keys and certificates and puts them on the volumes the
overlay design names. This module holds the pure parts: what to carry, how to trim the seeded workspace list, the scripts that run inside the guest, and the
cloud-init that prepares the image. `baseline/bin/baseline-build-kasm-base` does the downloading and drives QEMU.

Facts this rests on (read from the Kasm 1.19.0 installer, not assumed): the installer is `install.sh` with a noninteractive profile; its offline mode (given an
image archive, which may list no images) skips dependency installation and turns off the workspace registry and the update check; Postgres's data is a named
Docker volume, so it is bound to the persistent disk; images are seeded with Kasm's own `bin/utils/db_init`; `docker compose` (v2) is required.
"""
from __future__ import annotations

import re

import yaml

KASM_VERSION = "1.19.0"
LOGGING_PLUGIN_TAG = "1.1"      # the plugin release lines install.sh of this Kasm version asks for (its release/1.1 and release/1.5 branches)
NETWORK_PLUGIN_TAG = "1.5"
IMAGE_TAG = KASM_VERSION                     # the static tag; the seed list's own `-rolling-daily` names are rewritten to it, so nothing is pulled at run time
BUNDLE = f"kasm_release_{KASM_VERSION}.tar.gz"
DOWNLOAD_BASE = "https://kasm-static-content.s3.amazonaws.com"
SERVICE_IMAGES = ("postgres", "api", "manager", "agent", "kasm-guac", "rdp-gateway", "rdp-https-gateway", "proxy")     # install.sh's own service list for 1.19.0
# What a fresh setup can launch without internet, as the user's choices rather than as images: the same Docker image can be offered twice, once with its own
# persistent profile and once without (a temporary browser). VS Code and Chrome are two of the five default applications. Kasm warns against sharing a profile
# directory between workspaces, and each entry below has its own image_id, so each keeps its own. The seed list is trimmed to exactly these, so nothing Kasm
# offers fails for want of an image.
WORKSPACES = (
    {"key": "browser-temporary", "image": "chrome", "friendly_name": "Browser (temporary)", "persistent": False},
    {"key": "browser-personal", "image": "chrome", "friendly_name": "Browser (personal)", "persistent": True},
    {"key": "development-desktop", "image": "ubuntu-noble-desktop", "friendly_name": "Development desktop", "persistent": True},
    {"key": "vs-code", "image": "vs-code", "friendly_name": "VS Code", "persistent": True},
    {"key": "firefox", "image": "firefox", "friendly_name": "Firefox", "persistent": True},
    {"key": "terminal", "image": "terminal", "friendly_name": "Terminal", "persistent": False},
)
PROFILE_PATH = "/mnt/kasm_profiles/{user_id}/{image_id}"        # a person's profiles together (Kasm's own documented example); not shared between workspaces
GUEST_PACKAGES = ("docker.io", "docker-compose", "lsof", "jq", "curl", "openssl", "ca-certificates", "qemu-guest-agent", "iptables", "fuse3")
KASM_UID = KASM_GID = 6500       # fixed in the base: files on the persistent admin disk are owned by this number, so it must mean the same on every root
ADMIN_DISK_SERIAL, PROFILES_DISK_SERIAL = "baseline-kasm-admin", "baseline-kasm-prof"      # virtio serials are 20 characters at most


class KasmBuildError(RuntimeError):
    pass


def workspaces_from_list(entries) -> tuple:
    """The workspaces the base carries: the supported-OS list's Kasm entry when it names them (DR262), else this module's default set. A change here is a change to
    what the base holds, so it takes effect when the base is rebuilt."""
    for entry in entries or []:
        if entry.get("kind") == "kasm" and entry.get("workspaces"):
            return tuple(dict(w) for w in entry["workspaces"])
    return WORKSPACES


def image_ref(name: str, tag: str = IMAGE_TAG) -> str:
    return f"kasmweb/{name}:{tag}"


def carried_images(workspaces=WORKSPACES) -> list:
    """The distinct Docker images to preload, in order (two workspace entries may share one)."""
    seen, out = set(), []
    for w in workspaces:
        ref = image_ref(w["image"])
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def _repo(ref: str) -> str:
    return ref.split(":", 1)[0]


def _check_profile_path(path: str) -> str:
    if (not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/")
            or "{image_id}" not in path or "{user_id}" not in path):
        raise KasmBuildError("the profile path must be absolute and name both {image_id} and {user_id}")
    return path


def trim_seed_yaml(text: str, workspaces=WORKSPACES, *, profile_path: str = PROFILE_PATH) -> str:
    """The seeded workspace list for a machine that carries `workspaces`: one entry each, in that order, named by the static tag that is loaded locally,
    enabled, with its own image_id, and with persistent profiles on `profile_path` only where the entry asks for them. Everything else in each record is the
    release's own."""
    profile_path = _check_profile_path(profile_path)
    data = yaml.safe_load(text)
    by_repo = {_repo(image["name"]): image for image in data["images"]}
    missing = [w["image"] for w in workspaces if f"kasmweb/{w['image']}" not in by_repo]
    if missing:
        raise KasmBuildError("the seed list does not include: " + ", ".join(missing))
    if len({w["key"] for w in workspaces}) != len(workspaces) or len({w["friendly_name"] for w in workspaces}) != len(workspaces):
        raise KasmBuildError("workspace keys and names must be unique")
    # The seed also says which user group may see each image. That section must name only images that exist (Postgres rejects it otherwise and the whole
    # seed rolls back silently), and an image with no link is visible to nobody, so it is rebuilt for exactly what is kept.
    group_of = {row["image_id"]: row["group_id"] for row in data.get("group_images", [])}
    for w in workspaces:
        if by_repo[f"kasmweb/{w['image']}"]["image_id"] not in group_of:
            raise KasmBuildError(f"the release does not put {w['image']} in a user group, so no one could see it")
    kept, links = [], []
    for position, w in enumerate(workspaces):
        original = by_repo[f"kasmweb/{w['image']}"]
        entry = dict(original)
        entry["name"] = image_ref(w["image"])
        entry["friendly_name"] = w["friendly_name"]
        entry["image_id"] = "${uuid:image_id:%d}" % (1000 + position)            # unique per entry, so two entries on one image keep separate profiles
        entry["enabled"] = True
        entry["hidden"] = False
        entry["persistent_profile_path"] = profile_path if w["persistent"] else None
        kept.append(entry)
        links.append({"image_id": entry["image_id"], "group_id": group_of[original["image_id"]]})
    data["images"] = kept
    data["group_images"] = links
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def prepare_script(service_refs: list, workspace_refs: list) -> str:
    """Runs once inside the build VM (as root, from cloud-init). Progress goes to the serial console so the builder can follow it."""
    pulls = "\n".join(f"pull {ref}" for ref in [*service_refs, *workspace_refs])
    return f'''#!/bin/bash
set -euo pipefail
exec > >(tee /dev/ttyS0) 2>&1
# a failure must stop the build at once and say so, not leave a half-prepared VM running until the builder's timeout
trap 'echo "PREPARE-FAILED at line $LINENO"; sleep 2; poweroff' ERR
echo "PREPARE-START"
mkdir -p /mnt/payload /opt/kasm-installer/seed /opt/kasm-installer/offline
mount -o ro LABEL=KASMPAYLOAD /mnt/payload
tar -xf /mnt/payload/{BUNDLE} -C /opt/kasm-installer
cp /mnt/payload/default_images_amd64.yaml /opt/kasm-installer/seed/default_images_amd64.yaml
# the users Kasm's installer would create on the root: made here with fixed numbers, so a fresh root has them and ownership on the persistent disk is stable
groupadd -g {KASM_GID} kasm
useradd -u {KASM_UID} -g {KASM_GID} -M -s /usr/sbin/nologin kasm
useradd -u 70 -M -s /usr/sbin/nologin kasm_db
systemctl enable --now docker
docker compose version
pull() {{
    echo "Pulling $1"
    docker pull --quiet "$1" >/dev/null
    echo "IMAGE-DIGEST $1 $(docker image inspect --format '{{{{index .RepoDigests 0}}}}' "$1")"
}}
{pulls}
# Kasm's installer runs at first boot in its offline mode (which also turns off the registry and the update check) against images that are already loaded,
# so it is handed an archive that lists no images.
mkdir -p /tmp/offline/service_images
: > /tmp/offline/service_images/images.txt
tar -czf /opt/kasm-installer/offline/service_images.tar.gz -C /tmp/offline service_images
rm -rf /tmp/offline
# the two Docker plugins Kasm's installer would fetch from the registry (log driver and sidecar network): installed here, packed the way its offline mode
# unpacks them, then removed again so the base itself holds none of Kasm's install state
for spec in "kasmweb/logger kasmweb/kasm-logging-plugin amd64-{LOGGING_PLUGIN_TAG}" "kasmweb/sidecar kasmweb/kasm-network-plugin amd64-{NETWORK_PLUGIN_TAG}"; do
    set -- $spec
    docker plugin install --alias "$1:$3" "$2:$3" --grant-all-permissions >/dev/null
    docker plugin disable "$1:$3" >/dev/null
done
systemctl stop docker docker.socket
tar -czf /opt/kasm-installer/offline/plugins.tar.gz -C /var/lib/docker/plugins .
systemctl start docker
for p in $(docker plugin ls --format '{{{{.Name}}}}'); do docker plugin rm -f "$p" >/dev/null; done
echo "PLUGINS-PACKED $(stat -c %s /opt/kasm-installer/offline/plugins.tar.gz)"
docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}} {{{{.Size}}}}'
systemctl enable baseline-kasm.service
# make the image generic: no machine id, host keys or cloud-init state, so every setup is its own machine
systemctl stop docker docker.socket
apt-get clean
rm -rf /var/lib/apt/lists/* /var/log/journal/* /var/log/*.log /root/prepare-kasm.sh
cloud-init clean --logs --seed
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
sync
echo "PREPARE-DONE"
poweroff
'''


_DISKS = f'''#!/bin/bash
# Brings up the two persistent disks by serial (never by device letter): platform state on the admin disk, user profiles on the personal one.
# A disk is formatted only when it is blank (a recognised filesystem means it is not, and neither does anything but zeros in its first MiB).
set -euo pipefail
ensure() {{
    local serial="$1" label="$2" mnt="$3" dev="/dev/disk/by-id/virtio-$1"
    [ -e "$dev" ] || {{ echo "disk $serial is not attached; nothing is started on an empty $mnt" >&2; return 1; }}
    if ! blkid -o value -s TYPE "$dev" >/dev/null 2>&1; then
        cmp -n 1048576 "$dev" /dev/zero >/dev/null 2>&1 || {{ echo "$serial holds data this does not recognise; refusing to format it" >&2; return 1; }}
        mkfs.ext4 -q -L "$label" "$dev"
    fi
    mkdir -p "$mnt"
    mountpoint -q "$mnt" || mount "$dev" "$mnt"
}}
ensure {ADMIN_DISK_SERIAL} KASM_ADMIN /opt/kasm
ensure {PROFILES_DISK_SERIAL} KASM_PROFILES /mnt/kasm_profiles
mkdir -p /opt/kasm/data/db /opt/kasm/.baseline
'''

_START = f'''#!/bin/bash
# Starts Kasm from what is on the persistent disks and the images in the base, and touches no network. Kasm's own bin/start also pulls images on every start
# and needs things the installer made on the root; the root is disposable (a rebuilt or reset OS starts fresh), so those are made again here:
# the `kasm` user comes with the base, then the Docker network, then Postgres's data volume bound to the admin disk. Docker's record of that volume is on
# the root; the data is not.
set -euo pipefail
id -u kasm >/dev/null
docker network inspect kasm_default_network >/dev/null 2>&1 || docker network create --driver=bridge kasm_default_network >/dev/null
docker volume inspect kasm_db_{KASM_VERSION} >/dev/null 2>&1 || \\
    docker volume create --driver local --opt type=none --opt o=bind --opt device=/opt/kasm/data/db kasm_db_{KASM_VERSION} >/dev/null
export KASM_UID="$(id -u kasm)" KASM_GID="$(id -g kasm)"
cd /opt/kasm/current/docker
docker compose up -d
'''

_UP = '''#!/bin/bash
# Boot driver: the disks first, then Kasm, and only when it was installed. Nothing is installed here.
set -euo pipefail
/usr/local/sbin/baseline-kasm-disks
systemctl start docker
if [ -f /opt/kasm/.baseline/installed.json ]; then
    /usr/local/sbin/baseline-kasm-start
fi
'''

_INSTALL = f'''#!/bin/bash
# Runs once, started from the host through the guest agent, with the secrets on STDIN (KEY=VALUE lines). The host generated them and keeps its copy in the
# vault on USER_ADMIN; nothing here writes them to disk except Kasm's own configuration on the admin disk, and nothing is echoed.
set -euo pipefail
declare -A secret
while IFS= read -r line; do
    key="${{line%%=*}}"; value="${{line#*=}}"
    case "$key" in KASM_ADMIN_PASSWORD|KASM_USER_PASSWORD|KASM_DB_PASSWORD|KASM_MANAGER_TOKEN) ;; *) echo "unexpected setting" >&2; exit 2;; esac
    [[ "$value" =~ ^[A-Za-z0-9]{{12,64}}$ ]] || {{ echo "$key must be 12 to 64 letters and digits" >&2; exit 2; }}
    secret[$key]="$value"
done
for key in KASM_ADMIN_PASSWORD KASM_USER_PASSWORD KASM_DB_PASSWORD KASM_MANAGER_TOKEN; do
    [ -n "${{secret[$key]:-}}" ] || {{ echo "$key was not given" >&2; exit 2; }}
done
[ ! -f /opt/kasm/.baseline/installed.json ] || {{ echo "already installed"; exit 0; }}
/usr/local/sbin/baseline-kasm-disks
systemctl start docker
[ -z "$(ls -A /opt/kasm/data/db 2>/dev/null)" ] || {{ echo "refusing: /opt/kasm/data/db already holds data" >&2; exit 3; }}
VOLUME=kasm_db_{KASM_VERSION}
# Kasm's installer, offline and without starting anything: its own database initialisation seeds before the stack starts.
bash /opt/kasm-installer/kasm_release/install.sh --install-profile noninteractive --accept-eula --no-start --use-static-images \\
    --admin-password "${{secret[KASM_ADMIN_PASSWORD]}}" --user-password "${{secret[KASM_USER_PASSWORD]}}" \\
    --db-password "${{secret[KASM_DB_PASSWORD]}}" --manager-token "${{secret[KASM_MANAGER_TOKEN]}}" \\
    --offline-service /opt/kasm-installer/offline/service_images.tar.gz \\
    --offline-logger-plugin /opt/kasm-installer/offline/plugins.tar.gz --offline-network-plugin /opt/kasm-installer/offline/plugins.tar.gz --skip-egress --no-swap-check --ignore-dep-failures --proxy-port 443 >/var/log/kasm-install.log 2>&1
# the carried workspaces, with persistent profiles where asked, seeded by Kasm's own tool in its local-database mode (-q false, as the installer calls it)
/opt/kasm/current/bin/utils/db_init -s /opt/kasm-installer/seed/default_images_amd64.yaml -q false -T 5432 -Q "${{secret[KASM_DB_PASSWORD]}}" -t true >>/var/log/kasm-install.log 2>&1
# db_init -i deletes and recreates the database volume with no options, so Postgres's freshly initialised data is on the disposable root by now. Carry it onto
# the admin disk and make the volume a bind onto it, before anything starts.
SOURCE="$(docker volume inspect --format '{{{{.Mountpoint}}}}' "$VOLUME")"
cp -a "$SOURCE"/. /opt/kasm/data/db/
docker rm -f kasm_db >/dev/null 2>&1 || true
docker volume rm "$VOLUME" >/dev/null
docker volume create --driver local --opt type=none --opt o=bind --opt device=/opt/kasm/data/db "$VOLUME" >/dev/null
systemctl disable kasm.service >/dev/null 2>&1 || true      # one driver: baseline-kasm-start, which pulls nothing
/usr/local/sbin/baseline-kasm-start
healthy=""
for _ in $(seq 1 120); do
    if curl -ksf https://localhost/api/__healthcheck >/dev/null 2>&1; then healthy=yes; break; fi
    sleep 5
done
[ -n "$healthy" ] || {{ echo "Kasm did not answer its health check" >&2; exit 1; }}
printf '{{"kasm_version": "{KASM_VERSION}", "installed": "%s"}}\\n' "$(date -u +%FT%TZ)" > /opt/kasm/.baseline/installed.json
echo "KASM-INSTALLED"
'''

_UNIT = '''[Unit]
Description=Bring Kasm back from its persistent disks
After=docker.service network-online.target
Requires=docker.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/baseline-kasm-up
[Install]
WantedBy=multi-user.target
'''


def guest_files() -> dict:
    """path -> (mode, content) of what the base image carries inside the guest."""
    return {
        "/usr/local/sbin/baseline-kasm-disks": ("0755", _DISKS),
        "/usr/local/sbin/baseline-kasm-start": ("0755", _START),
        "/usr/local/sbin/baseline-kasm-up": ("0755", _UP),
        "/usr/local/sbin/baseline-kasm-install": ("0700", _INSTALL),
        "/etc/systemd/system/baseline-kasm.service": ("0644", _UNIT),
    }


def build_user_data(service_refs: list, workspace_refs: list) -> str:
    files = [{"path": "/root/prepare-kasm.sh", "permissions": "0700", "owner": "root:root", "content": prepare_script(service_refs, workspace_refs)}]
    files += [{"path": path, "permissions": mode, "owner": "root:root", "content": content} for path, (mode, content) in guest_files().items()]
    config = {"disable_root": True, "ssh_pwauth": False, "package_update": True, "package_upgrade": False, "packages": list(GUEST_PACKAGES),
              "write_files": files, "runcmd": [["bash", "/root/prepare-kasm.sh"]]}
    return "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False, default_flow_style=False)
