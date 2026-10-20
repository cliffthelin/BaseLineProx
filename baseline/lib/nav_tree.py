"""The navigation as nested categories, in two modes, one tree for the installer / build manager and the Baseline console.

Simple mode is for someone who just wants things to work: plain names, only the pages that matter. Advanced mode is the full set with the technical names. Every entry carries both names; an entry
marked advanced is not shown in simple mode at all, and a group with nothing left is not shown either. The flat list of pages is derived from the tree, so a page can never be reachable in one place and
missing from another. (Inside a page, anything technical is marked `class="adv"` and hidden in simple mode by the same switch.)
"""
from __future__ import annotations

from dataclasses import dataclass

SIMPLE, ADVANCED = "simple", "advanced"


@dataclass(frozen=True)
class Page:
    path: str
    advanced: str                 # the technical name (what it has always been called)
    simple: str | None = None     # the plain name; None = the page is advanced-only
    blurb: str = ""               # one plain sentence, shown in simple mode


@dataclass(frozen=True)
class Group:
    advanced: str
    simple: str | None
    items: tuple


P = Page
TREE = (
    Group("Home", "Home", (P("/home", "Home", "Home"), P("/launcher", "Launcher", "Apps and computers", "Open an app or start a computer."))),
    Group("Machine", "This computer", (
        P("/hardware", "Hardware", "About this computer", "What this computer is made of and whether it is healthy."),
        P("/sensors", "Sensors", "Temperatures and health", "How hot things are and how the drives are doing."),
        P("/network", "Network", "Internet and network", "Whether you are online, and how."),
        P("/audio", "Audio and Bluetooth", "Sound and Bluetooth"),
        P("/power", "Power", "Power", "Sleep, shut down and restart."),
        P("/memory", "Memory and swap"),
        P("/drive-admin", "Drive Administration", "Storage drives", "See, set up and protect your drives."))),
    Group("Workloads", "Virtual computers", (
        P("/vms", "Virtual machines", "Virtual computers", "Computers that run inside this one."),
        P("/workspaces", "Workspaces", "Workspaces"),
        P("/environments", "Environments", "Ready-made setups", "A computer already set up for a purpose."),
        P("/containers", "Distro containers"),
        P("/workloads", "Workload jobs"),
        P("/app-isolation", "App Isolation"),
        P("/ceph", "Ceph"))),
    Group("Tools", "Help and tools", (
        P("/chat", "Chat", "Ask for help", "Ask the assistant."),
        P("/turnkey", "Set up for you", "Everything set up", "What was set up for you, and run it again."),
        P("/files", "Files", "Files", "Browse, upload and download files on the connected drives."),
        P("/tools", "Diagnostic tools", "Checkups", "Run a check on a part of this computer."),
        P("/ai-setup", "AI providers", "AI assistants"),
        P("/shell", "Console"))),
    Group("Security and access", "Safety and access", (
        P("/vault", "Vault", "Passwords and keys"),
        P("/security", "Two-factor", "Two-step sign-in"),
        P("/operators", "Operators", "People who can sign in"),
        P("/approvals", "Approvals", "Waiting for your approval", "Things that need a yes from you."),
        P("/remote-access", "Remote access", "Connect from elsewhere"),
        P("/audit", "Audit"))),
    Group("Recovery and backup", "Backup and restore", (P("/recovery", "Recovery", "Backup and restore", "Get things back if something goes wrong."),)),
    Group("Settings", "Settings", (
        P("/settings", "Settings", "Settings"),
        P("/web-address", "Web address", "Where Baseline is on your network", "The address you type to reach this page."),
        P("/admin", "Admin"),
        P("/operations", "Operations"),
        P("/master-config", "Master Config"))),
    Group("Installer", "Set up and build", (
        Group("Plan and build", "Plan a build", (
            P("/install-plan", "Installer plan", "Plan a build", "Choose what to put on a new drive."),
            P("/installation-readiness", "Installation readiness", "Is it ready to install?"),
            P("/install-plan?display=desktop", "Installer desktop"),
            P("/recipes", "Environment recipes"),
            P("/drive-names", "Name your drives", "Name your drives", "Which drives this computer may build."))),
        Group("Cache", None, (P("/installer-cache", "Installer Cache"),)),
        Group("Server managed", "Parent server", (P("/managed-mode", "Managed server mode", "Connect to a parent server",
                                                      "Optional. A parent keeps backups of your data and can rebuild your computers. You never need one."),)))),
)


def _visible(entry, mode) -> bool:
    if mode == ADVANCED:
        return True
    return entry.simple is not None and (isinstance(entry, Page) or any(_visible(i, mode) for i in entry.items))


def label(entry, mode) -> str:
    return entry.simple if mode == SIMPLE and entry.simple else entry.advanced


def flatten(tree=TREE) -> tuple:
    """(path, advanced name) of every page."""
    out = []

    def walk(entries):
        for e in entries:
            if isinstance(e, Page):
                out.append((e.path, e.advanced))
            else:
                walk(e.items)
    walk(tree)
    return tuple(out)


def is_page(entry) -> bool:
    return isinstance(entry, Page)


def active_group(active_path: str, tree=TREE):
    """The advanced label of the top-level group holding the page being viewed, or None."""
    for group in tree:
        if any(active_path.startswith(path) for path, _ in flatten((group,))):
            return group.advanced
    return None


def visible_in(mode: str, tree=TREE) -> list:
    """The paths shown in a mode."""
    out = []

    def walk(entries):
        for e in entries:
            if not _visible(e, mode):
                continue
            if isinstance(e, Page):
                out.append(e.path)
            else:
                walk(e.items)
    walk(tree)
    return out
