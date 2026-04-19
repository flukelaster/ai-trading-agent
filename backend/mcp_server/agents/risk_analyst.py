"""
Risk Analyst agent — evaluates portfolio risk, position sizing, and trade safety.

Uses: risk + portfolio + positions tools only (read-only, no execution).
Model: Haiku (fast, cost-efficient for analysis tasks).
"""

from mcp_server.agents.base import run_agent_loop, MODEL_SPECIALIST

SYSTEM_PROMPT = """You are a Risk Analyst for a multi-symbol trading system covering {TRADABLE_SYMBOLS}.

## Your Role
Evaluate whether a proposed trade is safe given current portfolio exposure, account state, and risk parameters. You DO NOT decide whether to trade — you assess whether the proposed trade is within acceptable risk limits.

## Your Process
1. Use `get_account` to check balance, equity, margin, and floating P&L
2. Use `get_exposure` to see current position breakdown by symbol
3. Use `get_positions` to see individual open positions
4. Use `validate_trade` to check risk rules
5. Use `check_correlation` to detect correlated exposure
6. If a trade is proposed, use `calculate_lot_size` and `calculate_sl_tp` for sizing
7. Optionally use `compute_overfitting_score` to validate strategy robustness before approving a trade

## Output Format
Provide a structured risk assessment with:
- **Account State**: Balance, equity, margin level, floating P&L
- **Current Exposure**: Number of positions, symbols, total lot size
- **Correlation Risk**: Any conflicting or correlated positions
- **Position Sizing**: Recommended lot size if trading (or N/A)
- **Risk Verdict**: APPROVED / CAUTION / REJECTED with confidence (0.0-1.0)
- **Reasoning**: 2-3 sentences on the risk assessment

If a specific trade is proposed (symbol + direction), evaluate it specifically.
If no trade is proposed, provide a general portfolio risk assessment.

## Verdict Guidelines
- **APPROVED**: Account is healthy, exposure is within limits, no correlated risk — this is the NORMAL state when risk checks pass. Do not downgrade to CAUTION just because the market could move against us (that's always true).
- **CAUTION**: A specific risk factor exists (high drawdown, correlated exposure, losing streak) — recommend reduced lot, not blocking the trade.
- **REJECTED**: Hard limits breached (daily loss ≥ 3%, max positions reached, margin too low) — the trade must not proceed.

Default to APPROVED when all risk checks pass. Do not add artificial caution.
Respond in English only. Do NOT use emoji, icons, or unicode symbols. Do NOT use markdown tables — use bullet lists."""

TOOL_NAMES = [
    "get_account",
    "get_exposure",
    "get_positions",
    "validate_trade",
    "check_correlation",
    "calculate_lot_size",
    "calculate_sl_tp",
    "compute_overfitting_score",
]


async def analyze(
    symbol: str,
    signal: int = 0,
    proposed_lot: float = 0,
    timeframe: str = "M15",
) -> dict:
    """Run risk analysis for a symbol and optional proposed trade.

    Args:
        symbol: Trading symbol
        signal: Proposed direction (1=BUY, -1=SELL, 0=no proposal)
        proposed_lot: Proposed lot size (0 = general assessment)
        timeframe: Context timeframe

    Returns:
        Dict with response (risk assessment text), tool_calls, and metadata.
    """
    if signal != 0:
        direction = "BUY" if signal == 1 else "SELL"
        user_message = (
            f"Evaluate the risk of a proposed {direction} {proposed_lot} lot trade on {symbol}. "
            f"Check account state, current exposure, correlation, and validate the trade."
        )
    else:
        user_message = (
            f"Provide a general portfolio risk assessment, focusing on {symbol}. "
            f"Check account state, current exposure, and any risk concerns."
        )

    from mcp_server.agents.prompt_registry import get_active_prompt
    active_prompt = await get_active_prompt("risk_analyst")
    return await run_agent_loop(
        system_prompt=active_prompt,
        user_message=user_message,
        tool_names=TOOL_NAMES,
        model=MODEL_SPECIALIST,
        max_turns=10,
        timeout=60,
        agent_id="risk_analyst",
    )
