"""Every web application action has exactly one agent definition, Bot<Action>, that can only drive the browser."""
from pathlib import Path

import pytest

import drive_admin as da
import operations as ops

AGENTS = Path(__file__).resolve().parents[2] / ".claude" / "agents"
ACTIONS = sorted(set(ops.OPERATIONS) | set(da.ACTIONS))


def bot_name(action: str) -> str:
    return "Bot" + "".join(p.capitalize() for p in action.split("_"))


def test_there_is_a_bot_for_every_action_and_no_extra_bot():
    expected = {bot_name(a) + ".md" for a in ACTIONS}
    assert {p.name for p in AGENTS.glob("Bot*.md")} == expected


@pytest.mark.parametrize("action", ACTIONS)
def test_a_bot_has_only_browser_tools_and_the_binding_rules(action):
    text = (AGENTS / f"{bot_name(action)}.md").read_text()
    front = text.split("---")[1]
    assert f"name: {bot_name(action)}" in front
    tools = [t.strip() for t in front.split("tools:")[1].split("\n")[0].split(",")]
    assert tools and all(t.startswith("mcp__Claude_Browser__") for t in tools)
    assert not any(banned in front for banned in ("Bash", "Write", "Edit"))
    assert f"`{action}`" in text
    assert "never type, read, ask for, or store a password" in text.lower()
    assert "no shell" in text
