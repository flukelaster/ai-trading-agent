"""
SDK Client — wraps Claude Agent SDK query() for trading bot use cases.

Uses Max subscription via CLAUDE_CODE_OAUTH_TOKEN (no API key needed).
Two entry points:
  - sdk_complete(): simple prompt → text (sentiment analysis)
  - sdk_agent_loop(): multi-turn with MCP tools (trading agent)
"""

import os
import sys
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import TextBlock, ToolUseBlock
from loguru import logger

# MCP server name used in server.py — must match for allowed_tools prefix
MCP_SERVER_NAME = "trading-agent-tools"

# Path to the MCP server entry point (relative to backend/)
_MCP_SERVER_MODULE = "mcp_server.server"


def _get_mcp_server_config() -> dict:
    """Build MCP stdio server config pointing to our FastMCP server."""
    python_exe = sys.executable
    env = {
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379"),
        "MT5_BRIDGE_URL": os.environ.get("MT5_BRIDGE_URL", "http://localhost:8001"),
    }
    return {
        MCP_SERVER_NAME: {
            "command": python_exe,
            "args": ["-m", _MCP_SERVER_MODULE],
            "env": env,
        }
    }


def _mcp_tool_name(tool_name: str) -> str:
    """Convert short tool name to MCP-qualified name."""
    return f"mcp__{MCP_SERVER_NAME}__{tool_name}"


async def sdk_complete(
    prompt: str,
    system_prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_turns: int = 1,
    agent_id: str = "unknown",
) -> str | None:
    """Simple prompt → text response. No tools. For sentiment analysis."""
    from app.ai.usage_logger import log_ai_usage

    start_time = time.time()
    success = True
    usage: dict | None = None
    cost_sdk: float | None = None
    duration_ms_sdk = 0
    num_turns = 0
    stderr_lines: list[str] = []

    try:
        text_parts: list[str] = []

        async for msg in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                system_prompt=system_prompt,
                model=model,
                max_turns=max_turns,
                permission_mode="bypassPermissions",
                stderr=lambda line: stderr_lines.append(line),
            ),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                usage = getattr(msg, "usage", None)
                cost_sdk = getattr(msg, "total_cost_usd", None)
                duration_ms_sdk = getattr(msg, "duration_ms", 0) or 0
                num_turns = getattr(msg, "num_turns", 0) or 0
                if getattr(msg, "is_error", False):
                    success = False

        result = "".join(text_parts)
        if result:
            logger.info(f"SDK complete: {len(result)} chars")
        else:
            logger.warning(f"SDK complete: empty response. stderr: {''.join(stderr_lines[-5:])}")
            success = False

        await log_ai_usage(
            agent_id=agent_id,
            model=model,
            usage=usage,
            cost_usd_sdk=cost_sdk,
            duration_ms=duration_ms_sdk or int((time.time() - start_time) * 1000),
            turns=num_turns,
            tool_calls_count=0,
            success=success,
        )

        return result or None
    except Exception as e:
        logger.error(f"SDK complete error: {e}")
        if stderr_lines:
            logger.error(f"SDK stderr: {''.join(stderr_lines[-10:])}")
        await log_ai_usage(
            agent_id=agent_id,
            model=model,
            usage=usage,
            cost_usd_sdk=cost_sdk,
            duration_ms=int((time.time() - start_time) * 1000),
            turns=num_turns,
            tool_calls_count=0,
            success=False,
        )
        return None


async def sdk_agent_loop(
    prompt: str,
    system_prompt: str,
    model: str = "claude-sonnet-4-20250514",
    allowed_tools: list[str] | None = None,
    max_turns: int = 15,
    timeout: int = 120,
    agent_id: str = "unknown",
) -> dict[str, Any]:
    """Multi-turn agent loop with MCP trading tools.

    Returns dict matching run_agent_loop format:
        {response, tool_calls, turns, duration_s}
    """
    from app.ai.usage_logger import log_ai_usage

    start_time = time.time()
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    turns = 0
    cost_usd: float | None = None
    usage: dict | None = None
    duration_ms_sdk = 0
    success = True
    stderr_lines: list[str] = []

    try:
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            permission_mode="bypassPermissions",
            mcp_servers=_get_mcp_server_config(),
            stderr=lambda line: stderr_lines.append(line),
        )

        # Filter tools if specified
        if allowed_tools:
            options.allowed_tools = [_mcp_tool_name(t) for t in allowed_tools]

        async for msg in query(prompt=prompt, options=options):
            # Check timeout
            if time.time() - start_time > timeout:
                logger.warning(f"SDK agent timeout after {timeout}s")
                success = False
                break

            if isinstance(msg, AssistantMessage):
                turns += 1
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_calls.append(
                            {
                                "tool": block.name,
                                "input": block.input,
                            }
                        )
                        logger.info(f"[Agent] Tool: {block.name}")

            elif isinstance(msg, ResultMessage):
                cost_usd = getattr(msg, "total_cost_usd", None)
                usage = getattr(msg, "usage", None)
                duration_ms_sdk = getattr(msg, "duration_ms", 0) or 0
                if getattr(msg, "is_error", False):
                    success = False

        response = "".join(text_parts)
        duration = round(time.time() - start_time, 1)

        logger.info(f"SDK agent: {turns} turns, {len(tool_calls)} tools, {duration}s")

        await log_ai_usage(
            agent_id=agent_id,
            model=model,
            usage=usage,
            cost_usd_sdk=cost_usd,
            duration_ms=duration_ms_sdk or int(duration * 1000),
            turns=turns,
            tool_calls_count=len(tool_calls),
            success=success,
        )

        return {
            "response": response or "No response",
            "tool_calls": tool_calls,
            "turns": turns,
            "duration_s": duration,
            "cost_usd": cost_usd,
        }

    except Exception as e:
        logger.error(f"SDK agent error: {e}")
        # Log all available error details
        if stderr_lines:
            logger.error(f"SDK stderr: {''.join(stderr_lines[-10:])}")
        if hasattr(e, "error_output"):
            logger.error(f"SDK error_output: {e.error_output}")
        if hasattr(e, "__cause__") and e.__cause__:
            logger.error(f"SDK cause: {e.__cause__}")
        logger.error(f"SDK error type: {type(e).__name__}, attrs: {vars(e) if hasattr(e, '__dict__') else 'N/A'}")
        await log_ai_usage(
            agent_id=agent_id,
            model=model,
            usage=usage,
            cost_usd_sdk=cost_usd,
            duration_ms=int((time.time() - start_time) * 1000),
            turns=turns,
            tool_calls_count=len(tool_calls),
            success=False,
        )
        return {
            "response": f"Agent error: {e}",
            "tool_calls": tool_calls,
            "turns": turns,
            "duration_s": round(time.time() - start_time, 1),
            "error": str(e),
        }
