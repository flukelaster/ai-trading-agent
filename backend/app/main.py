"""
Gold Trading Bot — FastAPI Main Application (multi-symbol)
"""

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
    ai_insights,
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
)
from app.api.routes import metrics as metrics_routes
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
from app.db.session import async_session
from app.health import check_health
from app.middleware.auth import AuthMiddleware
from app.mt5.connector import MT5BridgeConnector
from app.notifications.telegram import TelegramNotifier


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.logging_config import configure_logging
    configure_logging()

    logger.info("Starting Trading Bot (multi-symbol)...")

    # Initialize shared components
    connector = MT5BridgeConnector()
    redis_client = redis_lib.from_url(settings.redis_url)
    ai_client = AIClient()

    # Create a persistent DB session for bot engines
    db_session = async_session()

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

    # Initialize optimizer if AI available
    if ai_client.client:
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

    # Start scheduler
    scheduler = BotScheduler(manager)
    scheduler.set_health_monitor(health_monitor)
    scheduler.start()
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
    await manager.stop()
    await connector.close()
    if manager._binance_connector:
        await manager._binance_connector.close()
    await db_session.close()
    await redis_client.close()


app = FastAPI(
    title="Trading Bot",
    version="2.0.0",
    lifespan=lifespan,
)

# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(activity.router)
app.include_router(memory_routes.router)
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
