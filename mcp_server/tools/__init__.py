"""Shared utilities for MCP tools."""

import os
import sys

# Add backend to path once (instead of in every tool module)
_backend_path = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _backend_path not in sys.path:
    sys.path.insert(0, _backend_path)


def backend_url() -> str:
    """Get the backend API URL from env or default."""
    return os.environ.get("BACKEND_URL", "http://localhost:8000")
