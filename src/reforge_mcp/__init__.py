"""
Reforge MCP - Main package.

Exports the MCP server entry point and version information.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("reforge-mcp")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+unknown"

__author__ = "Codewithaiyan"
__description__ = "MCP server that automatically cleans up messy vibe-coded repositories"

from .server import main, mcp

__all__ = ["__author__", "__description__", "__version__", "main", "mcp"]
