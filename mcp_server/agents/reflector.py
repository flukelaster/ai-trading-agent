"""
Reflector agent — reviews past trades and extracts learnings.

Runs before the main analysis pipeline (Phase 0 of orchestrator).
Provides context and lessons to the orchestrator to improve decisions.

Uses: learning + session + strategy_gen tools.
Model: Haiku (fast review, cost-efficient).
"""

from mcp_server.agents.base import run_agent_loop, filter_tools, MODEL_SPECIALIST

SYSTEM_PROMPT = """You are a Trade Reflector for a multi-symbol trading system. Your job is to review recent trading performance and extract actionable learnings.

## Your Role
Before each trading session, you review what happened recently and provide context that helps the Orchestrator make better decisions. You DO NOT trade — you reflect and learn.

## Your Process
1. Use `analyze_recent_trades` to get trade statistics and patterns
2. Use `detect_regime` to understand the current market state
3. Use `get_learnings` to recall previous insights
4. Use `get_context` to check if there's existing session context
5. Synthesize: What worked? What didn't? What should we watch for?

## Output Format
Provide a structured reflection with:
- **Recent Performance**: Win rate, P&L, streak status
- **Current Regime**: Market regime and what it means for strategy selection
- **Lessons**: Top 3 actionable insights from recent trades
- **Strategy Recommendation**: Which strategy fits the current regime
- **Warnings**: Any risk factors to watch (losing streak, high volatility, etc.)
- **Session Context**: Key context the orchestrator should know

After your analysis:
- Use `save_context` to store key insights for the current session
- Use `save_learning` for any new cross-session insights
- Use `recommend_strategy` to suggest the best strategy for the regime

Be concise and actionable. The Orchestrator reads your report to calibrate its approach."""

TOOL_NAMES = [
    "analyze_recent_trades",
    "detect_regime",
    "get_learnings",
    "get_context",
    "save_context",
    "save_learning",
    "get_strategy_profiles",
    "recommend_strategy",
]


async def reflect(symbol: str, timeframe: str = "M15") -> dict:
    """Run the reflection cycle for a symbol.

    Args:
        symbol: Trading symbol
        timeframe: Context timeframe

    Returns:
        Dict with reflection report, learnings, and strategy recommendation.
    """
    tools = filter_tools(TOOL_NAMES)
    user_message = (
        f"Reflect on recent {symbol} trading performance. "
        f"Analyze trades from the past 7 days, detect the current market regime on {timeframe}, "
        f"recall previous learnings, and provide an actionable briefing for the Orchestrator. "
        f"Save any new insights to session context and learnings."
    )
    return await run_agent_loop(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        tools=tools,
        model=MODEL_SPECIALIST,
        max_turns=10,
        timeout=90,
    )
