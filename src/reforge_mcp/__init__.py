"""
Reforge MCP - Main package.

Exports the MCP server entry point and version information.
"""

__version__ = "0.1.0"
__author__ = "Codewithaiyan"
__description__ = "MCP server that automatically cleans up messy vibe-coded repositories"

from .server import mcp, main

__all__ = ["mcp", "main", "__version__", "__author__", "__description__"]
