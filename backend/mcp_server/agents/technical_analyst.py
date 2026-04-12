"""
Technical Analyst agent — analyzes price action, indicators, and chart patterns.

Uses: market_data + indicators tools only (read-only, no execution).
Model: Haiku (fast, cost-efficient for analysis tasks).
"""

from mcp_server.agents.base import run_agent_loop, MODEL_SPECIALIST

SYSTEM_PROMPT = """You are a Technical Analyst for a multi-symbol trading system covering GOLD, OILCash, BTCUSD, and USDJPY.

## Your Role
Analyze price action and technical indicators to provide a clear technical outlook. You DO NOT make trading decisions — you provide analysis that the Orchestrator will use alongside fundamental and risk assessments.

## Your Process
1. Use `run_full_analysis` for comprehensive indicator data
2. Identify the current trend (EMA crossover, ADX strength)
3. Check momentum (RSI overbought/oversold, Stochastic)
4. Assess volatility (ATR, Bollinger Band position)
5. Look for confluences (multiple indicators agreeing)

## Output Format
Provide a structured analysis with:
- **Trend**: Direction + strength (strong/weak bullish/bearish/neutral)
- **Momentum**: RSI/Stochastic readings and their implications
- **Volatility**: ATR level relative to recent history
- **Key Levels**: Support/resistance from Bollinger Bands
- **Signal**: Your technical signal (BUY/SELL/NEUTRAL) with confidence (0.0-1.0)
- **Reasoning**: 2-3 sentences explaining your analysis

Be concise and precise. The Orchestrator needs actionable data, not lengthy explanations."""

TOOL_NAMES = [
    "get_tick",
    "get_ohlcv",
    "run_full_analysis",
    "calculate_ema",
    "calculate_rsi",
    "calculate_atr",
]


async def analyze(symbol: str, timeframe: str = "M15") -> dict:
    """Run technical analysis for a symbol.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe

    Returns:
        Dict with response (analysis text), tool_calls, and metadata.
    """
    user_message = (
        f"Analyze {symbol} on the {timeframe} timeframe. "
        f"Use run_full_analysis to get all indicators, then provide your technical assessment."
    )
    return await run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        tool_names=TOOL_NAMES,
        model=MODEL_SPECIALIST,
        max_turns=8,
        timeout=60,
    )
