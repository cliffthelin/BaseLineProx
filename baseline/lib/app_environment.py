"""One application per machine on Proxmox: a VM from the ready-made base that matches the Linux type, or an LXC container for a server (operator 2026-10-17; DR269).

The operator named six applications to run from Proxmox as their own machines, with network access to the system drives and to other servers: Claude (desktop), ChatGPT, LM Studio, Ollama, VS Code,
Spotify. Kasm already has these as workspaces; this is the Proxmox side.
- A desktop application gets a VM made from the base of its Linux type (`prebuilt_environment`): the install route comes from `app_catalogue` for THAT system (a Debian package on Debian and Ubuntu,
  Flatpak on Bazzite, pacman on Arch-family systems, and so on). The seed installs the application on first boot and starts it at login. The one account is the Proxmox user who is already signed in
  (no separate login, no password); the console signs that user straight in, so the machine runs on its own.
- A server (Ollama) gets an LXC container from the Debian template: its models are on a mount from a constant volume, it listens on the network, and the Proxmox firewall says who may reach it.
- Drives: a host folder can be passed into a VM as a virtiofs share (a directory mapping, then `--virtiofs`); a network share (NFS or SMB) is mounted at boot; the other servers are just addresses
  on the bridge. No password is ever put in a seed: an SMB share names a credentials file that lives on the machine.
Everything here builds data and command lines; nothing runs until a host calls it.
"""
from __future__ import annotations

import re

import app_catalogue as ac
import prebuilt_environment as pe

_MOUNT_POINT = re.compile(r"^/[A-Za-z0-9._/-]{1,100}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,100}$")
_EXPORT = re.compile(r"^/[A-Za-z0-9._/-]{0,150}$")
_SHARE = re.compile(r"^[A-Za-z0-9._$-]{1,60}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
_CIDR = re.compile(r"^[0-9a-fA-F:.]+(/[0-9]{1,3})?$")
HEADLESS = {"ollama"}                       # servers: no desktop, no autostart entry


class AppEnvError(ValueError):
    pass


def mount_entry(share: dict) -> list:
    """One cloud-init `mounts` row from a share: {kind: nfs|smb|virtiofs, ...}. NFS and SMB are mounted when the network is up and never stop the boot if the server is away; SMB takes a
    credentials FILE path on the machine, never a password."""
    kind, target = share.get("kind"), str(share.get("target", ""))
    if not _MOUNT_POINT.match(target) or ".." in target:
        raise AppEnvError("a share's target is an absolute folder")
    if kind == "nfs":
        if not _HOST.match(str(share.get("server", ""))) or not _EXPORT.match(str(share.get("export", ""))):
            raise AppEnvError("an NFS share needs a server name and an exported folder")
        return [f"{share['server']}:{share['export']}", target, "nfs", "defaults,_netdev,nofail,x-systemd.automount", "0", "0"]
    if kind == "smb":
        creds = str(share.get("credentials", ""))
        if not _HOST.match(str(share.get("server", ""))) or not _SHARE.match(str(share.get("share", ""))) or not _MOUNT_POINT.match(creds):
            raise AppEnvError("an SMB share needs a server, a share name and the path of a credentials file on the machine")
        return [f"//{share['server']}/{share['share']}", target, "cifs", f"credentials={creds},_netdev,nofail,x-systemd.automount,uid=1000,gid=1000", "0", "0"]
    if kind == "virtiofs":
        if not _TAG.match(str(share.get("tag", ""))):
            raise AppEnvError("a virtiofs share has a plain tag")
        return [share["tag"], target, "virtiofs", "defaults,nofail", "0", "0"]
    raise AppEnvError("a share is nfs, smb or virtiofs")


def plan(app_id: str, os_id: str, *, shares=(), resolved=None, catalogue=None) -> dict:
    """What the application's machine needs on this Linux type: the base, the route and its install script, how it is started, the mounts, and whether it is a server."""
    catalogue = catalogue or ac.load()
    if app_id not in catalogue:
        raise AppEnvError(f"{app_id} is not in the application catalogue")
    entry = catalogue[app_id]
    route, params = ac.route_for(entry, os_id)
    if route is None:
        raise AppEnvError(params)
    script = ac.install_script(entry, os_id, resolved)
    if script is None:
        raise AppEnvError(f"{entry['name']} on {os_id} comes by the {route} route, which is declared or belongs to another side, not installed in a VM at first boot")
    launch = None
    if app_id not in HEADLESS:
        launch = f"flatpak run {params['id']}" if route == "flatpak" else (ac.web_command(app_id) if route == "web" else entry.get("launch"))
        if not launch:
            raise AppEnvError(f"{entry['name']} has no command to start it")
    return {"app": app_id, "name": entry["name"], "os": os_id, "base": pe.base_name(os_id), "route": route, "script": script, "launch": launch, "headless": app_id in HEADLESS,
            "mounts": [mount_entry(s) for s in shares], "data": entry.get("data", [])}


def seed_extra(plan_: dict, *, tag: str = "") -> dict:
    """The additions to the base's first-boot seed: run the install script (logged, with a marker when it finished), start the application at login, and add the mounts. With `tag` (the
    application's name) every file is named for the application, so several applications can share one machine's seed."""
    script = plan_["script"]
    if "BASELINE_END_OF_SCRIPT" in script:
        raise AppEnvError("the install script contains the end marker")
    dash = f"-{tag}" if tag else ""
    files = [{"path": f"/var/lib/baseline/install-app{dash}.sh", "permissions": "0700", "content": script}]
    if plan_["launch"]:
        files.append({"path": f"/etc/xdg/autostart/baseline-app{dash}.desktop", "permissions": "0644",
                      "content": f"[Desktop Entry]\nType=Application\nName={plan_['name']}\nExec={plan_['launch']}\nX-GNOME-Autostart-enabled=true\n"})
        # (the base's seed already signs the owner straight in at the console, so the application starts on its own)
    if plan_.get("route") in ("deb", "apt"):          # started with the password store every machine shares, so a sign-in carried from another machine opens (signin_share.py)
        import signin_share
        files += signin_share.wrapper_files(plan_["app"])
    run = ["sh", "-c", f"mkdir -p /var/lib/baseline && sh /var/lib/baseline/install-app{dash}.sh > /var/log/baseline-install-app{dash}.log 2>&1; rc=$?; "
                       f"printf '{{\"app\": \"{plan_['app']}\", \"exit\": %s}}\\n' \"$rc\" > /var/lib/baseline/app-ready{dash}.json"]
    return {"write_files": files, "runcmd": [run], "mounts": plan_["mounts"]}


def create_vm(host, name: str, app_id: str, os_id: str, **kwargs) -> dict:
    """Make the application's VM from its base: the base's seed plus this application's additions."""
    shares = kwargs.pop("shares", ())
    resolved = kwargs.pop("resolved", None)
    chosen = plan(app_id, os_id, shares=shares, resolved=resolved)
    return pe.create(host, name, os_id, extra=seed_extra(chosen), **kwargs)


# ---- Proxmox command lines (built, not run) -------------------------------------------------------------------------------------------------------
def virtiofs_argv(node: str, vmid: int, index: int, tag: str, host_path: str) -> list:
    """Two command lines that pass a host folder into a VM: a directory mapping (cluster level) and the VM's virtiofs device. The VM then mounts it by tag."""
    if not _HOST.match(node) or not _TAG.match(tag) or not re.match(r"^/mnt/[A-Za-z0-9._/-]{1,150}$", host_path) or ".." in host_path or not 0 <= index <= 9:
        raise AppEnvError("a node name, a tag, a folder under /mnt and a device number are needed")
    return [["pvesh", "create", "/cluster/mapping/dir", "--id", tag, "--map", f"node={node},path={host_path}"], ["qm", "set", str(int(vmid)), f"--virtiofs{index}", f"{tag},cache=auto"]]


def ollama_container(vmid: int, *, hostname="ollama", template: str, models_host_path: str, allow_from: str, memory_mb=8192, cores=4, disk_gb=16, port=11434) -> dict:
    """The LXC for Ollama: created from the Debian template, its models on a mount from a constant volume, started at boot, on the bridge with the Proxmox firewall on and one rule saying who may
    reach the port. Returns {create, start, firewall (the contents of /etc/pve/firewall/<vmid>.fw)}; the install script is pushed and run with `pct exec` after it starts."""
    import pct_provision
    if not re.match(r"^/mnt/[A-Za-z0-9._/-]{1,150}$", models_host_path) or ".." in models_host_path or not _CIDR.match(allow_from) or not 1 <= port <= 65535:
        raise AppEnvError("a models folder under /mnt, an address range allowed to connect, and a port are needed")
    create = pct_provision.create_ct_argv(vmid, template, hostname=hostname, memory_mb=memory_mb, cores=cores, disk_gb=disk_gb)
    create[create.index("--net0") + 1] += ",firewall=1"
    create += ["--mp0", f"{models_host_path},mp=/models", "--onboot", "1", "--features", "nesting=0"]
    firewall = f"[OPTIONS]\nenable: 1\npolicy_in: DROP\n\n[RULES]\nIN ACCEPT -p tcp -dport {port} -source {allow_from} -log nolog\nIN ACCEPT -p icmp -source {allow_from}\n"
    return {"create": create, "start": pct_provision.start_ct_argv(vmid), "firewall": firewall}
