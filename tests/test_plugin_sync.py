"""Guard against drift between canonical billing code and the plugin's vendored copies.

scripts/cocm_time_tracker.py is the single source of billing truth and
mcp/cocm_billing_server.py is the canonical MCP surface. The plugin vendors
both (required so the plugin is self-contained when installed outside this
repo). If these tests fail, re-copy:
    cp scripts/cocm_time_tracker.py plugins/medsync8-billing/server/
    sed 's|Path(__file__).resolve().parents\\[1\\] / "scripts"|Path(__file__).resolve().parent|' \\
        mcp/cocm_billing_server.py > plugins/medsync8-billing/server/cocm_billing_server.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "medsync8-billing" / "server"


def test_vendored_tracker_matches_canonical():
    canonical = REPO / "scripts" / "cocm_time_tracker.py"
    assert (PLUGIN / "cocm_time_tracker.py").read_bytes() == canonical.read_bytes(), (
        "Plugin's vendored tracker has drifted from scripts/cocm_time_tracker.py."
    )


def test_vendored_server_matches_canonical_modulo_import_path():
    canonical = (REPO / "mcp" / "cocm_billing_server.py").read_text()
    expected = canonical.replace(
        'Path(__file__).resolve().parents[1] / "scripts"',
        "Path(__file__).resolve().parent",
    )
    assert expected != canonical, "canonical server lost its scripts/ path line"
    assert (PLUGIN / "cocm_billing_server.py").read_text() == expected, (
        "Plugin's vendored MCP server has drifted from mcp/cocm_billing_server.py "
        "(only the tracker import path may differ)."
    )
