"""
Strategy Optimizer — weekly AI-powered parameter optimization with backtest validation.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClient
from app.ai.prompts import OPTIMIZATION_SYSTEM_PROMPT
from app.backtest.engine import BacktestEngine
from app.db.models import AIOptimizationLog, Trade
from app.risk.manager import RiskManager
from app.strategy import get_strategy


@dataclass
class OptimizationResult:
    assessment: str
    current_params: dict
    suggested_params: dict
    confidence: float
    reasoning: str
    backtest_validation: dict | None = None
    log_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "assessment": self.assessment,
            "current_params": self.current_params,
            "suggested_params": self.suggested_params,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "backtest_validation": self.backtest_validation,
            "log_id": self.log_id,
        }


# Valid parameter ranges for validation
PARAM_RANGES = {
    "fast_period": (5, 50),
    "slow_period": (20, 200),
    "rsi_period": (5, 30),
    "rsi_overbought": (60, 85),
    "rsi_oversold": (15, 40),
    "sl_multiplier": (0.5, 3.0),
    "tp_multiplier": (1.0, 5.0),
}


class StrategyOptimizer:
    def __init__(self, ai_client: AIClient, db_session: AsyncSession):
        self.ai = ai_client
        self.db = db_session
        self._collector = None  # Set externally if available

    def set_collector(self, collector):
        self._collector = collector

    async def build_performance_summary(self, days: int = 7) -> str:
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(Trade).where(Trade.open_time >= cutoff).order_by(Trade.open_time)
        )
        trades = result.scalars().all()

        if not trades:
            return "No trades in the last {days} days."

        total = len(trades)
        closed = [t for t in trades if t.profit is not None]
        wins = [t for t in closed if t.profit > 0]
        losses = [t for t in closed if t.profit <= 0]

        avg_profit = sum(t.profit for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.profit for t in losses) / len(losses) if losses else 0
        total_profit = sum(t.profit for t in closed) if closed else 0
        win_rate = len(wins) / len(closed) * 100 if closed else 0

        # Profit factor
        gross_profit = sum(t.profit for t in wins) if wins else 0
        gross_loss = abs(sum(t.profit for t in losses)) if losses else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        summary = f"""Period: last {days} days
Total trades: {total}
Closed trades: {len(closed)}
Win rate: {win_rate:.1f}%
Average profit: {avg_profit:.2f}
Average loss: {avg_loss:.2f}
Total profit: {total_profit:.2f}
Profit factor: {pf:.2f}"""
        return summary

    async def optimize(
        self, current_params: dict, strategy_name: str = "ema_crossover"
    ) -> OptimizationResult | None:
        summary = await self.build_performance_summary()
        user_prompt = f"Current performance:\n{summary}\n\nCurrent params: {json.dumps(current_params)}"

        result = await self.ai.complete_json_async(OPTIMIZATION_SYSTEM_PROMPT, user_prompt, max_tokens=512)
        if result is None:
            logger.warning("AI optimization failed")
            return None

        # Validate suggested params
        suggested = result.get("suggested_params", {})
        for key, (low, high) in PARAM_RANGES.items():
            if key in suggested:
                val = suggested[key]
                if isinstance(val, (int, float)):
                    suggested[key] = max(low, min(high, val))

        # Backtest validation if collector is available
        backtest_validation = None
        should_apply = False
        if self._collector:
            backtest_validation = await self._backtest_compare(
                strategy_name, current_params, suggested
            )
            if backtest_validation:
                should_apply = backtest_validation.get("suggested_better", False)
                logger.info(
                    f"Backtest validation: current score={backtest_validation.get('current_score', 0):.2f}, "
                    f"suggested score={backtest_validation.get('suggested_score', 0):.2f}, "
                    f"apply={should_apply}"
                )

        now = datetime.now(UTC)
        period_start = now - timedelta(days=7)

        # Save to DB
        try:
            log = AIOptimizationLog(
                period_start=period_start,
                period_end=now,
                current_params=json.dumps(current_params),
                suggested_params=json.dumps(suggested),
                rationale=result.get("reasoning", ""),
                confidence=float(result.get("confidence", 0.0)),
                applied=should_apply,
                backtest_result=json.dumps(backtest_validation) if backtest_validation else None,
            )
            self.db.add(log)
            await self.db.commit()
            await self.db.refresh(log)
            log_id = log.id
        except Exception as e:
            logger.error(f"Failed to save optimization log: {e}")
            await self.db.rollback()
            log_id = None

        return OptimizationResult(
            assessment=result.get("assessment", ""),
            current_params=current_params,
            suggested_params=suggested,
            confidence=float(result.get("confidence", 0.0)),
            reasoning=result.get("reasoning", ""),
            backtest_validation=backtest_validation,
            log_id=log_id,
        )

    async def _backtest_compare(
        self, strategy_name: str, current_params: dict, suggested_params: dict
    ) -> dict | None:
        """Backtest current vs suggested params on recent historical data."""
        try:
            from app.config import settings
            # Load last 90 days of data from DB
            to_date = datetime.now(UTC).strftime("%Y-%m-%d")
            from_date = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")
            from app.config import resolve_broker_symbol
            df = await self._collector.load_from_db(
                resolve_broker_symbol(settings.symbol), settings.timeframe, from_date, to_date
            )
            if df.empty or len(df) < 200:
                logger.info("Not enough historical data for backtest validation")
                return None

            risk_manager = RiskManager()

            # Backtest current params
            current_strategy = get_strategy(strategy_name, current_params)
            current_engine = BacktestEngine(current_strategy, risk_manager)
            current_result = current_engine.run(df)

            # Backtest suggested params
            suggested_strategy = get_strategy(strategy_name, suggested_params)
            suggested_engine = BacktestEngine(suggested_strategy, risk_manager)
            suggested_result = suggested_engine.run(df)

            def calc_score(r):
                if r.total_trades < 5:
                    return -999.0
                pf = min(r.profit_factor, 10.0)
                return r.sharpe_ratio * pf * r.win_rate

            current_score = calc_score(current_result)
            suggested_score = calc_score(suggested_result)

            return {
                "current_score": round(current_score, 4),
                "suggested_score": round(suggested_score, 4),
                "suggested_better": suggested_score > current_score,
                "current_metrics": {
                    "trades": current_result.total_trades,
                    "win_rate": round(current_result.win_rate, 4),
                    "profit": round(current_result.total_profit, 2),
                    "sharpe": round(current_result.sharpe_ratio, 4),
                    "max_dd": round(current_result.max_drawdown, 4),
                },
                "suggested_metrics": {
                    "trades": suggested_result.total_trades,
                    "win_rate": round(suggested_result.win_rate, 4),
                    "profit": round(suggested_result.total_profit, 2),
                    "sharpe": round(suggested_result.sharpe_ratio, 4),
                    "max_dd": round(suggested_result.max_drawdown, 4),
                },
                "data_bars": len(df),
            }
        except Exception as e:
            logger.error(f"Backtest comparison failed: {e}")
            return None
