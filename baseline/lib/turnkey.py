"""Turnkey setup for the person who is signed in (operator, 2026-10-19: "if you do not set it up for my user then it's still not done").

For every ready-made system the build carries (and the supported-OS list names): a machine made from its base, with the owner's account (the signed-in Proxmox user, no password) and
the list's applications preset in its first-boot seed. Then every secret in the vault is granted to every machine and to Kasm, so the person's sign-ins are there without any setup of theirs.
It only adds: a machine that exists is left alone, a grant that exists is not rewritten, and one system failing does not stop the rest. The report says what was done and what was not.
"""
from __future__ import annotations

import app_catalogue
import app_environment
import prebuilt_environment as pe
import vault_grants
from app_environment import AppEnvError  # noqa: F401  (callers catch it)


def _merge(extras) -> dict:
    merged = {"write_files": [], "runcmd": [], "mounts": []}
    for extra in extras:
        for key in merged:
            merged[key].extend(extra.get(key, []))
    return merged


def resolved_plan(app, os_id, *, catalogue=None, resolve=app_catalogue.resolve) -> dict:
    """The application's plan on this system with its package found first (the publisher's own index, its SHA-256 checked before install). When the package cannot be found now (no network
    on this host, the publisher unreachable) the application is reported as not made ready, never installed unchecked."""
    catalogue = catalogue or app_catalogue.load()
    entry = catalogue.get(app)
    if entry is None:
        raise AppEnvError(f"{app} is not in the application catalogue")
    try:
        found = resolve(entry, os_id)
    except (app_catalogue.CatalogueError, OSError) as exc:
        raise AppEnvError(f"{entry['name']}: its package could not be found now ({exc})") from None
    return app_environment.plan(app, os_id, resolved=found or None, catalogue=catalogue)


def run(host, owner_user, entries, carried, os_bases_dir, *, vault_names, grants_path, create=pe.create, plan_for=resolved_plan, install_base=pe.install_base,
        owner_for=pe.owner_account) -> dict:
    report = {"created": [], "already_there": [], "failed": {}, "not_carried": [], "apps_skipped": {}, "granted_to": [], "needs_owner": False}
    vault_names = [name for name in vault_names if name != "AI_SETUP_DEFAULT"]  # AI profiles use their own explicit target grants
    have = {vm["name"] for vm in host.list_vms()}
    try:
        owner = owner_for(host, owner_user)
    except pe.OwnerUnknown:                      # the person's own account name is not known: no machine is made with a generic one; the person is asked (turnkey page)
        owner = None
        report["needs_owner"] = True
    for entry in entries if owner else []:
        ident = entry["id"]
        if entry.get("kind") == "kasm" or ident not in pe.SYSTEMS:
            continue
        if ident not in carried:
            report["not_carried"].append(ident)
            continue
        if ident in have:
            report["already_there"].append(ident)
            continue
        try:
            extras, skipped = [], {}
            if pe.SYSTEMS[ident]["seed"]:
                for app in entry.get("apps", []):
                    try:
                        extras.append(app_environment.seed_extra(plan_for(app, ident), tag=app))
                    except AppEnvError as exc:
                        skipped[app] = str(exc)[:160]
            install_base(host, ident, os_bases_dir)
            create(host, ident, ident, owner=owner, extra=_merge(extras) if extras else None)
            report["created"].append(ident)
            if skipped:
                report["apps_skipped"][ident] = skipped
        except Exception as exc:                                  # one system failing is reported, never fatal to the others
            report["failed"][ident] = str(exc)[:200]
    targets = ["kasm"] + [f"vm:{vm['name']}" for vm in host.list_vms()]
    for target in targets:
        known = set(vault_grants.granted(grants_path, target))
        for name in vault_names:
            if name not in known:
                vault_grants.grant(grants_path, target, name)
        if vault_names:
            report["granted_to"].append(target)
    return report
