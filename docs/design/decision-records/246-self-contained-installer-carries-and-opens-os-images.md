# DR246 - The self-contained installer carries OS images and the installed system opens one

Date: 2026-10-11
Status: implemented and proven on the offline rehearsal (blank sparse disk, no network). Not run on PC401.
Follows DR245. Builds on `vm_host`, `proxmox_vm_host` and `vm_page` (the web app's VM page); nothing there was changed.

## Problem

The self-contained installer reached the Proxmox login offline, but the installed drive carried no OS to open. The
vanilla OS images live on the machine running the installer, and the installed system cannot read that disk.

## Decision

- `os_isos.py`: the installer host offers a folder of images (hard links, no space used, plus a `SHA256SUMS` computed
  there) to the installer VM as a read-only 9p share tagged `baseline-isos` (`drive_setup_install`'s `share_dir`,
  recorded in the invocation's device inventory as a share, never a drive; `no_other_drives` stays true).
- First boot gets a new step `os-isos` after `installer`: mount the share, copy each image that fits into
  `/mnt/INSTALLER_CACHE/isos` (2 GiB always left free), verifying every byte against the offered sum, then register
  `INSTALLER_CACHE` as the Proxmox ISO storage `baseline-isos` (with `template/iso` -> `../isos`, the layout Proxmox
  lists). It never stops the installation: no offer, a corrupt image or a failed registration is logged and recorded.
  Images that do not fit are skipped by name.
- `baseline-allscript-install --os-iso NAME` (repeatable). Default: every `.iso` except the Proxmox installer; the
  rehearsal defaults to the smallest.
- `tests/integration/verify_os_open.py` drives the web app's own `vm_page.perform` on the Proxmox backend
  (`create_iso`, `start`), then reads the VM's screen over its QMP socket.

## Evidence (rehearsal, 2026-10-11, ISO built from this branch, no network)

- first boot log: `os-isos: registered /mnt/INSTALLER_CACHE as Proxmox ISO storage baseline-isos`,
  `os-isos: carried: jrescue-2026.08.03-amd64.iso`; 2,285,338,624 bytes, identical to the source, in about 20 s;
  `pvesm status` lists `baseline-isos` active (INSTALLER_CACHE volume 54 GB).
- `vm_page.perform` `create_iso` and `start`: both `ok`; `host.status`: running; `qm status`: running.
- the VM's screen, read over QMP after the settle time: 67.9% of sampled pixels non-black. The image itself was not
  viewed; this proves the OS shows a display, not which screen.

## Findings along the way

- Proxmox's VM page names an image by its storage volume (`baseline-isos:iso/<file>`), not a file name; the harness
  resolves it.
- `qm monitor` does not work with piped input; QMP over `/var/run/qemu-server/<vmid>.qmp` does.

## Not done

- Applications with overlays. The apps (`baseline-apps`) install natively into a Debian 13 or Ubuntu 24.04/26.04 guest
  from publisher packages fetched over HTTPS (DR133). Offline, that needs a carried guest base image and the exact
  application packages and guest dependencies. Not built; needs a decision on which base and which apps to carry.
- Re-establishing internet later on the machine the drive boots on. First boot already proposes DHCP and asks for
  CONFIRM; if verification fails offline it rolls back and installs from the drive's repository. A later unattended
  retry is a question of whether CONFIRM covers it (REAL-012: only a CONFIRM keystroke authorizes). Not built.
- The real PC401 run.
