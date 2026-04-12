"""Shared utilities for MCP tools."""

import os


def backend_url() -> str:
    """Get the backend API URL from env or default."""
    return os.environ.get("BACKEND_URL", "http://localhost:8000")


def init_mcp_tools(redis_client) -> None:
    """Initialize all MCP tools that require Redis. Idempotent — safe to call once at startup."""
    from mcp_server.tools.broker import init_broker
    from mcp_server.tools.session import init_session
    init_broker(redis_client)
    init_session(redis_client)
