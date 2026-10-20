"""Exercise the real CLI with an unsupported request; no host changes."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_unavailable_update_category_exits_unsuccessfully(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    config = tmp_path / "config.json"
    selection = tmp_path / "selection.json"
    config.write_text("{}")
    selection.write_text(json.dumps({"code": True}))
    env = dict(os.environ, PYTHONPATH=str(repo / "baseline" / "lib"))
    result = subprocess.run([sys.executable, str(repo / "baseline/bin/baseline-update"),
                             "--config", str(config), "--selection", str(selection)],
                            env=env, capture_output=True, text=True)
    assert json.loads(result.stdout)["not_available"] == ["code"]
    assert result.returncode == 1
