"""The navigation as nested categories, one tree for the installer / build manager and the Baseline web console.

A group holds pages and, where a topic has parts of its own, a sub-group (the Installer holds a Server managed group). The flat list of pages is derived from the tree, so a page can never be
reachable in one and missing from the other.
"""
from __future__ import annotations

# (label, [ (path, label) | (label, [ ... ]) ])
TREE = (
    ("Home", (("/home", "Home"), ("/launcher", "Launcher"))),
    ("Machine", (
        ("/hardware", "Hardware"), ("/sensors", "Sensors"), ("/network", "Network"), ("/audio", "Audio and Bluetooth"),
        ("/power", "Power"), ("/memory", "Memory and swap"), ("/drive-admin", "Drive Administration"))),
    ("Workloads", (
        ("/vms", "Virtual machines"), ("/workspaces", "Workspaces"), ("/containers", "Distro containers"), ("/environments", "Environments"),
        ("/workloads", "Workload jobs"), ("/app-isolation", "App Isolation"), ("/ceph", "Ceph"))),
    ("Tools", (("/chat", "Chat"), ("/shell", "Console"), ("/tools", "Diagnostic tools"), ("/ai-setup", "AI providers"))),
    ("Security and access", (
        ("/vault", "Vault"), ("/security", "Two-factor"), ("/operators", "Operators"), ("/approvals", "Approvals"),
        ("/audit", "Audit"), ("/remote-access", "Remote access"))),
    ("Recovery and backup", (("/recovery", "Recovery"),)),
    ("Settings", (("/settings", "Settings"), ("/admin", "Admin"), ("/operations", "Operations"), ("/master-config", "Master Config"))),
    ("Installer", (
        ("Plan and build", (("/install-plan", "Installer plan"), ("/install-plan?display=desktop", "Installer desktop"),
                            ("/recipes", "Environment recipes"), ("/installation-readiness", "Installation readiness"))),
        ("Cache", (("/installer-cache", "Installer Cache"),)),
        ("Server managed", (("/managed-mode", "Managed server mode"),)))),
)


def is_page(entry) -> bool:
    return isinstance(entry[0], str) and entry[0].startswith("/")


def flatten(tree=TREE) -> tuple:
    out = []

    def walk(entries):
        for entry in entries:
            if is_page(entry):
                out.append(entry)
            else:
                walk(entry[1])
    for _, entries in tree:
        walk(entries)
    return tuple(out)


def active_group(active_path: str, tree=TREE):
    """The label of the top-level group holding the page being viewed, or None."""
    for label, entries in tree:
        if any(active_path.startswith(path) for path, _ in flatten(((label, entries),))):
            return label
    return None
