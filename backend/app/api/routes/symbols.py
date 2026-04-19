"""Symbol Config API — CRUD + toggle + MT5 validation + ML retrain trigger."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import require_auth
from app.db.models import SymbolConfig
from app.db.session import async_session, get_db
from app.services import symbol_config_service as svc

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
MLStatus = Literal["pending", "training", "ready", "failed"]
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,32}$")


# ─── Schemas ──────────────────────────────────────────────────────────────────


class SymbolBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)
    broker_alias: str | None = None
    asset_class: str = Field(default="forex", max_length=16)
    default_timeframe: Timeframe = "M15"
    pip_value: float = Field(gt=0)
    default_lot: float = Field(gt=0)
    max_lot: float = Field(gt=0)
    price_decimals: int = Field(ge=0, le=8, default=2)
    sl_atr_mult: float = Field(gt=0, le=10, default=1.5)
    tp_atr_mult: float = Field(gt=0, le=10, default=2.0)
    contract_size: float = Field(gt=0, default=1.0)
    ml_tp_pips: float = Field(gt=0)
    ml_sl_pips: float = Field(gt=0)
    ml_forward_bars: int = Field(ge=1, le=100, default=10)
    ml_timeframe: Timeframe = "M15"

    @field_validator("asset_class")
    @classmethod
    def _check_asset_class(cls, v: str) -> str:
        from app.market.sessions import supported_asset_classes

        if v.lower() not in supported_asset_classes():
            raise ValueError(f"asset_class must be one of {supported_asset_classes()}; got {v!r}")
        return v.lower()

    @model_validator(mode="after")
    def _check_lot_bounds(self) -> SymbolBase:
        if self.default_lot > self.max_lot:
            raise ValueError("default_lot must be <= max_lot")
        return self

    @model_validator(mode="after")
    def _check_pip_value_sane(self) -> SymbolBase:
        """Reject pip_value that cannot co-exist with price_decimals.

        ML labeling treats `entry ± (tp_pips × pip_value)` as the TP/SL barrier;
        if pip_value is wildly out of scale (e.g. 10.0 on an instrument priced
        in cents) every candle gets labelled HOLD and training fails with
        "missing classes ['SELL','BUY']". Clamp to the plausible range derived
        from price_decimals.
        """
        # Permitted band: [10^-price_decimals, 10^-(price_decimals-2)]
        # Gives a 3-order-of-magnitude window around the conventional pip.
        max_pip = 10 ** (-(self.price_decimals - 2)) if self.price_decimals >= 2 else 100.0
        min_pip = 10 ** (-self.price_decimals) if self.price_decimals > 0 else 0.01
        if not (min_pip <= self.pip_value <= max_pip):
            suggested = 10 ** (-(self.price_decimals - 1)) if self.price_decimals >= 1 else 1.0
            raise ValueError(
                f"pip_value={self.pip_value} is out of range for price_decimals={self.price_decimals}. "
                f"Expected [{min_pip}, {max_pip}]. Suggested: {suggested}."
            )
        return self

    @model_validator(mode="after")
    def _check_ml_barrier_sane(self) -> SymbolBase:
        """Warn when ml_tp_pips × pip_value would exceed a 50% price move.

        Triple-barrier labeling needs BUY and SELL labels to appear in the
        training set. If the barrier is larger than half the typical price,
        the labeler will only ever produce HOLD.
        """
        tp_frac = self.ml_tp_pips * self.pip_value
        sl_frac = self.ml_sl_pips * self.pip_value
        # Rough heuristic: if barrier > 50 price units, it's almost certainly
        # wrong for anything that isn't a stock index. Keep the check cheap
        # and deterministic (no DB lookup) — actual price check happens at
        # train time via the trainer's minimum-samples guard.
        if tp_frac > 50 or sl_frac > 50:
            raise ValueError(
                f"ml_tp_pips × pip_value = {tp_frac} and ml_sl_pips × pip_value = {sl_frac}. "
                f"Barriers above 50 price units almost always produce HOLD-only labels. "
                f"Lower ml_tp_pips / ml_sl_pips or correct pip_value."
            )
        return self


class SymbolCreateRequest(SymbolBase):
    symbol: str = Field(min_length=2, max_length=32)

    @field_validator("symbol")
    @classmethod
    def _check_symbol(cls, v: str) -> str:
        if not _SYMBOL_PATTERN.match(v):
            raise ValueError("symbol must be alphanumeric (2-32 chars, . _ - allowed)")
        return v


class SymbolUpdateRequest(SymbolBase):
    pass


class SymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    display_name: str
    broker_alias: str | None
    asset_class: str
    is_enabled: bool
    default_timeframe: str
    pip_value: float
    default_lot: float
    max_lot: float
    price_decimals: int
    sl_atr_mult: float
    tp_atr_mult: float
    contract_size: float
    ml_tp_pips: float
    ml_sl_pips: float
    ml_forward_bars: int
    ml_timeframe: str
    ml_status: str
    ml_last_trained_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    @field_serializer("ml_last_trained_at", "created_at", "updated_at")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return v.isoformat() if v else None


class SymbolSpecResponse(BaseModel):
    ok: bool
    message: str
    spec: dict | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _require_config(db: AsyncSession, symbol: str) -> SymbolConfig:
    cfg = await svc.get_config(db, symbol)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
    return cfg


async def _audit(
    db: AsyncSession,
    request: Request,
    action: str,
    symbol: str,
    detail: dict | None = None,
) -> None:
    await log_audit(
        db,
        action,
        resource=f"symbol:{symbol}",
        detail=detail,
        ip=request.client.host if request.client else None,
        auto_commit=False,
    )


async def _publish(request: Request, symbol: str, action: str) -> None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client:
        await svc.publish_reload(redis_client, symbol, action)


async def _reload_engines_direct(request: Request) -> None:
    """Trigger BotManager.reload_engines directly.

    Safety net for when the Redis pubsub subscriber is not running or the
    message is missed (e.g. subscriber reconnecting). Swallows exceptions so
    API request does not fail if reload has a problem — pubsub will retry.
    """
    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        return
    try:
        from app.config import apply_db_symbol_profiles

        async with async_session() as _s:
            db_profiles = await svc.load_profiles_from_db(_s)
        apply_db_symbol_profiles(db_profiles)
        await manager.reload_engines()
    except Exception as e:
        logger.warning(f"Direct engine reload failed (pubsub will retry): {e}")


_PATH_TO_CLASS: tuple[tuple[str, str], ...] = (
    ("cryptocurrenc", "crypto"),
    ("crypto", "crypto"),
    ("metal", "metal"),
    ("energ", "energy"),
    ("ind", "index"),
    ("share", "stock"),
    ("stock", "stock"),
    ("equit", "stock"),
    ("forex", "forex"),
)


def _infer_asset_class(path: str) -> str:
    """Map MT5 symbol path (e.g. "Forex\\Majors\\EURUSD") to supported asset class."""
    if not path:
        return "forex"
    first = path.split("\\")[0].lower()
    for needle, cls in _PATH_TO_CLASS:
        if needle in first:
            return cls
    return "forex"


def _pip_value_from_spec(digits: int, point: float) -> float:
    """Forex 3/5-digit quotes: 1 pip = 10 × point. Else: 1 pip = point."""
    return point * 10 if digits in (3, 5) else point


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", dependencies=[Depends(require_auth)])
async def list_symbols(db: AsyncSession = Depends(get_db)) -> list[SymbolResponse]:
    configs = await svc.list_configs(db)
    return [SymbolResponse.model_validate(c) for c in configs]


@router.get("/broker-catalog", dependencies=[Depends(require_auth)])
async def broker_catalog(request: Request) -> dict:
    """Live XM broker catalog — used by Add Symbol dialog for searchable dropdown + autofill.

    Cached 1h in Redis. Bypasses cache when Redis unavailable.
    """
    connector = getattr(request.app.state, "connector", None)
    if connector is None:
        raise HTTPException(status_code=503, detail="MT5 connector unavailable")

    async def _fetch() -> dict:
        result = await connector.list_symbols()
        if not result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "bridge error",
            )
        raw_items = (result.get("data") or {}).get("items", [])
        return {
            "refreshed_at": datetime.utcnow().isoformat(),
            "count": len(raw_items),
            "items": [
                {
                    "symbol": it["symbol"],
                    "path": it.get("path") or "",
                    "description": it.get("description") or "",
                    "asset_class": _infer_asset_class(it.get("path") or ""),
                    "price_decimals": int(it["digits"]),
                    "pip_value": _pip_value_from_spec(int(it["digits"]), float(it["point"])),
                    "contract_size": float(it["trade_contract_size"]),
                    "volume_min": float(it["volume_min"]),
                    "volume_max": float(it["volume_max"]),
                    "volume_step": float(it.get("volume_step") or 0.01),
                    "currency_base": it.get("currency_base") or "",
                    "currency_profit": it.get("currency_profit") or "",
                }
                for it in raw_items
            ],
        }

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        from app.cache import cached

        return await cached(redis_client, "xm:catalog:v1", 3600, _fetch)
    return await _fetch()


@router.get("/{symbol}", dependencies=[Depends(require_auth)])
async def get_symbol(symbol: str, db: AsyncSession = Depends(get_db)) -> SymbolResponse:
    cfg = await _require_config(db, symbol)
    return SymbolResponse.model_validate(cfg)


@router.post("", dependencies=[Depends(require_auth)])
async def create_symbol(
    req: SymbolCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SymbolResponse:
    if await svc.get_config(db, req.symbol):
        raise HTTPException(status_code=409, detail=f"Symbol '{req.symbol}' already exists")

    # Check for soft-deleted row with same symbol — revive it instead of INSERT
    # (DB has a unique constraint on `symbol`, so a raw INSERT would fail with
    # IntegrityError when a previously-deleted row is still present).
    existing_deleted = await db.execute(
        select(SymbolConfig).where(
            SymbolConfig.symbol == req.symbol,
            SymbolConfig.is_deleted.is_(True),
        )
    )
    cfg = existing_deleted.scalar_one_or_none()
    action = "symbol_created"
    if cfg is not None:
        for field, value in req.model_dump().items():
            setattr(cfg, field, value)
        cfg.is_deleted = False
        cfg.is_enabled = False
        cfg.ml_status = "pending"
        cfg.ml_last_trained_at = None
        cfg.updated_at = datetime.utcnow()
        cfg.updated_by = "owner"
        action = "symbol_revived"
    else:
        cfg = SymbolConfig(**req.model_dump(), is_enabled=False, ml_status="pending")
        db.add(cfg)

    await _audit(db, request, action, req.symbol, {"broker_alias": req.broker_alias})
    await db.commit()
    await db.refresh(cfg)
    await _publish(request, req.symbol, "created")
    await _reload_engines_direct(request)

    logger.info(f"Symbol {action}: {req.symbol}")
    return SymbolResponse.model_validate(cfg)


@router.put("/{symbol}", dependencies=[Depends(require_auth)])
async def update_symbol(
    symbol: str,
    req: SymbolUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SymbolResponse:
    cfg = await _require_config(db, symbol)
    for field, value in req.model_dump().items():
        setattr(cfg, field, value)
    cfg.updated_at = datetime.utcnow()
    cfg.updated_by = "owner"

    await _audit(db, request, "symbol_updated", symbol)
    await db.commit()
    await db.refresh(cfg)
    await _publish(request, symbol, "updated")
    await _reload_engines_direct(request)

    return SymbolResponse.model_validate(cfg)


@router.delete("/{symbol}", dependencies=[Depends(require_auth)])
async def delete_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    cfg = await _require_config(db, symbol)
    cfg.is_enabled = False
    cfg.is_deleted = True
    cfg.updated_at = datetime.utcnow()
    cfg.updated_by = "owner"

    await _audit(db, request, "symbol_deleted", symbol)
    await db.commit()
    await _publish(request, symbol, "deleted")
    await _reload_engines_direct(request)

    return {"status": "deleted", "symbol": symbol}


@router.post("/{symbol}/toggle", dependencies=[Depends(require_auth)])
async def toggle_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SymbolResponse:
    cfg = await _require_config(db, symbol)
    cfg.is_enabled = not cfg.is_enabled
    cfg.updated_at = datetime.utcnow()
    cfg.updated_by = "owner"

    action = "symbol_enabled" if cfg.is_enabled else "symbol_disabled"
    await _audit(db, request, action, symbol)
    await db.commit()
    await db.refresh(cfg)
    await _publish(request, symbol, "toggled")
    await _reload_engines_direct(request)

    logger.info(f"Symbol {symbol} -> enabled={cfg.is_enabled}")
    return SymbolResponse.model_validate(cfg)


@router.post("/{symbol}/validate", dependencies=[Depends(require_auth)])
async def validate_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SymbolSpecResponse:
    cfg = await svc.get_config(db, symbol)
    alias = cfg.broker_alias if cfg and cfg.broker_alias else symbol
    connector = getattr(request.app.state, "connector", None)
    if connector is None:
        raise HTTPException(status_code=503, detail="MT5 connector unavailable")

    result = await connector.get_symbol_spec(alias)
    if not result.get("success"):
        return SymbolSpecResponse(ok=False, message=result.get("error") or "unknown error")
    return SymbolSpecResponse(ok=True, message=f"Validated {alias}", spec=result.get("data"))


@router.post("/{symbol}/retrain", dependencies=[Depends(require_auth)])
async def retrain_symbol(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    cfg = await _require_config(db, symbol)
    if cfg.ml_status == "training":
        raise HTTPException(status_code=409, detail=f"Symbol '{symbol}' already training")

    scheduler = getattr(request.app.state, "scheduler", None)
    manager = getattr(request.app.state, "manager", None)
    engine = manager.get_engine(symbol) if manager else None
    if scheduler is None or engine is None:
        raise HTTPException(status_code=503, detail="Scheduler or engine unavailable")

    cfg.ml_status = "training"
    cfg.updated_at = datetime.utcnow()
    cfg.updated_by = "owner"
    await db.commit()

    task = asyncio.create_task(scheduler._ml_retrain_symbol(symbol, engine))
    _retrain_tasks.add(task)
    task.add_done_callback(_on_retrain_done)

    return {"status": "training", "symbol": symbol}


_retrain_tasks: set[asyncio.Task] = set()


def _on_retrain_done(task: asyncio.Task) -> None:
    _retrain_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"retrain task raised: {exc!r}")


@router.get("/{symbol}/ml-status", dependencies=[Depends(require_auth)])
async def get_ml_status(symbol: str, db: AsyncSession = Depends(get_db)) -> dict:
    cfg = await _require_config(db, symbol)
    return {
        "symbol": symbol,
        "status": cfg.ml_status,
        "last_trained_at": cfg.ml_last_trained_at.isoformat() if cfg.ml_last_trained_at else None,
    }
