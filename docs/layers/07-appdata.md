# 07 · APPDATA_<PERSONA>

**Status: In progress** · [index](README.md)

Every installed application's writable layer, per persona. 20-200 GB each,
mounted `defaults,nosuid,nodev` at `/mnt/APPDATA_<PERSONA>`. Not `noexec`:
podman's image layers live in an AppData upper layer and must execute.

The rule (direct instruction, 2026-09-30): application data is personal-owned
and goes nowhere but an AppData volume or container. Scope is anything
installable that is not a driver; drivers are filtered out by
`installable_apps()`.

## Layout

```
/mnt/APPDATA_<PERSONA>/<ID>/          app home, keyed by constant ID (shape: A_C_nnnnn)
/mnt/APPDATA_<PERSONA>/<ID>/registry.db   that app's own registry
/mnt/APPDATA_<PERSONA>/by-name/<name> -> <ID>   alias only, never a mount path
```

Identifiers come from [`naming.py`](../../baseline/lib/naming.py):
`<L>_<M>_<NNNNN>`, nine characters, allocated once and never reused.

**Previews are not allocations.** The App Isolation page shows IDs from
`naming.preview()`: numbered in catalog order across the whole App cluster
(on 2026-09-30 the Caddy container previewed as `A_C_00015`, because it is the
15th app) and marked unreserved. They can change if the catalog changes.
Nothing is stored until `naming.allocate_many` runs from an explicit
provisioning step, which has not happened on any host.

## Planning only

[`appdata.py`](../../baseline/lib/appdata.py) computes mount specifications,
paths and identities. It never mounts, chowns or writes. Checks it provides:
`target_conflicts`, `cross_app_leaks`, `identifier_collisions`, and
`UnpinnedImage` for container images without a digest.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Per-app plan, registry path, owner | MVP completed | unit tests | `appdata.plan_all` |
| Constant identifier scheme | MVP completed | unit tests | `naming.py` |
| Mount options (was bare `defaults`) | MVP completed | unit tests | fixed `86f86fc` |
| App Isolation tab | MVP completed | unit tests | not re-checked in a browser after the ID rewrite |
| Volumes on any disk | On roadmap | none | the Baseline drive has no free space for partitions 7-8 ([00](00-baseline-drive.md)) |
| Applying a plan | On roadmap | none | needs an operator-authorized, destructive path like Drive Administration |
