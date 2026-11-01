#!/usr/bin/env python3
"""The name existing MCP configs run: the server itself is aip_server.py."""

from aip_server import *  # noqa: F401,F403
from aip_server import mcp

if __name__ == "__main__":
    mcp.run()
