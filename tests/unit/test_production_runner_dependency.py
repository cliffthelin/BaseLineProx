"""Production deployment must not conceal a missing execution boundary."""
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("module,dependency", [(module, "repair") for module in [
    "vm_provision", "pct_provision", "docker_provision", "drive_admin",
    "baseline_web", "gui_brokers.clipboard", "gui_brokers.file_picker",
    "config_apply", "proxmox_detect", "vm_scripts", "persistence_pool",
    "scripts_inbox", "update_pipeline", "sensors_interval_control",
    "backup_recurring", "persist_bind_mounts", "control_panel_web",
    "recovery_mode", "backup_restore", "proxmox_vm_metrics", "quadlet",
    "config_diff", "diagnostics", "drive_installer", "config_pipeline",
    "config_crypto",
]] + [("self_installer", "drive_setup_acquire"), ("vm_scripts", "pct_provision")])
def test_missing_runner_dependency_prevents_module_loading(module, dependency):
    lib = Path(__file__).resolve().parents[2] / "baseline" / "lib"
    source = """
import importlib.abc
import sys
class MissingRepair(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == sys.argv[3]:
            raise ImportError('required production runner missing')
sys.meta_path.insert(0, MissingRepair())
sys.path.insert(0, sys.argv[1])
__import__(sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", source, str(lib), module, dependency],
                            capture_output=True, text=True)
    assert result.returncode != 0, "missing production dependency was replaced by a stub"
    assert "required production runner missing" in result.stderr
