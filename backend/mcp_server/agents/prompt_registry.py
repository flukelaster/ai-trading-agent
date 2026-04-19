"""
Prompt Registry — central store for agent system prompts with Redis override.

Custom prompts stored in Redis (key: agent_prompt:{id}) override hardcoded defaults.
If Redis unavailable or key missing, falls back to hardcoded SYSTEM_PROMPT constants.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

# ─── Module-level Redis reference ────────────────────────────────────────────

_redis: Any = None

REDIS_PREFIX = "agent_prompt:"


def init_prompt_registry(redis_client: Any) -> None:
    global _redis
    _redis = redis_client
    logger.info("Prompt registry initialized")


# ─── Default prompts (lazy-loaded to avoid circular imports) ─────────────────

_defaults_loaded = False
_DEFAULTS: dict[str, str] = {}


def _load_defaults() -> None:
    global _defaults_loaded, _DEFAULTS
    if _defaults_loaded:
        return

    # Multi-agent prompts
    # Single agent (file-based)
    from pathlib import Path

    from mcp_server.agents.fundamental_analyst import SYSTEM_PROMPT as FUND
    from mcp_server.agents.orchestrator import SYSTEM_PROMPT as ORCH
    from mcp_server.agents.reflector import SYSTEM_PROMPT as REFL
    from mcp_server.agents.risk_analyst import SYSTEM_PROMPT as RISK
    from mcp_server.agents.technical_analyst import SYSTEM_PROMPT as TECH

    prompt_path = Path(__file__).parent.parent / "system_prompt.md"
    single = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    # Utility prompts
    from app.ai.prompts import OPTIMIZATION_SYSTEM_PROMPT, get_sentiment_prompt

    # Sentiment default uses a `{symbol}` placeholder so the /agent-prompts UI
    # displays the generic template instead of a gold-specific variant.
    # Runtime sentiment calls in app/ai/news_sentiment.py pass the real symbol.
    _DEFAULTS.update(
        {
            "orchestrator": ORCH,
            "technical_analyst": TECH,
            "fundamental_analyst": FUND,
            "risk_analyst": RISK,
            "reflector": REFL,
            "single_agent": single,
            "sentiment": get_sentiment_prompt("{symbol}"),
            "optimization": OPTIMIZATION_SYSTEM_PROMPT,
        }
    )
    _defaults_loaded = True


# ─── Agent metadata ──────────────────────────────────────────────────────────

AGENT_META: dict[str, dict[str, str]] = {
    "orchestrator": {
        "name": "Orchestrator",
        "model": "claude-sonnet-4-20250514",
        "description": "ผู้ประสานงานหลัก — สังเคราะห์รายงานจาก specialist ทั้งหมดและตัดสินใจเทรด",
    },
    "technical_analyst": {
        "name": "Technical Analyst",
        "model": "claude-haiku-4-5-20251001",
        "description": "วิเคราะห์กราฟ — EMA, RSI, ATR, Bollinger, แนวโน้ม, โมเมนตัม",
    },
    "fundamental_analyst": {
        "name": "Fundamental Analyst",
        "model": "claude-haiku-4-5-20251001",
        "description": "วิเคราะห์ข่าว — sentiment, ประวัติเทรด, ปัจจัยพื้นฐาน",
    },
    "risk_analyst": {
        "name": "Risk Analyst",
        "model": "claude-haiku-4-5-20251001",
        "description": "วิเคราะห์ความเสี่ยง — position sizing, SL/TP, correlation, exposure",
    },
    "reflector": {
        "name": "Reflector",
        "model": "claude-haiku-4-5-20251001",
        "description": "ทบทวนผลเทรด — เรียนรู้จากอดีต, ตรวจจับ regime, แนะนำกลยุทธ์",
    },
    "single_agent": {
        "name": "Single Agent",
        "model": "claude-sonnet-4-20250514",
        "description": "Agent เดี่ยว (fallback) — system_prompt.md สำหรับ single-agent mode",
    },
    "sentiment": {
        "name": "Sentiment Analyzer",
        "model": "claude-haiku-4-5-20251001",
        "description": "วิเคราะห์ข่าว sentiment — bullish/bearish/neutral พร้อมปัจจัยสำคัญ",
    },
    "optimization": {
        "name": "Strategy Optimizer",
        "model": "claude-haiku-4-5-20251001",
        "description": "แนะนำการปรับ parameter — วิเคราะห์ผลเทรดแล้วเสนอค่าที่ดีกว่า",
    },
}


def get_default_prompt(agent_id: str) -> str:
    _load_defaults()
    return _DEFAULTS.get(agent_id, "")


def _tradable_symbols_str() -> str:
    """Return comma-separated canonical symbols from current SYMBOL_PROFILES.

    Excludes broker-alias entries (those carry a 'canonical' key). Falls back
    to env-configured symbol_list if profiles not yet populated.
    """
    try:
        from app.config import SYMBOL_PROFILES, settings

        names = [s for s, p in SYMBOL_PROFILES.items() if "canonical" not in p]
        if not names:
            names = list(settings.symbol_list)
        return ", ".join(sorted(names))
    except Exception:
        return "the configured instruments"


def _inject_symbols(prompt: str) -> str:
    return prompt.replace("{TRADABLE_SYMBOLS}", _tradable_symbols_str())


async def get_active_prompt(agent_id: str) -> str:
    """Get custom prompt from Redis, fallback to hardcoded default.

    Substitutes {TRADABLE_SYMBOLS} with the current symbol list at call time,
    so agents always see the live instrument set.
    """
    _load_defaults()
    default = _DEFAULTS.get(agent_id, "")

    resolved = default
    if _redis is not None:
        try:
            custom = await _redis.get(f"{REDIS_PREFIX}{agent_id}")
            if custom:
                resolved = custom if isinstance(custom, str) else custom.decode("utf-8")
        except Exception as e:
            logger.warning(f"Prompt registry Redis read failed for {agent_id}: {e}")

    return _inject_symbols(resolved)


async def set_custom_prompt(agent_id: str, prompt: str) -> None:
    if _redis is None:
        raise RuntimeError("Prompt registry not initialized")
    await _redis.set(f"{REDIS_PREFIX}{agent_id}", prompt)


async def delete_custom_prompt(agent_id: str) -> None:
    if _redis is None:
        raise RuntimeError("Prompt registry not initialized")
    await _redis.delete(f"{REDIS_PREFIX}{agent_id}")


async def get_all_prompts() -> list[dict]:
    """Return all agents with active/default prompts and customization status."""
    _load_defaults()
    result = []

    for agent_id, meta in AGENT_META.items():
        default = _DEFAULTS.get(agent_id, "")
        active = default
        is_customized = False

        if _redis:
            try:
                custom = await _redis.get(f"{REDIS_PREFIX}{agent_id}")
                if custom:
                    active = custom if isinstance(custom, str) else custom.decode("utf-8")
                    is_customized = True
            except Exception:
                pass

        result.append(
            {
                "id": agent_id,
                "name": meta["name"],
                "model": meta["model"],
                "description": meta["description"],
                "default_prompt": default,
                "active_prompt": active,
                "is_customized": is_customized,
            }
        )

    return result
