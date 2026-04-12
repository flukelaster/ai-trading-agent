"""
Agent configuration — tool definitions, dispatch, and entry points.

Uses Anthropic Messages API with tool_use for agent loops.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from mcp_server.agents.base import run_agent_loop, MODEL_ORCHESTRATOR
from mcp_server.guardrails import AGENT_TIMEOUT, MAX_AGENT_TURNS
from mcp_server.tools import market_data, indicators, risk, broker, portfolio
from mcp_server.tools import sentiment, history, journal, learning, session, strategy_gen
from mcp_server.tools import memory


# ─── System Prompt ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str | None = None


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        prompt_path = Path(__file__).parent / "system_prompt.md"
        _SYSTEM_PROMPT = prompt_path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


# ─── Tool Definitions (for Messages API) ────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    # Market Data
    {"name": "get_tick", "description": "Get current bid/ask tick", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_ohlcv", "description": "Get OHLCV candlestick data", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "timeframe": {"type": "string"}, "count": {"type": "integer"}}, "required": ["symbol"]}},
    # Indicators
    {"name": "run_full_analysis", "description": "Comprehensive technical analysis: EMA, RSI, ATR, ADX, Bollinger, Stochastic", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "timeframe": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "calculate_ema", "description": "Calculate EMA", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "period": {"type": "integer"}, "timeframe": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "calculate_rsi", "description": "Calculate RSI (0-100)", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "period": {"type": "integer"}, "timeframe": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "calculate_atr", "description": "Calculate ATR (volatility)", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "period": {"type": "integer"}, "timeframe": {"type": "string"}}, "required": ["symbol"]}},
    # Risk
    {"name": "validate_trade", "description": "Check if trade is allowed under risk rules", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "signal": {"type": "integer"}, "current_positions": {"type": "integer"}, "daily_pnl": {"type": "number"}, "balance": {"type": "number"}}, "required": ["symbol", "signal", "current_positions", "daily_pnl", "balance"]}},
    {"name": "calculate_lot_size", "description": "Calculate optimal position size", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "balance": {"type": "number"}, "sl_pips": {"type": "number"}}, "required": ["symbol", "balance", "sl_pips"]}},
    {"name": "calculate_sl_tp", "description": "Calculate stop-loss and take-profit", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "entry_price": {"type": "number"}, "signal": {"type": "integer"}, "atr": {"type": "number"}}, "required": ["symbol", "entry_price", "signal", "atr"]}},
    # Broker (GUARDRAIL-GATED)
    {"name": "place_order", "description": "Place trade order (guardrail-gated)", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "order_type": {"type": "string", "enum": ["BUY", "SELL"]}, "lot": {"type": "number"}, "sl": {"type": "number"}, "tp": {"type": "number"}, "comment": {"type": "string"}}, "required": ["symbol", "order_type", "lot", "sl", "tp"]}},
    {"name": "modify_position", "description": "Modify SL/TP of position", "input_schema": {"type": "object", "properties": {"ticket": {"type": "integer"}, "sl": {"type": "number"}, "tp": {"type": "number"}}, "required": ["ticket"]}},
    {"name": "close_position", "description": "Close a position", "input_schema": {"type": "object", "properties": {"ticket": {"type": "integer"}}, "required": ["ticket"]}},
    {"name": "get_positions", "description": "Get open positions", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
    # Portfolio
    {"name": "get_account", "description": "Get account summary", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_exposure", "description": "Get portfolio exposure by symbol", "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_correlation", "description": "Check correlation conflicts", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "signal": {"type": "integer"}, "active_positions": {"type": "object"}}, "required": ["symbol", "signal", "active_positions"]}},
    # Sentiment
    {"name": "get_sentiment", "description": "Get latest AI sentiment", "input_schema": {"type": "object", "properties": {}}},
    # History
    {"name": "get_trade_history", "description": "Get recent trade history", "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "symbol": {"type": "string"}}}},
    {"name": "get_daily_pnl", "description": "Get daily P&L", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
    {"name": "get_performance", "description": "Get performance stats", "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "symbol": {"type": "string"}}}},
    # Journal
    {"name": "log_decision", "description": "Log trading decision with reasoning (MUST call)", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "decision": {"type": "string"}, "reasoning": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["symbol", "decision", "reasoning"]}},
    {"name": "log_reasoning", "description": "Log internal reasoning", "input_schema": {"type": "object", "properties": {"thought_process": {"type": "string"}}, "required": ["thought_process"]}},
    # Learning (Phase E)
    {"name": "analyze_recent_trades", "description": "Analyze recent trade patterns", "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "symbol": {"type": "string"}}}},
    {"name": "detect_regime", "description": "Detect market regime", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "timeframe": {"type": "string"}}}},
    # Session
    {"name": "save_context", "description": "Save session context", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "context": {"type": "object"}}, "required": ["symbol", "context"]}},
    {"name": "get_context", "description": "Get session context", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "save_learning", "description": "Save cross-session learning", "input_schema": {"type": "object", "properties": {"learning_text": {"type": "string"}, "category": {"type": "string"}}, "required": ["learning_text"]}},
    {"name": "get_learnings", "description": "Get learnings", "input_schema": {"type": "object", "properties": {"category": {"type": "string"}}}},
    # Strategy
    {"name": "get_strategy_profiles", "description": "Get strategy profiles", "input_schema": {"type": "object", "properties": {}}},
    {"name": "recommend_strategy", "description": "Recommend strategy for regime", "input_schema": {"type": "object", "properties": {"regime": {"type": "string"}, "symbol": {"type": "string"}}, "required": ["regime"]}},
    {"name": "generate_strategy_config", "description": "Generate custom strategy config", "input_schema": {"type": "object", "properties": {"base_strategy": {"type": "string"}, "param_overrides": {"type": "object"}, "name": {"type": "string"}}, "required": ["base_strategy"]}},
    {"name": "generate_ensemble_config", "description": "Generate ensemble config", "input_schema": {"type": "object", "properties": {"weights": {"type": "object"}, "name": {"type": "string"}}, "required": ["weights"]}},
    # Memory (Layered Memory System)
    {"name": "save_memory", "description": "Save insight to persistent memory (30d mid-term, promotable to permanent)", "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "category": {"type": "string", "enum": ["pattern", "strategy", "risk", "regime", "correlation"]}, "symbol": {"type": "string"}, "evidence": {"type": "object"}}, "required": ["summary", "category"]}},
    {"name": "get_memories", "description": "Recall stored memories sorted by confidence", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "category": {"type": "string"}, "tier": {"type": "string", "enum": ["mid", "long"]}, "limit": {"type": "integer"}}}},
    {"name": "validate_memory", "description": "Validate whether a stored memory matched reality (hit/miss)", "input_schema": {"type": "object", "properties": {"memory_id": {"type": "integer"}, "hit": {"type": "boolean"}}, "required": ["memory_id", "hit"]}},
]

# ─── Tool Dispatch ───────────────────────────────────────────────────────────

_TOOL_HANDLERS: dict[str, Any] = {
    "get_tick": market_data.get_tick,
    "get_ohlcv": market_data.get_ohlcv,
    "run_full_analysis": indicators.full_analysis,
    "calculate_ema": indicators.calculate_ema,
    "calculate_rsi": indicators.calculate_rsi,
    "calculate_atr": indicators.calculate_atr,
    "validate_trade": lambda **kw: risk.validate_trade(**kw),
    "calculate_lot_size": lambda **kw: risk.calculate_lot(**kw),
    "calculate_sl_tp": lambda **kw: risk.calculate_sl_tp(**kw),
    "place_order": broker.place_order,
    "modify_position": broker.modify_position,
    "close_position": broker.close_position,
    "get_positions": broker.get_positions,
    "get_account": portfolio.get_account,
    "get_exposure": portfolio.get_exposure,
    "check_correlation": lambda **kw: portfolio.check_correlation(**kw),
    "get_sentiment": sentiment.get_latest_sentiment,
    "get_trade_history": history.get_trade_history,
    "get_daily_pnl": history.get_daily_pnl,
    "get_performance": history.get_performance,
    "log_decision": journal.log_decision,
    "log_reasoning": journal.log_reasoning,
    "analyze_recent_trades": learning.analyze_recent_trades,
    "detect_regime": learning.detect_regime,
    "save_context": session.save_context,
    "get_context": session.get_context,
    "save_learning": lambda **kw: session.save_learning(kw.get("learning_text", ""), kw.get("category", "general")),
    "get_learnings": session.get_learnings,
    "get_strategy_profiles": lambda **kw: strategy_gen.get_strategy_profiles(),
    "recommend_strategy": lambda **kw: strategy_gen.recommend_strategy(**kw),
    "generate_strategy_config": lambda **kw: strategy_gen.generate_strategy_config(**kw),
    "generate_ensemble_config": lambda **kw: strategy_gen.generate_ensemble_config(**kw),
    "save_memory": memory.save_memory,
    "get_memories": memory.get_memories,
    "validate_memory": memory.validate_memory,
}


async def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return JSON result string."""
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(**input_data)
        if asyncio.iscoroutine(result):
            result = await result
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        return json.dumps({"error": str(e)})


def get_tools_by_name(names: list[str]) -> list[dict]:
    """Filter TOOLS by name list."""
    name_set = set(names)
    return [t for t in TOOLS if t["name"] in name_set]


# ─── Agent Entry Points ─────────────────────────────────────────────────────

async def run_agent(
    job_type: str,
    job_input: dict | None,
    model: str = MODEL_ORCHESTRATOR,
) -> dict:
    """Run single-agent loop."""
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(job_type, job_input)

    result = await run_agent_loop(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=TOOLS,
        model=model,
        max_turns=MAX_AGENT_TURNS,
        timeout=AGENT_TIMEOUT,
    )
    decision = result.get("response", "No decision")

    # Extract strategy name from decision text
    strategy_used = "ai_autonomous"
    for keyword in ["Trend Following", "Mean Reversion", "Breakout", "Momentum", "Hold"]:
        if keyword.lower() in decision.lower():
            strategy_used = keyword.lower().replace(" ", "_")
            break

    return {
        "decision": decision,
        "strategy_used": strategy_used,
        "turns": result.get("turns", 0),
        "tool_calls": result.get("tool_calls", []),
        "duration_s": result.get("duration_s", 0),
    }


async def run_multi_agent(
    job_type: str,
    job_input: dict | None,
) -> dict:
    """Run multi-agent pipeline."""
    from mcp_server.agents.orchestrator import run_multi_agent as _run
    return await _run(job_type, job_input)


def _build_user_message(job_type: str, job_input: dict | None) -> str:
    input_str = json.dumps(job_input, default=str) if job_input else "{}"
    if job_type == "candle_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        timeframe = (job_input or {}).get("timeframe", "M15")
        return f"A new {timeframe} candle has closed for {symbol}. Analyze and decide whether to trade.\n\nJob input: {input_str}"
    elif job_type == "manual_analysis":
        symbol = (job_input or {}).get("symbol", "GOLD")
        return f"Manual analysis requested for {symbol}. Provide thorough analysis with recommendation.\n\nJob input: {input_str}"
    elif job_type == "weekly_review":
        return f"Perform a weekly trading review.\n\nJob input: {input_str}"
    else:
        return f"Job type: {job_type}\nInput: {input_str}"
