"""Structural checks for Textual dashboard controls without UI dependencies."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_hardware_modal_only_shows_real_read_only_details_and_close():
    tree = ast.parse((ROOT / "baseline" / "bin" / "baseline").read_text())
    modal = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "HardwareModal")
    compose = next(node for node in modal.body if isinstance(node, ast.FunctionDef) and node.name == "compose")
    calls = [node for node in ast.walk(compose) if isinstance(node, ast.Call)]
    called_names = {node.func.id for node in calls if isinstance(node.func, ast.Name)}
    button_labels = {
        node.args[0].value for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "Button"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    assert "TabbedContent" not in called_names
    assert button_labels == {"Close"}


def test_connection_modal_disables_admin_switch_when_state_is_unknown():
    tree = ast.parse((ROOT / "baseline" / "bin" / "baseline").read_text())
    modal = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConnectionModal")
    compose = next(node for node in modal.body if isinstance(node, ast.FunctionDef) and node.name == "compose")
    switch = next(node for node in ast.walk(compose)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Switch")
    disabled = next(keyword.value for keyword in switch.keywords if keyword.arg == "disabled")
    assert "_admin_up_at_open" in ast.unparse(disabled)
    assert "None" in ast.unparse(disabled)
    save = next(node for node in modal.body if isinstance(node, ast.FunctionDef) and node.name == "run_save_and_close")
    assert "_admin_up_at_open is not None" in ast.unparse(save)


def test_network_dashboard_does_not_hide_bridge_member_probe_errors():
    tree = ast.parse((ROOT / "baseline" / "bin" / "baseline").read_text())
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BaselineApp")
    render = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == "_render_network")
    source = ast.unparse(render)
    assert "network._bridge_members(active_dev)" in source
    assert "NetworkProbeError" in source
    assert "bridge member inventory unavailable" in source
    assert "Unknown" in source


def test_tether_action_reports_the_real_outcome_before_refreshing_network():
    tree = ast.parse((ROOT / "baseline" / "bin" / "baseline").read_text())
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BaselineApp")
    run = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == "run_tether")
    source = ast.unparse(run)
    assert "result = tether.auto_tether()" in source
    assert "report_tether_result" in source
    assert "collect_network" in source

    report = next(node for node in app.body if isinstance(node, ast.FunctionDef) and node.name == "report_tether_result")
    report_source = ast.unparse(report)
    assert "result.get('ok')" in report_source or 'result.get("ok")' in report_source
    assert "result.get('stage'" in report_source or 'result.get("stage"' in report_source
    assert "self.notify" in report_source
