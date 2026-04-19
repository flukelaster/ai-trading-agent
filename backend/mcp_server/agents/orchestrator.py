"""
Orchestrator agent — coordinates specialist agents and makes final trading decisions.

Workflow:
1. Receive job (candle close, manual analysis, etc.)
2. Run specialist agents in parallel (technical, fundamental, risk)
3. Synthesize their reports into a final decision
4. Execute trades if warranted (via broker tools + guardrails)
5. Log all decisions with reasoning

Model: Sonnet (best reasoning for synthesis and final decisions).
"""

import asyncio
import json
import time

from loguru import logger

from mcp_server.agents import fundamental_analyst, reflector, risk_analyst, technical_analyst
from mcp_server.agents.base import (
    MODEL_ORCHESTRATOR,
    run_agent_loop,
)

SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent trading system for {TRADABLE_SYMBOLS}.

## Language & Format
Always respond in English. Do NOT use Thai.
Do NOT use emoji, icons, checkmarks, or any unicode symbols (no ✅ ❌ ⚠️ 🔥 etc.) under any circumstances.
Do NOT use markdown tables (|---|). Use bullet lists instead.

## Your Role
You receive analysis reports from three specialist agents and make the final trading decision. You are the ONLY agent with execution authority.

## Specialist Reports
You will receive three reports in the user message:
1. **Technical Analyst**: Price action, indicators, trend, momentum
2. **Fundamental Analyst**: Sentiment, performance history, session context
3. **Risk Analyst**: Portfolio exposure, risk limits, position sizing

## Your Decision Framework
1. Read all three reports carefully
2. **Technical signal is primary** — if Technical gives a clear BUY/SELL with confidence ≥ 0.5, that is a trade candidate
3. Fundamental bias is **supporting, not required** — if Fundamental is NEUTRAL (e.g. no news), that does NOT block the trade
4. Only trade when Risk Analyst says APPROVED or CAUTION (never on REJECTED)
5. If Technical and Fundamental **actively conflict** (BUY vs BEARISH), HOLD. But NEUTRAL ≠ conflict
6. If Technical confidence < 0.4 AND no strong fundamental bias, HOLD
7. If trading: use the Risk Analyst's recommended lot size and SL/TP

## Execution
If you decide to trade:
1. Use `place_order` with the calculated parameters
2. The order passes through non-bypassable guardrails automatically
3. Use `log_decision` to record the full reasoning (MANDATORY)

If you decide to HOLD:
1. Use `log_decision` to record why you held (MANDATORY)
2. If Technical gave a clear signal but you still held, explain specifically which condition blocked

## Rules
- NEVER trade against the Risk Analyst's REJECTED verdict
- NEVER skip logging — every decision must be journaled
- ALWAYS include all three analyst reports in your reasoning
- You are an AI Trader, not just an AI filter — your job is to find good trades, not to avoid all risk
- HOLD is correct when there is no clear setup, but a clear technical signal + APPROVED/CAUTION risk = you should trade
- Maximum 3 trades per analysis cycle
- If Reflector reports overfitting grade "overfit" (>60%): reduce lot size by 50% and note elevated overfitting risk in log_decision
- If overfitting grade is "moderate" (30-60%): proceed with caution, mention in log_decision
- Always reference the overfitting grade when making strategy selection decisions"""

# Orchestrator has access to execution tools + journal
ORCHESTRATOR_TOOL_NAMES = [
    "place_order",
    "modify_position",
    "close_position",
    "log_decision",
    "log_reasoning",
]


async def run_multi_agent(
    job_type: str,
    job_input: dict | None,
    oauth_token: str | None = None,
) -> dict:
    """Run the full multi-agent pipeline for a job.

    1. Run specialists in parallel
    2. Feed their reports to the orchestrator
    3. Orchestrator makes final decision

    Args:
        job_type: Job type (candle_analysis, manual_analysis, etc.)
        job_input: Job parameters
        oauth_token: OAuth token

    Returns:
        Combined result with all agent reports and final decision.
    """
    start_time = time.time()
    symbol = (job_input or {}).get("symbol")
    if not symbol:
        raise ValueError("multi-agent run requires 'symbol' in job_input")
    timeframe = (job_input or {}).get("timeframe", "M15")

    logger.info(f"[Orchestrator] Starting multi-agent analysis: {symbol} {timeframe}")

    results: dict[str, dict] = {}
    specialist_errors: dict[str, str] = {}

    # ─── Phase 0: Reflection (Phase E) ──────────────────────────────────
    # Reflector reviews past trades and provides context before analysis

    reflection_report = ""
    if reflector:
        try:
            logger.info("[Orchestrator] Phase 0: Running reflector")
            reflection_result = await reflector.reflect(symbol, timeframe)
            reflection_report = reflection_result.get("response", "")
            results["reflector"] = reflection_result
            logger.info(f"[Orchestrator] Reflection completed ({reflection_result.get('turns', 0)} turns)")
        except Exception as e:
            logger.warning(f"[Orchestrator] Reflector failed (non-critical): {e}")
            specialist_errors["reflector"] = str(e)
            results["reflector"] = {"response": f"ERROR: {e}", "tool_calls": [], "turns": 0}

    # ─── Phase 1: Run specialists in parallel ────────────────────────────

    # Run all specialists in parallel (Anthropic API supports concurrent calls)
    specialist_tasks = {
        "technical": asyncio.create_task(technical_analyst.analyze(symbol, timeframe)),
        "fundamental": asyncio.create_task(fundamental_analyst.analyze(symbol, timeframe)),
        "risk": asyncio.create_task(risk_analyst.analyze(symbol, timeframe=timeframe)),
    }

    for name, task in specialist_tasks.items():
        try:
            results[name] = await task
        except Exception as e:
            logger.error(f"[Orchestrator] {name} analyst failed: {e}")
            specialist_errors[name] = str(e)
            results[name] = {"response": f"ERROR: {e}", "tool_calls": [], "turns": 0}

    specialist_duration = round(time.time() - start_time, 1)
    logger.info(f"[Orchestrator] Specialists completed in {specialist_duration}s")

    # ─── Phase 2: Synthesize with Orchestrator ───────────────────────────

    synthesis_message = _build_synthesis_message(
        job_type=job_type,
        job_input=job_input,
        symbol=symbol,
        timeframe=timeframe,
        technical_report=results["technical"]["response"],
        fundamental_report=results["fundamental"]["response"],
        risk_report=results["risk"]["response"],
        reflection_report=reflection_report,
    )

    from mcp_server.agents.prompt_registry import get_active_prompt

    active_prompt = await get_active_prompt("orchestrator")
    orchestrator_result = await run_agent_loop(
        system_prompt=active_prompt,
        user_message=synthesis_message,
        tool_names=ORCHESTRATOR_TOOL_NAMES,
        model=MODEL_ORCHESTRATOR,
        max_turns=10,
        timeout=120,
        oauth_token=oauth_token,
        agent_id="orchestrator",
    )

    total_duration = round(time.time() - start_time, 1)

    # ─── Combine Results ─────────────────────────────────────────────────

    all_tool_calls = []
    for name, r in results.items():
        for tc in r.get("tool_calls", []):
            all_tool_calls.append({**tc, "agent": name})
    for tc in orchestrator_result.get("tool_calls", []):
        all_tool_calls.append({**tc, "agent": "orchestrator"})

    # Build specialists dict
    specialists_output: dict = {}
    for agent_name in ("technical", "fundamental", "risk", "reflector"):
        if agent_name in results:
            specialists_output[agent_name] = {
                "report": results[agent_name]["response"],
                "turns": results[agent_name].get("turns", 0),
                "tool_calls": len(results[agent_name].get("tool_calls", [])),
            }

    return {
        "decision": orchestrator_result.get("response", "No decision"),
        "specialists": specialists_output,
        "orchestrator_turns": orchestrator_result.get("turns", 0),
        "total_tool_calls": len(all_tool_calls),
        "tool_calls": all_tool_calls,
        "specialist_duration_s": specialist_duration,
        "total_duration_s": total_duration,
        "errors": specialist_errors if specialist_errors else None,
    }


def _build_synthesis_message(
    job_type: str,
    job_input: dict | None,
    symbol: str,
    timeframe: str,
    technical_report: str,
    fundamental_report: str,
    risk_report: str,
    reflection_report: str = "",
) -> str:
    """Build the user message for the orchestrator with all specialist reports."""
    job_context = ""
    if job_type == "candle_analysis":
        job_context = f"A new {timeframe} candle has closed for {symbol}."
    elif job_type == "manual_analysis":
        job_context = f"The owner has requested a manual analysis of {symbol}."
    elif job_type == "weekly_review":
        job_context = "Perform a weekly trading review."
    else:
        job_context = f"Job: {job_type}"

    reflection_section = ""
    if reflection_report:
        reflection_section = f"""
---

## Reflection & Session Context (from past trade review)
{reflection_report}
"""

    return f"""{job_context}
{reflection_section}
Your specialist analysts have completed their assessments:

---

## Technical Analysis Report
{technical_report}

---

## Fundamental Analysis Report
{fundamental_report}

---

## Risk Assessment Report
{risk_report}

---

Based on these three reports, make your trading decision for {symbol}.
Remember: you MUST log your decision with `log_decision`, whether you trade or hold.
Input context: {json.dumps(job_input, default=str) if job_input else "{}"}"""
