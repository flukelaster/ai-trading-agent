"""
AI Trading Agent — FastAPI Main Application (multi-symbol)
"""

import os
from contextlib import asynccontextmanager

import redis.asyncio as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.ai.client import AIClient
from app.ai.news_sentiment import NewsSentimentAnalyzer
from app.ai.strategy_optimizer import StrategyOptimizer
from app.api.routes import (
    activity,
    admin,
    agent_prompts,
    ai_insights,
    ai_usage,
    memory as memory_routes,
    analytics,
    backtest,
    bot,
    data,
    history,
    jobs,
    macro,
    market_data,
    ml,
    positions,
    integration,
    rollout,
    runners,
    secrets,
    strategy,
    symbols as symbols_routes,
)
from app.api.routes import quant
from app.api.routes import metrics as metrics_routes
from app.api.routes import webhooks
from app.api.websocket import router as ws_router
from app.api.ws_runners import router as ws_runners_router
from app.auth import router as auth_router
from app.auth_webauthn import router as webauthn_router
from app.bot.manager import BotManager
from app.bot.scheduler import BotScheduler
from app.config import settings
from app.data.collector import HistoricalDataCollector
from app.data.macro import MacroDataService
from app.data.macro_events import MacroEventCalendar
from app.db.observability import (
    PoolPressureMonitor,
    SessionLifetimeMiddleware,
    get_pool_stats,
    install_slow_query_logger,
    long_hold_tracker,
    slow_query_tracker,
)
from app.db.session import async_session, engine as db_engine
from app.health import check_health
from app.middleware.auth import AuthMiddleware
from app.mt5.connector import MT5BridgeConnector
from app.notifications.telegram import TelegramNotifier


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.logging_config import configure_logging
    configure_logging()

    logger.info("Starting Trading Bot (multi-symbol)...")

    from app.auth import _assert_auth_consistent
    _assert_auth_consistent()

    # Phase 1 observability: slow query logger — attach once, survives entire app lifetime
    install_slow_query_logger(db_engine, threshold_ms=settings.db_slow_query_threshold_ms)

    # Auto-add missing columns/tables (safe for production — IF NOT EXISTS guards)
    # Each statement runs in its own session to isolate transaction abort on error.
    from sqlalchemy import text
    schema_stmts = [
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS trade_reason VARCHAR(255)",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS pre_trade_snapshot JSON",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS post_trade_analysis JSON",
        "ALTER TABLE trades ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_trades_is_archived ON trades (is_archived)",
        """CREATE TABLE IF NOT EXISTS ai_usage_logs (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
            agent_id VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd_sdk DOUBLE PRECISION,
            cost_usd_calc DOUBLE PRECISION,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            turns INTEGER NOT NULL DEFAULT 0,
            tool_calls_count INTEGER NOT NULL DEFAULT 0,
            success BOOLEAN NOT NULL DEFAULT TRUE,
            raw_usage JSON
        )""",
        "CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_timestamp ON ai_usage_logs (timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_agent_id ON ai_usage_logs (agent_id)",
    ]
    for stmt in schema_stmts:
        try:
            async with async_session() as _tmp_session:
                await _tmp_session.execute(text("SET lock_timeout = '5s'"))
                await _tmp_session.execute(text(stmt))
                await _tmp_session.commit()
        except Exception as e:
            logger.warning(f"Schema stmt skipped: {str(e)[:120]}")
    logger.info("DB schema check complete")

    # Mint long-lived JWT so MCP tools can call the backend API (localhost) with auth.
    import os as _os
    from app.auth import mint_internal_token
    _internal_token = mint_internal_token()
    if _internal_token:
        _os.environ["INTERNAL_API_TOKEN"] = _internal_token
        logger.info("Minted INTERNAL_API_TOKEN for MCP tool → backend calls")

    # Initialize shared components
    connector = MT5BridgeConnector()
    redis_client = redis_lib.from_url(settings.redis_url)
    ai_client = AIClient()

    # Create a persistent DB session for bot engines
    db_session = async_session()

    try:
        from app.services import symbol_config_service as symbol_svc
        from app.config import apply_db_symbol_profiles
        async with async_session() as _cfg_session:
            db_profiles = await symbol_svc.load_profiles_from_db(_cfg_session)
        if db_profiles:
            apply_db_symbol_profiles(db_profiles)
            enabled = [s for s, p in db_profiles.items() if p.get("is_enabled") and "canonical" not in p]
            logger.info(f"Symbol profiles loaded from DB: {len(db_profiles)} entries, enabled: {enabled}")
    except Exception as e:
        logger.warning(f"Symbol profile DB load failed (using static defaults): {e}")

    # Initialize BotManager (creates one engine per symbol)
    manager = BotManager(connector, db_session, redis_client)

    # Initialize sentiment analyzer (shared)
    sentiment_analyzer = NewsSentimentAnalyzer(ai_client, db_session, redis_client)
    manager.set_sentiment_analyzer(sentiment_analyzer)

    # Initialize historical data collector (uses first engine's market_data)
    first_engine = next(iter(manager.engines.values()))
    hist_collector = HistoricalDataCollector(first_engine.market_data, db_session)

    # Initialize macro data service
    macro_service = MacroDataService(db_session)
    event_calendar = MacroEventCalendar()
    for engine in manager.engines.values():
        engine._macro_service = macro_service
        engine.context_builder.set_macro_service(macro_service)
        engine.context_builder.set_event_calendar(event_calendar)

    # Initialize optimizer (uses Claude Agent SDK via AIClient)
    optimizer = StrategyOptimizer(ai_client, db_session)
    optimizer.set_collector(hist_collector)
    for engine in manager.engines.values():
        engine._optimizer = optimizer

    # Initialize Telegram notifier
    notifier = TelegramNotifier()
    manager.set_notifier(notifier)
    if notifier.enabled:
        logger.info("Telegram notifications enabled")
    else:
        logger.info("Telegram notifications disabled (no token/chat_id)")

    # Set up routes with manager reference
    bot.set_manager(manager)
    webhooks.init_webhooks(manager)
    backtest.set_market_data(first_engine.market_data)
    backtest.set_collector(hist_collector)
    data.set_collector(hist_collector)
    ml.set_ml_deps(hist_collector, db_session)
    macro.set_macro_deps(macro_service, event_calendar)

    # Store references for health checks
    app.state.manager = manager
    app.state.connector = connector
    app.state.redis = redis_client
    app.state.ai_client = ai_client

    # Initialize metrics
    from app.metrics import Metrics, set_metrics
    metrics = Metrics(redis_client)
    set_metrics(metrics)
    app.state.metrics = metrics

    # Initialize health monitor
    from app.bot.health_monitor import HealthMonitor
    health_monitor = HealthMonitor(connector, manager, notifier)
    app.state.health_monitor = health_monitor

    # Initialize MCP tools (needed for AI agent trading via scheduler)
    try:
        from mcp_server.tools import init_mcp_tools
    except ImportError:
        logger.warning("MCP tools not available (mcp_server not importable)")
    else:
        try:
            init_mcp_tools(redis_client)
            logger.info("MCP tools initialized for AI agent")
        except Exception as e:
            logger.error(f"MCP tools init failed: {e} — AI agent trading may not work")
        try:
            from mcp_server.agents.prompt_registry import init_prompt_registry
            init_prompt_registry(redis_client)
            logger.info("Prompt registry initialized")
        except Exception as e:
            logger.warning(f"Prompt registry init failed: {e}")

    # Restore trading_mode from Redis (survives redeploy)
    try:
        cached_mode = await redis_client.get("trading_mode")
        if cached_mode:
            mode = cached_mode if isinstance(cached_mode, str) else cached_mode.decode()
            if mode in ("strategy", "ai_autonomous"):
                settings.trading_mode = mode
                logger.info(f"Restored trading_mode from Redis: {mode}")
    except Exception as e:
        logger.debug(f"Redis trading_mode restore failed: {e}")

    # Phase 1 observability: pool pressure monitor — Telegram alert on sustained high utilization
    pool_monitor = PoolPressureMonitor(
        db_engine,
        notifier=notifier,
        high_threshold=settings.db_pool_alert_threshold,
        sustained_seconds=settings.db_pool_alert_sustained_seconds,
    )
    app.state.pool_monitor = pool_monitor

    # Start scheduler
    scheduler = BotScheduler(manager)
    scheduler.set_health_monitor(health_monitor)
    scheduler.start()
    scheduler.scheduler.add_job(
        pool_monitor.tick,
        "interval",
        seconds=10,
        id="db_pool_pressure",
        replace_existing=True,
    )
    for engine in manager.engines.values():
        engine._scheduler = scheduler
    app.state.scheduler = scheduler

    if macro_service.is_configured:
        logger.info("FRED macro data service configured")
    else:
        logger.info("FRED macro data disabled (no FRED_API_KEY)")

    # Initialize Runner Manager (non-fatal: app works without it if tables don't exist yet)
    try:
        from app.runner.backend import ProcessRunnerBackend
        from app.runner.heartbeat import RunnerHeartbeatMonitor
        from app.runner.job_queue import JobQueue
        from app.runner.manager import RunnerManager
        from app.vault import vault

        runner_backend = ProcessRunnerBackend()
        runner_db_session = async_session()
        runner_manager = RunnerManager(runner_db_session, redis_client, runner_backend, vault)
        job_queue = JobQueue(runner_db_session, redis_client)
        heartbeat_monitor = RunnerHeartbeatMonitor(
            runner_manager,
            interval_seconds=settings.runner_heartbeat_interval,
            max_misses=settings.runner_heartbeat_max_misses,
        )

        # Rebuild job queue from DB on startup
        await job_queue.rebuild_from_db()

        # Add heartbeat check to scheduler
        scheduler.scheduler.add_job(
            heartbeat_monitor.check_all,
            "interval",
            seconds=settings.runner_heartbeat_interval,
            id="runner_heartbeat",
            replace_existing=True,
        )

        app.state.runner_manager = runner_manager
        app.state.job_queue = job_queue
        app.state.heartbeat_monitor = heartbeat_monitor

        logger.info("Runner manager initialized")
    except Exception as e:
        logger.warning(f"Runner manager init failed (non-fatal): {e}")
        logger.warning("Runner features disabled — run 'alembic upgrade head' to create runner tables")

    # Start symbol-config hot-reload subscriber
    await manager.start_reload_subscriber()

    symbols = manager.get_symbols()
    logger.info(f"Trading Bot initialized — symbols: {symbols}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if hasattr(app.state, "runner_manager"):
        await app.state.runner_manager.shutdown()
    if "runner_db_session" in dir():
        await runner_db_session.close()
    scheduler.stop()
    await manager.stop_reload_subscriber()
    await manager.stop()
    await connector.close()
    if manager._binance_connector:
        await manager._binance_connector.close()
    await db_session.close()
    await redis_client.close()


# Gate Swagger / ReDoc / OpenAPI behind ENABLE_API_DOCS — default off so prod
# doesn't expose the full route catalog to unauthenticated scanners.
_docs_enabled = os.getenv("ENABLE_API_DOCS", "0") == "1"
app = FastAPI(
    title="Trading Bot",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https: wss:; "
            "frame-ancestors 'none'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Phase 1 observability: warn on long-held DB connections per request
app.add_middleware(
    SessionLifetimeMiddleware,
    async_engine=db_engine,
    warn_threshold_ms=settings.db_request_warn_ms,
    error_threshold_ms=settings.db_request_error_ms,
)

# Phase 4 rate limit — Redis token bucket per (IP, path). Fails open if Redis unavailable.
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(
    RateLimitMiddleware,
    sustained_per_minute=settings.rate_limit_per_minute,
    burst_capacity=settings.rate_limit_burst,
)

# Auth middleware disabled — using Bearer token auth (legacy password mode)
# app.add_middleware(AuthMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Routes
app.include_router(admin.router)
app.include_router(auth_router)
app.include_router(webauthn_router)
app.include_router(bot.router)
app.include_router(positions.router)
app.include_router(history.router)
app.include_router(strategy.router)
app.include_router(ai_insights.router)
app.include_router(backtest.router)
app.include_router(market_data.router)
app.include_router(data.router)
app.include_router(ml.router)
app.include_router(macro.router)
app.include_router(analytics.router)
app.include_router(metrics_routes.router)
app.include_router(secrets.router)
app.include_router(runners.router)
app.include_router(jobs.router)
app.include_router(rollout.router)
app.include_router(integration.router)
app.include_router(webhooks.router)
app.include_router(activity.router)
app.include_router(agent_prompts.router)
app.include_router(ai_usage.router)
app.include_router(memory_routes.router)
app.include_router(quant.router)
app.include_router(symbols_routes.router)
app.include_router(ws_router)
app.include_router(ws_runners_router)


@app.get("/health")
async def health():
    mgr = app.state.manager
    first_engine = next(iter(mgr.engines.values())) if mgr.engines else None
    return await check_health(
        first_engine,
        app.state.connector,
        app.state.redis,
        app.state.ai_client,
    )


@app.get("/health/pool")
async def health_pool():
    """Live DB pool stats + recent slow queries + long-hold requests."""
    stats = get_pool_stats(db_engine)
    monitor = getattr(app.state, "pool_monitor", None)
    return {
        "pool": stats,
        "samples": monitor.recent(60) if monitor else [],
        "slow_queries": slow_query_tracker.top(10),
        "long_holds": long_hold_tracker.top(10),
        "thresholds": {
            "alert_utilization": settings.db_pool_alert_threshold,
            "alert_sustained_seconds": settings.db_pool_alert_sustained_seconds,
            "slow_query_ms": settings.db_slow_query_threshold_ms,
            "request_warn_ms": settings.db_request_warn_ms,
            "request_error_ms": settings.db_request_error_ms,
        },
    }
