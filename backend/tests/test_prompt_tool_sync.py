from __future__ import annotations

import re
from pathlib import Path

from backend.prompts import VALID_TOOLS


def test_frontend_tool_ids_match_backend_valid_tools():
    repo_root = Path(__file__).resolve().parents[2]
    prompts_js = repo_root / "frontend" / "src" / "prompts.js"
    text = prompts_js.read_text(encoding="utf-8")

    marker = "export const TOOLS = ["
    assert marker in text
    tools_block = text.split(marker, 1)[1].split("];", 1)[0]
    frontend_tools = set(re.findall(r'id:\s*"([^"]+)"', tools_block))

    assert frontend_tools == VALID_TOOLS
