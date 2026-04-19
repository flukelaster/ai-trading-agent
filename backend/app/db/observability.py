"""
DB Observability — pool metrics, slow query log, session-lifetime tracking.

Phase 1 of long-term DB scaling plan (docs/LONG-TERM-DB-SCALING.md).

Exports:
- get_pool_stats(engine) — live pool snapshot
- install_slow_query_logger(engine, threshold_ms) — log queries exceeding threshold
- SessionLifetimeMiddleware — log requests holding DB connection too long
- PoolPressureMonitor — APScheduler callable, snapshots pool + alerts
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------- Pool stats ----------


def get_pool_stats(async_engine: AsyncEngine) -> dict[str, Any]:
    """Snapshot current pool state. Safe to call frequently (no I/O)."""
    pool = async_engine.sync_engine.pool
    size = pool.size()
    checked_out = pool.checkedout()
    overflow = pool.overflow()
    checked_in = pool.checkedin()
    total_capacity = size + max(overflow, 0)
    utilization = checked_out / total_capacity if total_capacity else 0.0
    return {
        "size": size,
        "checked_out": checked_out,
        "checked_in": checked_in,
        "overflow": overflow,
        "total_capacity": total_capacity,
        "utilization": round(utilization, 3),
    }


# ---------- Slow query log ----------


@dataclass
class SlowQueryRecord:
    sql: str
    duration_ms: float
    timestamp: float


class SlowQueryTracker:
    """In-memory ring buffer of recent slow queries."""

    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self._buf: deque[SlowQueryRecord] = deque(maxlen=capacity)

    def record(self, sql: str, duration_ms: float) -> None:
        self._buf.append(SlowQueryRecord(sql=sql, duration_ms=duration_ms, timestamp=time.time()))

    def top(self, n: int = 10) -> list[dict[str, Any]]:
        ranked = sorted(self._buf, key=lambda r: r.duration_ms, reverse=True)[:n]
        return [{"sql": r.sql[:300], "duration_ms": round(r.duration_ms, 1), "timestamp": r.timestamp} for r in ranked]


slow_query_tracker = SlowQueryTracker()


def install_slow_query_logger(async_engine: AsyncEngine, threshold_ms: float = 500.0) -> None:
    """Attach SQLAlchemy execute-time listeners to the sync engine underlying async_engine."""
    sync_engine: Engine = async_engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._query_start_time = time.monotonic()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        start = getattr(context, "_query_start_time", None)
        if start is None:
            return
        duration_ms = (time.monotonic() - start) * 1000.0
        if duration_ms >= threshold_ms:
            slow_query_tracker.record(statement, duration_ms)
            logger.warning(
                "slow_query duration_ms={:.1f} sql={}",
                duration_ms,
                statement[:200].replace("\n", " "),
            )


# ---------- Session-lifetime middleware ----------


@dataclass
class LongHoldRecord:
    path: str
    method: str
    duration_ms: float
    checkouts: int
    timestamp: float


class LongHoldTracker:
    def __init__(self, capacity: int = 100):
        self._buf: deque[LongHoldRecord] = deque(maxlen=capacity)

    def record(self, rec: LongHoldRecord) -> None:
        self._buf.append(rec)

    def top(self, n: int = 10) -> list[dict[str, Any]]:
        ranked = sorted(self._buf, key=lambda r: r.duration_ms, reverse=True)[:n]
        return [
            {
                "path": r.path,
                "method": r.method,
                "duration_ms": round(r.duration_ms, 1),
                "checkouts": r.checkouts,
                "timestamp": r.timestamp,
            }
            for r in ranked
        ]


long_hold_tracker = LongHoldTracker()


class SessionLifetimeMiddleware(BaseHTTPMiddleware):
    """Measure how long each request holds DB connections. Warn/error on long holds."""

    def __init__(
        self,
        app,
        async_engine: AsyncEngine,
        warn_threshold_ms: float = 2000.0,
        error_threshold_ms: float = 10000.0,
    ):
        super().__init__(app)
        self.engine = async_engine
        self.warn_threshold_ms = warn_threshold_ms
        self.error_threshold_ms = error_threshold_ms

    async def dispatch(self, request: Request, call_next) -> Response:
        pool = self.engine.sync_engine.pool
        start = time.monotonic()
        start_checkouts = pool.checkedout()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000.0
        end_checkouts = pool.checkedout()

        if duration_ms >= self.warn_threshold_ms:
            rec = LongHoldRecord(
                path=request.url.path,
                method=request.method,
                duration_ms=duration_ms,
                checkouts=max(end_checkouts, start_checkouts),
                timestamp=time.time(),
            )
            long_hold_tracker.record(rec)
            log_fn = logger.error if duration_ms >= self.error_threshold_ms else logger.warning
            log_fn(
                "long_request path={} method={} duration_ms={:.0f} checkouts={}",
                request.url.path,
                request.method,
                duration_ms,
                rec.checkouts,
            )
        return response


# ---------- Pool pressure monitor ----------


@dataclass
class PressureState:
    high_since: float | None = None
    alerted: bool = False
    recent_samples: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=360))


class PoolPressureMonitor:
    """
    Sample pool stats periodically. Telegram-alert on sustained high utilization.

    Wire into scheduler: add_job(monitor.tick, "interval", seconds=10).
    """

    def __init__(
        self,
        async_engine: AsyncEngine,
        notifier=None,
        high_threshold: float = 0.7,
        sustained_seconds: float = 60.0,
    ):
        self.engine = async_engine
        self.notifier = notifier
        self.high_threshold = high_threshold
        self.sustained_seconds = sustained_seconds
        self.state = PressureState()

    async def tick(self) -> None:
        stats = get_pool_stats(self.engine)
        stats["ts"] = time.time()
        self.state.recent_samples.append(stats)

        if stats["utilization"] >= self.high_threshold:
            if self.state.high_since is None:
                self.state.high_since = time.time()
            elif not self.state.alerted and time.time() - self.state.high_since >= self.sustained_seconds:
                await self._alert(stats)
                self.state.alerted = True
        else:
            self.state.high_since = None
            self.state.alerted = False

    async def _alert(self, stats: dict[str, Any]) -> None:
        msg = (
            f"DB pool pressure HIGH — utilization={stats['utilization']:.0%} "
            f"checked_out={stats['checked_out']}/{stats['total_capacity']} "
            f"for {self.sustained_seconds:.0f}s+. Investigate slow queries / leaks."
        )
        logger.error(msg)
        if self.notifier is not None:
            try:
                await self.notifier.send_message(msg)
            except Exception as e:
                logger.warning(f"Pool pressure alert notifier failed: {e}")

    def recent(self, n: int = 60) -> list[dict[str, Any]]:
        return list(self.state.recent_samples)[-n:]
