"""
Gold Trading Bot — FastAPI Main Application
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
from app.api.routes import ai_insights, backtest, bot, history, market_data, positions, strategy
from app.api.websocket import router as ws_router
from app.bot.engine import BotEngine
from app.bot.scheduler import BotScheduler
from app.config import settings
from app.db.session import async_session
from app.health import check_health
from app.mt5.connector import MT5BridgeConnector


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gold Trading Bot...")

    # Initialize components
    connector = MT5BridgeConnector()
    redis_client = redis_lib.from_url(settings.redis_url)
    ai_client = AIClient()

    # Create a persistent DB session for bot engine
    db_session = async_session()

    # Initialize bot engine
    bot_engine = BotEngine(connector, db_session, redis_client)

    # Initialize sentiment analyzer
    sentiment_analyzer = NewsSentimentAnalyzer(ai_client, db_session, redis_client)
    bot_engine.set_sentiment_analyzer(sentiment_analyzer)

    # Initialize optimizer if AI available
    if ai_client.client:
        bot_engine._optimizer = StrategyOptimizer(ai_client, db_session)

    # Initialize Telegram notifier
    notifier = TelegramNotifier()
    bot_engine.set_notifier(notifier)
    if notifier.enabled:
        logger.info("Telegram notifications enabled")
    else:
        logger.info("Telegram notifications disabled (no token/chat_id)")

    # Set up routes with bot reference
    bot.set_bot(bot_engine)
    backtest.set_market_data(bot_engine.market_data)

    # Store references for health checks
    app.state.bot = bot_engine
    app.state.connector = connector
    app.state.redis = redis_client
    app.state.ai_client = ai_client

    # Start scheduler
    scheduler = BotScheduler(bot_engine)
    scheduler.start()
    bot_engine._scheduler = scheduler
    app.state.scheduler = scheduler

    logger.info("Gold Trading Bot initialized")

    yield

    # Shutdown
    logger.info("Shutting down...")
    scheduler.stop()
    await bot_engine.stop()
    await db_session.close()
    await redis_client.close()


app = FastAPI(
    title="Gold Trading Bot",
    version="1.0.0",
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
app.include_router(ws_router)


@app.get("/health")
async def health():
    return await check_health(
        app.state.bot,
        app.state.connector,
        app.state.redis,
        app.state.ai_client,
    )
