"""
Gold Trading Bot — FastAPI Main Application (multi-symbol)
"""

from contextlib import asynccontextmanager

import redis.asyncio as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.ai.client import AIClient
from app.ai.news_sentiment import NewsSentimentAnalyzer
from app.ai.strategy_optimizer import StrategyOptimizer
from app.notifications.telegram import TelegramNotifier
from app.api.routes import ai_insights, backtest, bot, data, history, market_data, ml, macro, positions, strategy
from app.data.collector import HistoricalDataCollector
from app.data.macro import MacroDataService
from app.data.macro_events import MacroEventCalendar
from app.api.websocket import router as ws_router
from app.bot.manager import BotManager
from app.bot.scheduler import BotScheduler
from app.config import settings
from app.db.session import async_session
from app.health import check_health
from app.mt5.connector import MT5BridgeConnector


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    # Start scheduler
    scheduler = BotScheduler(manager)
    scheduler.start()
    for engine in manager.engines.values():
        engine._scheduler = scheduler
    app.state.scheduler = scheduler

    if macro_service.is_configured:
        logger.info("FRED macro data service configured")
    else:
        logger.info("FRED macro data disabled (no FRED_API_KEY)")

    symbols = manager.get_symbols()
    logger.info(f"Trading Bot initialized — symbols: {symbols}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    scheduler.stop()
    await manager.stop()
    await connector.close()
    await db_session.close()
    await redis_client.close()


app = FastAPI(
    title="Trading Bot",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
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
app.include_router(ws_router)


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
