"""What the console must carry before anything is retired: every TUI feature and every installer / build manager function, with the console page that holds it.

An entry is `present` when the console source contains its evidence (a route or a marker) and a `gap` when it has none. Gaps are allowed to exist, never to be forgotten or to grow quietly: a test keeps
`tests/unit/parity_gaps.json` equal to the computed gaps, so closing one means deleting its line, and adding a feature means adding its entry. Nothing may be removed from the TUI or the installer
while it has a gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LIB = Path(__file__).resolve().parent
BIN = LIB.parent / "bin"


@dataclass(frozen=True)
class Feature:
    id: str
    source: str                 # "tui" | "installer"
    name: str
    route: str                  # the console page that carries it (or will)
    evidence: tuple | None = None   # (file in baseline/lib, text that must appear there); None = not carried yet


def F(id, source, name, route, evidence=None):
    return Feature(id, source, name, route, evidence)


W = "baseline_web.py"
FEATURES = (
    # --- the Baseline TUI (baseline/bin/baseline) ---
    F("tui.hardware.table", "tui", "Hardware overview table", "/hardware", (W, 'path.startswith("/hardware")')),
    F("tui.hardware.ids_toggle", "tui", "Show or hide hardware IDs", "/hardware"),
    F("tui.hardware.detail", "tui", "Hardware row detail", "/hardware"),
    F("tui.network.table", "tui", "Network interfaces table", "/network", (W, 'path == "/network"')),
    F("tui.network.tether", "tui", "Tether (phone) connection", "/network", (W, '"/network/tether"')),
    F("tui.network.alias", "tui", "Rename a connection", "/network"),
    F("tui.network.power", "tui", "Switch an interface on or off", "/network"),
    F("tui.network.role", "tui", "Primary and fallback connection", "/network", (W, "lifeline")),
    F("tui.sensors.table", "tui", "Sensors table", "/sensors", (W, 'path == "/sensors"')),
    F("tui.sensors.history", "tui", "Sensor history graph", "/sensors", ("sensors_view.py", "def hottest_history")),
    F("tui.vms.table", "tui", "Virtual machines table", "/vms", (W, 'path == "/vms"')),
    F("tui.vms.history", "tui", "Virtual machine usage graph", "/vms", ("vm_page.py", "def with_usage")),
    F("tui.vms.start", "tui", "Start a virtual machine", "/vms", ("vm_page.py", 'if action == "start"')),
    F("tui.vms.shutdown", "tui", "Shut down a virtual machine", "/vms", ("baseline_web.py", "'request_stop'")),
    F("tui.chat.ask", "tui", "Ask the assistant", "/chat", (W, '"/chat/ask"')),
    F("tui.chat.harness", "tui", "Choose the assistant", "/chat", ("chat_page.py", "harness")),
    F("tui.chat.copy", "tui", "Copy the last answer", "/chat"),
    F("tui.console.commands", "tui", "Console commands", "/shell", (W, '"/shell/run"')),
    F("tui.proxmox.return", "tui", "Go to the Proxmox interface", "/home", ("home_page.py", "8006")),
    F("tui.refresh", "tui", "Refresh now", "/home"),
    F("tui.status_bar", "tui", "Status bar", "/home"),
    # --- the installer in the web app (already served by baseline_web) ---
    F("installer.plan", "installer", "Installer plan", "/install-plan", (W, '"/install-plan"')),
    F("installer.plan.update", "installer", "Update the plan", "/install-plan", (W, "'/install-plan/update'")),
    F("installer.plan.discovery", "installer", "Discover hardware for the plan", "/install-plan", (W, "'/install-plan/discovery'")),
    F("installer.plan.execute", "installer", "Execute the plan natively", "/install-plan", (W, "'/install-plan/execute-native'")),
    F("installer.plan.inputs", "installer", "Prepare and capture input bundles", "/install-plan", (W, "'/install-plan/prepare-inputs'")),
    F("installer.plan.app_config", "installer", "Application configuration", "/install-plan", (W, "'/install-plan/app-config'")),
    F("installer.plan.catalog", "installer", "Application catalog", "/install-plan", (W, "'/install-plan/catalog'")),
    F("installer.recipes", "installer", "Environment recipes", "/recipes", (W, '"/recipes"')),
    F("installer.readiness", "installer", "Installation readiness", "/installation-readiness", (W, '"/installation-readiness"')),
    F("installer.cache", "installer", "Installer cache", "/installer-cache", (W, '"/installer-cache"')),
    F("installer.cache.acquire", "installer", "Acquire a pinned source", "/installer-cache", (W, "'/installer-cache/acquire'")),
    F("installer.drive_admin", "installer", "Drive administration", "/drive-admin", (W, '"/drive-admin"')),
    # --- the build manager (command line only today) ---
    F("build.install.recovery", "installer", "Back up a drive before installing", "/install-plan"),
    F("build.install.wipe_install", "installer", "Install onto a drive (typed confirmation)", "/install-plan"),
    F("build.install.rebuild", "installer", "Rebuild an installed drive in place", "/install-plan"),
    F("build.install.rehearse", "installer", "Try a build on the CACHE mirror first", "/install-plan"),
    F("build.install.checkpoints", "installer", "First-boot and kiosk checkpoints", "/install-plan"),
    F("build.install.progress", "installer", "Progress and write-wear report", "/install-plan"),
    F("build.cache.offline", "installer", "Build the offline cache", "/installer-cache"),
    F("build.cache.kasm_base", "installer", "Build the Kasm base", "/installer-cache"),
    F("build.cache.os_bases", "installer", "Build the ready-made OS bases", "/installer-cache"),
    F("build.iso", "installer", "Build an installer ISO", "/install-plan"),
    F("build.drives", "installer", "Name the drives this machine builds for", "/install-plan"),
    F("managed.mode", "installer", "Managed server mode", "/managed-mode", (W, '"/managed-mode"')),
    F("managed.web_address", "installer", "Web address", "/web-address", (W, '"/web-address"')),
    F("managed.parent_vault", "installer", "Parent vault: browse and restore backups", "/managed-mode"),
    F("managed.remote_rebuild", "installer", "Remote rebuild: setup, request, approve", "/managed-mode"),
)


def carried(feature: Feature, lib=LIB) -> bool:
    if feature.evidence is None:
        return False
    name, text = feature.evidence
    try:
        return text in (Path(lib) / name).read_text()
    except OSError:
        return False


def gaps(features=FEATURES, lib=LIB) -> list:
    return sorted(f.id for f in features if not carried(f, lib))


def report(features=FEATURES, lib=LIB) -> str:
    rows = [f"{'carried' if carried(f, lib) else 'GAP    '}  {f.source:9} {f.name}  ->  {f.route}" for f in features]
    done = sum(carried(f, lib) for f in features)
    return "\n".join(rows) + f"\n\n{done} of {len(features)} carried; {len(features) - done} gaps"
