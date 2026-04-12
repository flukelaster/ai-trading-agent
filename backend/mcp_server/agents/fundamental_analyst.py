"""
Fundamental Analyst agent — analyzes sentiment, news, and historical patterns.

Uses: sentiment + history tools only (read-only, no execution).
Model: Haiku (fast, cost-efficient for analysis tasks).
"""

from mcp_server.agents.base import run_agent_loop, MODEL_SPECIALIST

SYSTEM_PROMPT = """You are a Fundamental Analyst for a multi-symbol trading system covering GOLD, OILCash, BTCUSD, and USDJPY.

## Your Role
Analyze market sentiment, recent trading performance, and fundamental factors to provide a directional bias. You DO NOT make trading decisions — you provide analysis that the Orchestrator will use alongside technical and risk assessments.

## Your Process
1. Use `get_sentiment` for the latest AI sentiment reading
2. Use `get_performance` to check recent win rate and patterns
3. Use `get_trade_history` to see recent trade outcomes
4. Use `get_daily_pnl` to assess today's performance
5. Consider macro factors (time of day, session overlap, known events)

## Output Format
Provide a structured analysis with:
- **Sentiment**: Current AI sentiment reading and direction
- **Recent Performance**: Win rate, streak, and P&L trends
- **Session Context**: Which trading session is active, any known events
- **Bias**: Your fundamental bias (BULLISH/BEARISH/NEUTRAL) with confidence (0.0-1.0)
- **Reasoning**: 2-3 sentences explaining your assessment

Be concise and data-driven. The Orchestrator needs clear directional bias, not speculation."""

TOOL_NAMES = [
    "get_sentiment",
    "get_trade_history",
    "get_daily_pnl",
    "get_performance",
]


async def analyze(symbol: str, timeframe: str = "M15") -> dict:
    """Run fundamental analysis for a symbol.

    Args:
        symbol: Trading symbol
        timeframe: Context timeframe

    Returns:
        Dict with response (analysis text), tool_calls, and metadata.
    """
    user_message = (
        f"Provide a fundamental analysis for {symbol}. "
        f"Check current sentiment, recent performance, and today's P&L to form a directional bias."
    )
    return await run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        tool_names=TOOL_NAMES,
        model=MODEL_SPECIALIST,
        max_turns=8,
        timeout=60,
    )
