"""SymbolConfigService — DB-backed symbol profiles with Redis pub/sub hot-reload."""

from __future__ import annotations

import json
from datetime import datetime

import redis.asyncio as redis
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SymbolConfig

RELOAD_CHANNEL = "symbol_config_changed"


def config_to_profile(cfg: SymbolConfig) -> dict:
    """Convert DB row to in-memory profile dict (matches SYMBOL_PROFILES shape)."""
    return {
        "display_name": cfg.display_name,
        "default_timeframe": cfg.default_timeframe,
        "pip_value": cfg.pip_value,
        "default_lot": cfg.default_lot,
        "max_lot": cfg.max_lot,
        "price_decimals": cfg.price_decimals,
        "sl_atr_mult": cfg.sl_atr_mult,
        "tp_atr_mult": cfg.tp_atr_mult,
        "contract_size": cfg.contract_size,
        "ml_tp_pips": cfg.ml_tp_pips,
        "ml_sl_pips": cfg.ml_sl_pips,
        "ml_forward_bars": cfg.ml_forward_bars,
        "ml_timeframe": cfg.ml_timeframe,
        "broker_alias": cfg.broker_alias,
        "is_enabled": cfg.is_enabled,
        "ml_status": cfg.ml_status,
    }


async def list_configs(db: AsyncSession, include_disabled: bool = True) -> list[SymbolConfig]:
    stmt = select(SymbolConfig).where(SymbolConfig.is_deleted.is_(False))
    if not include_disabled:
        stmt = stmt.where(SymbolConfig.is_enabled.is_(True))
    result = await db.execute(stmt.order_by(SymbolConfig.symbol))
    return list(result.scalars().all())


async def get_config(db: AsyncSession, symbol: str) -> SymbolConfig | None:
    result = await db.execute(
        select(SymbolConfig).where(
            SymbolConfig.symbol == symbol,
            SymbolConfig.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def load_profiles_from_db(db: AsyncSession) -> dict[str, dict]:
    """Load all non-deleted configs as profile dict keyed by symbol and broker_alias."""
    configs = await list_configs(db, include_disabled=True)
    profiles: dict[str, dict] = {}
    for cfg in configs:
        profile = config_to_profile(cfg)
        profiles[cfg.symbol] = profile
        if cfg.broker_alias and cfg.broker_alias != cfg.symbol:
            alias_profile = profile.copy()
            alias_profile["canonical"] = cfg.symbol
            profiles[cfg.broker_alias] = alias_profile
    return profiles


async def publish_reload(
    redis_client: redis.Redis, symbol: str, action: str
) -> None:
    """Publish reload event so BotManager and scheduler refresh engines."""
    try:
        payload = json.dumps(
            {
                "symbol": symbol,
                "action": action,
                "ts": datetime.utcnow().isoformat(),
            }
        )
        await redis_client.publish(RELOAD_CHANNEL, payload)
    except Exception as e:
        logger.warning(f"SymbolConfigService: publish_reload failed: {e}")
