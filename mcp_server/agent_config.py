"""
Agent configuration — sets up the Claude agent with MCP tools.

Implements the agentic loop: messages → tool_use → execute → results → repeat.
Uses the Anthropic Messages API with tool_use (standard agent pattern).
"""

import asyncio
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Optional

from anthropic import AsyncAnthropic
from loguru import logger

from mcp_server.guardrails import (
    AGENT_TIMEOUT,
    MAX_AGENT_TURNS,
    TradingGuardrails,
)
from mcp_server.tools import (
    broker,
    history,
    indicators,
    journal,
    learning,
    market_data,
    portfolio,
    risk,
    session,
    strategy_gen,
    sentiment,
)


# ─── System Prompt ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str | None = None


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        prompt_path = Path(__file__).parent / "system_prompt.md"
        _SYSTEM_PROMPT = prompt_path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


# ─── Tool Definitions for Claude API ────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    # Market Data (read-only)
    {
        "name": "get_tick",
        "description": "Get current bid/ask tick for a trading symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "e.g. GOLD, BTCUSD, USDJPY"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_ohlcv",
        "description": "Get OHLCV candlestick data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "default": "M15"},
                "count": {"type": "integer", "default": 100},
            },
            "required": ["symbol"],
        },
    },
    # Indicators
    {
        "name": "run_full_analysis",
        "description": "Run comprehensive technical analysis: EMA, RSI, ATR, ADX, Bollinger, Stochastic. This is the primary tool for market analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "default": "M15"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "calculate_ema",
        "description": "Calculate EMA for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "integer", "default": 20},
                "timeframe": {"type": "string", "default": "M15"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "calculate_rsi",
        "description": "Calculate RSI (0-100) for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "integer", "default": 14},
                "timeframe": {"type": "string", "default": "M15"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "calculate_atr",
        "description": "Calculate ATR (volatility) for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "integer", "default": 14},
                "timeframe": {"type": "string", "default": "M15"},
            },
            "required": ["symbol"],
        },
    },
    # Risk
    {
        "name": "validate_trade",
        "description": "Check if a trade is allowed under risk rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "signal": {"type": "integer", "description": "1=BUY, -1=SELL"},
                "current_positions": {"type": "integer"},
                "daily_pnl": {"type": "number"},
                "balance": {"type": "number"},
            },
            "required": ["symbol", "signal", "current_positions", "daily_pnl", "balance"],
        },
    },
    {
        "name": "calculate_lot_size",
        "description": "Calculate optimal position size based on risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "balance": {"type": "number"},
                "sl_pips": {"type": "number"},
            },
            "required": ["symbol", "balance", "sl_pips"],
        },
    },
    {
        "name": "calculate_sl_tp",
        "description": "Calculate stop-loss and take-profit levels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "entry_price": {"type": "number"},
                "signal": {"type": "integer", "description": "1=BUY, -1=SELL"},
                "atr": {"type": "number"},
            },
            "required": ["symbol", "entry_price", "signal", "atr"],
        },
    },
    # Broker (GUARDRAIL-GATED)
    {
        "name": "place_order",
        "description": "Place a trade order. GUARDRAIL-GATED: validated before execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "order_type": {"type": "string", "enum": ["BUY", "SELL"]},
                "lot": {"type": "number"},
                "sl": {"type": "number", "description": "Stop-loss price"},
                "tp": {"type": "number", "description": "Take-profit price"},
                "comment": {"type": "string", "default": ""},
            },
            "required": ["symbol", "order_type", "lot", "sl", "tp"],
        },
    },
    {
        "name": "modify_position",
        "description": "Modify SL/TP of an existing position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket": {"type": "integer"},
                "sl": {"type": "number"},
                "tp": {"type": "number"},
            },
            "required": ["ticket"],
        },
    },
    {
        "name": "close_position",
        "description": "Close a position by ticket number.",
        "input_schema": {
            "type": "object",
            "properties": {"ticket": {"type": "integer"}},
            "required": ["ticket"],
        },
    },
    {
        "name": "get_positions",
        "description": "Get open positions, optionally filtered by symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
        },
    },
    # Portfolio
    {
        "name": "get_account",
        "description": "Get account summary: balance, equity, margin, profit.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_exposure",
        "description": "Get portfolio exposure breakdown by symbol.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_correlation",
        "description": "Check for correlation conflicts before trading.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "signal": {"type": "integer"},
                "active_positions": {"type": "object"},
            },
            "required": ["symbol", "signal", "active_positions"],
        },
    },
    # Sentiment
    {
        "name": "get_sentiment",
        "description": "Get latest AI sentiment (bullish/bearish/neutral).",
        "input_schema": {"type": "object", "properties": {}},
    },
    # History
    {
        "name": "get_trade_history",
        "description": "Get recent trade history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
                "symbol": {"type": "string"},
            },
        },
    },
    {
        "name": "get_daily_pnl",
        "description": "Get daily P&L summary.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
        },
    },
    {
        "name": "get_performance",
        "description": "Get performance statistics (win rate, Sharpe, drawdown).",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "symbol": {"type": "string"},
            },
        },
    },
    # Journal
    {
        "name": "log_decision",
        "description": "Log a trading decision with reasoning. MUST be called for every decision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "decision": {"type": "string", "description": "e.g. 'BUY 0.05', 'HOLD', 'SELL 0.03'"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["symbol", "decision", "reasoning"],
        },
    },
    {
        "name": "log_reasoning",
        "description": "Log internal reasoning/thought process for review.",
        "input_schema": {
            "type": "object",
            "properties": {"thought_process": {"type": "string"}},
            "required": ["thought_process"],
        },
    },
    # Phase E: Learning
    {
        "name": "analyze_recent_trades",
        "description": "Analyze recent trade outcomes to identify patterns, streaks, and strategy performance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
                "symbol": {"type": "string"},
            },
        },
    },
    {
        "name": "detect_regime",
        "description": "Detect current market regime (trending/ranging/volatile/transitional) with strategy recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "GOLD"},
                "timeframe": {"type": "string", "default": "M15"},
            },
        },
    },
    # Phase E: Session Memory
    {
        "name": "save_context",
        "description": "Save session context for today's trading (merged with existing).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["symbol", "context"],
        },
    },
    {
        "name": "get_context",
        "description": "Retrieve today's session context for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "save_learning",
        "description": "Save a cross-session learning that persists for 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "learning_text": {"type": "string"},
                "category": {"type": "string", "default": "general"},
            },
            "required": ["learning_text"],
        },
    },
    {
        "name": "get_learnings",
        "description": "Retrieve cross-session learnings, optionally by category.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
    },
    # Phase E: Strategy Selection
    {
        "name": "get_strategy_profiles",
        "description": "Get all strategy profiles with regime suitability and parameters.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "recommend_strategy",
        "description": "Recommend the best strategy for the current market regime.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regime": {"type": "string", "enum": ["trending", "ranging", "volatile", "transitional"]},
                "symbol": {"type": "string", "default": "GOLD"},
            },
            "required": ["regime"],
        },
    },
    {
        "name": "generate_strategy_config",
        "description": "Generate a custom strategy config from a template with validated parameters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_strategy": {"type": "string"},
                "param_overrides": {"type": "object"},
                "name": {"type": "string"},
            },
            "required": ["base_strategy"],
        },
    },
    {
        "name": "generate_ensemble_config",
        "description": "Generate a custom ensemble with specified strategy weights (must sum to ~1.0).",
        "input_schema": {
            "type": "object",
            "properties": {
                "weights": {"type": "object", "description": "e.g. {\"ema_crossover\": 0.4, \"breakout\": 0.3, \"mean_reversion\": 0.3}"},
                "name": {"type": "string", "default": "custom_ensemble"},
            },
            "required": ["weights"],
        },
    },
]

# ─── Tool Dispatch ───────────────────────────────────────────────────────────

_TOOL_HANDLERS: dict[str, Any] = {
    # Market Data
    "get_tick": market_data.get_tick,
    "get_ohlcv": market_data.get_ohlcv,
    # Indicators
    "run_full_analysis": indicators.full_analysis,
    "calculate_ema": indicators.calculate_ema,
    "calculate_rsi": indicators.calculate_rsi,
    "calculate_atr": indicators.calculate_atr,
    # Risk
    "validate_trade": lambda **kw: risk.validate_trade(**kw),
    "calculate_lot_size": lambda **kw: risk.calculate_lot(**kw),
    "calculate_sl_tp": lambda **kw: risk.calculate_sl_tp(**kw),
    # Broker
    "place_order": broker.place_order,
    "modify_position": broker.modify_position,
    "close_position": broker.close_position,
    "get_positions": broker.get_positions,
    # Portfolio
    "get_account": portfolio.get_account,
    "get_exposure": portfolio.get_exposure,
    "check_correlation": lambda **kw: portfolio.check_correlation(**kw),
    # Sentiment
    "get_sentiment": sentiment.get_latest_sentiment,
    # History
    "get_trade_history": history.get_trade_history,
    "get_daily_pnl": history.get_daily_pnl,
    "get_performance": history.get_performance,
    # Journal
    "log_decision": journal.log_decision,
    "log_reasoning": journal.log_reasoning,
    # Phase E: Learning
    "analyze_recent_trades": learning.analyze_recent_trades,
    "detect_regime": learning.detect_regime,
    # Phase E: Session
    "save_context": session.save_context,
    "get_context": session.get_context,
    "save_learning": lambda **kw: session.save_learning(kw.get("learning_text", ""), kw.get("category", "general")),
    "get_learnings": session.get_learnings,
    # Phase E: Strategy
    "get_strategy_profiles": lambda **kw: strategy_gen.get_strategy_profiles(),
    "recommend_strategy": lambda **kw: strategy_gen.recommend_strategy(**kw),
    "generate_strategy_config": lambda **kw: strategy_gen.generate_strategy_config(**kw),
    "generate_ensemble_config": lambda **kw: strategy_gen.generate_ensemble_config(**kw),
}


async def _execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return JSON result string."""
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = handler(**input_data)
        # Handle both sync and async handlers
        if asyncio.iscoroutine(result):
            result = await result
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        return json.dumps({"error": str(e)})


# ─── Agent Loop ──────────────────────────────────────────────────────────────

async def run_agent(
    job_type: str,
    job_input: dict | None,
    oauth_token: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Run the agent loop for a single job.

    Args:
        job_type: Type of job (e.g., "candle_analysis", "manual_analysis")
        job_input: Job parameters (e.g., {"symbol": "GOLD", "timeframe": "M15"})
        oauth_token: Claude OAuth token (from Vault)
        model: Claude model to use

    Returns:
        Dict with agent output (reasoning, decision, tool calls made).
    """
    token = oauth_token or os.environ.get("CLAUDE_OAUTH_TOKEN")
    if not token:
        return {"error": "No OAuth token available", "decision": "HOLD — no token"}

    client = AsyncAnthropic(api_key=token)
    system_prompt = _load_system_prompt()

    # Build initial user message based on job type
    user_message = _build_user_message(job_type, job_input)

    messages = [{"role": "user", "content": user_message}]
    tool_calls_made: list[dict] = []
    start_time = time.time()

    for turn in range(MAX_AGENT_TURNS):
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > AGENT_TIMEOUT:
            logger.warning(f"Agent timeout after {elapsed:.0f}s, {turn} turns")
            break

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return {
                "error": str(e),
                "decision": "HOLD — API error",
                "turns": turn,
                "tool_calls": tool_calls_made,
            }

        # Process response content blocks
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check if model is done (no more tool calls)
        if response.stop_reason == "end_turn":
            # Extract final text response
            final_text = ""
            for block in assistant_content:
                if hasattr(block, "text"):
                    final_text += block.text
            return {
                "decision": final_text,
                "turns": turn + 1,
                "tool_calls": tool_calls_made,
                "duration_s": round(time.time() - start_time, 1),
            }

        # Execute tool calls
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                logger.info(f"[Agent] Tool call: {tool_name}({json.dumps(tool_input, default=str)[:200]})")
                result_str = await _execute_tool(tool_name, tool_input)

                tool_calls_made.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "output_preview": result_str[:200],
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    # If we exhausted turns
    return {
        "decision": "HOLD — max turns reached",
        "turns": MAX_AGENT_TURNS,
        "tool_calls": tool_calls_made,
        "duration_s": round(time.time() - start_time, 1),
    }


async def run_multi_agent(
    job_type: str,
    job_input: dict | None,
    oauth_token: str | None = None,
) -> dict:
    """Run the multi-agent pipeline (orchestrator + specialists).

    This is the Phase D entry point. Delegates to the orchestrator which
    coordinates technical, fundamental, and risk analysts in parallel.
    """
    from mcp_server.agents.orchestrator import run_multi_agent as _run
    return await _run(job_type, job_input, oauth_token)


def _build_user_message(job_type: str, job_input: dict | None) -> str:
    """Build the initial user message for the agent based on job type."""
    input_str = json.dumps(job_input, default=str) if job_input else "{}"

    if job_type == "candle_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        timeframe = (job_input or {}).get("timeframe", "M15")
        return (
            f"A new {timeframe} candle has closed for {symbol}. "
            f"Analyze the current market conditions and decide whether to trade.\n\n"
            f"Job input: {input_str}"
        )
    elif job_type == "manual_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        return (
            f"The owner has requested a manual analysis of {symbol}. "
            f"Provide a thorough market analysis with your trading recommendation.\n\n"
            f"Job input: {input_str}"
        )
    elif job_type == "weekly_review":
        return (
            "Perform a weekly trading review. Analyze the past week's performance, "
            "identify patterns, and suggest adjustments to the trading approach.\n\n"
            f"Job input: {input_str}"
        )
    else:
        return f"Job type: {job_type}\nInput: {input_str}"
