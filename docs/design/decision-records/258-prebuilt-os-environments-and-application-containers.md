# 258 - Prebuilt OS environments with interchangeable application containers (requirements; not built)

Operator, 2026-10-12, after testing PC601 on a laptop. Recorded verbatim in intent; no code exists for this yet.

## What was asked
1. After install there is a VM or CT for **Ubuntu**, with the **agreed default applications installed and configured**.
2. The **user information for the OS is in the overlay** (USER_PERSONAL / APPDATA_*, never USER_ADMIN - DR257).
3. **Every OS ISO the drive carries is spun up beforehand** and configured with the default applications.
4. Each application is available in **its own application container, interchangeable**, with **adapters** for the operating systems that
   need a helper.
5. The browser profile applies to all users, no exception (decided separately: the machine's browser window is one profile on USER_ADMIN,
   settings by Chromium managed policy; per-user profiles live under /home, which is on USER_ADMIN).

## What already exists to build on
- `application_bundle.py`: the agreed apps (vscode, spotify, chrome, chatgpt, claude) as verified, per-app bundles with recipes.
- `ubuntu_environment.py`: Ubuntu VM from a pinned cloud image, disposable root, retained /home, one authenticated admin account.
- `vm_provision.py` / `pct_provision.py`: guest creation on `session-temp`; DR257's layering (a read-only base, an overlay per user/OS on
  USER_PERSONAL or APPDATA_*, session layer in SESSION_TEMP) is designed and proven to work natively in Proxmox, not yet built.
- OS ISOs carried on INSTALLER_CACHE (storage `installer-cache`), offered at install time.

## Open decisions (answers needed before building)
1. **Which apps, which OS.** The five apps above for every OS, or per-OS lists? Ubuntu first, the rest follow the same recipe?
2. **"Spun up previously".** At build time (inside the installer VM, so the drive ships with ready bases) or at first boot on the real
   machine? Build-time is faster for the user and uses the cache; first boot is cheaper to carry. Disk impact: one prepared base per OS.
3. **Application container form.** One OCI container (Podman/Quadlet) per app exporting its display to the OS guest via an adapter (Wayland
   socket / VNC / Xpra), or the app installed inside the guest from a per-app overlay layer? "Interchangeable" suggests the first.
4. **Helper OSes.** Which of the carried images need a helper (a Windows-class guest, an installer-only live image such as the rescue
   image, a distro without a package the app needs) and what the adapter is for each.
5. **Credentials in the overlay.** The OS user account is created from USER_PERSONAL data at first run; the base image carries none.
6. **Network at build time.** Several apps are downloaded (not distro packages): build-time needs internet or the offline cache must
   carry their bundles (the cache builder already collects some).

## Not decided here
Sizes (volumes only grow when used, DR257), the overlay's association table (USER_DATA holds the association to APP_DATA per user and OS).
