"""
Strategy API routes.
"""

from fastapi import APIRouter

from app.api.routes.bot import _get_engine
from app.strategy import STRATEGIES

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/available")
async def get_available_strategies():
    strategies = []
    for name, cls in STRATEGIES.items():
        try:
            instance = cls()
            worst_case = instance.worst_case
        except Exception:
            worst_case = ""
        strategies.append({"name": name, "class": cls.__name__, "worst_case": worst_case})
    return {"strategies": strategies}


@router.get("/current")
async def get_current_strategy():
    bot = _get_engine()
    return {
        "name": bot.strategy.name,
        "params": bot.strategy.get_params(),
    }
