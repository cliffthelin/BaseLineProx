"""The five diagnostic tools are shown, installed or not, with the manifest's own names (no tool name is hardcoded in the detection)."""
import json
from pathlib import Path

import tools_page
from inventory.collectors import tools

MANIFEST = json.loads((Path(tools.__file__).parent.parent / "tools_manifest.json").read_text())


class Result:
    def __init__(self, ok=True, out=""):
        self.ok, self.stdout, self.timed_out, self.permission_denied, self.unavailable = ok, out, False, False, False
        self.output_truncated, self.reason = False, ""


class Runner:
    def __init__(self, present):
        self.present = set(present)

    def which(self, binary):
        return f"/usr/bin/{binary}" if binary in self.present else None

    def run(self, argv, **kwargs):
        return Result(out=f"{argv[0]} 1.2.3")


def test_the_page_names_exactly_the_manifest_five_and_marks_each_installed_or_missing():
    names = [t["name"] for t in MANIFEST["tools"]]
    assert sorted(names) == sorted(tools_page.PURPOSE) and len(names) == 5
    runner = Runner({t["detect"]["binary"] for t in MANIFEST["tools"] if t["name"] != "iperf3"})
    page = tools_page.render(tools_page.gather(runner, MANIFEST)).decode()
    assert "4 of 5 installed" in page and page.count("NOT INSTALLED") == 1
    for name in names:
        assert name in page


def test_all_five_present_reads_five_of_five():
    runner = Runner({t["detect"]["binary"] for t in MANIFEST["tools"]})
    assert "5 of 5 installed" in tools_page.render(tools_page.gather(runner, MANIFEST)).decode()
