"""Tests for the version the package and the server report."""

import reforge_mcp
from reforge_mcp.server import mcp


def test_package_version_is_not_a_stale_literal():
    """It comes from installed metadata, so it cannot drift from pyproject."""
    assert reforge_mcp.__version__ != "0.1.0"
    assert reforge_mcp.__version__ != "0.0.0+unknown"


def test_serverinfo_reports_our_version_not_fastmcp_s():
    """FastMCP reports its own version in serverInfo when version= is unset."""
    import fastmcp

    assert mcp.version == reforge_mcp.__version__
    assert mcp.version != fastmcp.__version__
