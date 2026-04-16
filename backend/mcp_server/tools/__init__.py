"""Shared utilities for MCP tools."""

import os


def backend_url() -> str:
    """Get the backend API URL from env or default."""
    port = os.environ.get("PORT", "8000")
    return os.environ.get("BACKEND_URL", f"http://localhost:{port}")


def init_mcp_tools(redis_client) -> None:
    """Initialize all MCP tools that require Redis. Idempotent — safe to call once at startup."""
    from mcp_server.tools.broker import init_broker
    from mcp_server.tools.session import init_session
    from mcp_server.tools.strategy_switch import init_strategy_switch
    init_broker(redis_client)
    init_session(redis_client)
    init_strategy_switch(redis_client)
