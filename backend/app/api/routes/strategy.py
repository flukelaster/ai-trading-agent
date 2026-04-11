"""
Strategy API routes.
"""

from fastapi import APIRouter

from app.api.routes.bot import _get_engine
from app.strategy import STRATEGIES

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/available")
async def get_available_strategies():
    return {
        "strategies": [
            {"name": name, "class": cls.__name__}
            for name, cls in STRATEGIES.items()
        ]
    }


@router.get("/current")
async def get_current_strategy():
    bot = _get_engine()
    return {
        "name": bot.strategy.name,
        "params": bot.strategy.get_params(),
    }
