"""
Trade Accountability — evaluate trade quality by process, not just P&L.

Classification matrix:
- Skilled Win: correct reasoning + profit → reinforce
- Correct Process: correct reasoning + loss → don't adjust (just variance)
- Lucky Win: wrong reasoning + profit → DON'T reinforce (noise)
- Real Mistake: wrong reasoning + loss → learn and adjust

Expert traders learn from process, not from results.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from loguru import logger


@dataclass
class AccountabilityRecord:
    """Single trade accountability evaluation."""

    trade_id: str
    symbol: str
    direction: str  # BUY or SELL
    pnl: float
    pre_trade_setup: str  # what AI expected
    actual_outcome: str  # what actually happened
    reasoning_correct: bool
    classification: str  # skilled_win, correct_process, lucky_win, real_mistake
    lessons: list[str]  # what was learned
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "pnl": round(self.pnl, 2),
            "classification": self.classification,
            "reasoning_correct": self.reasoning_correct,
            "lessons": self.lessons,
            "timestamp": self.timestamp,
        }


class TradeAccountabilityTracker:
    """Tracks and analyzes trade quality over time."""

    def __init__(self):
        self._records: list[AccountabilityRecord] = []
        self._max_records = 500

    def evaluate(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        pnl: float,
        pre_trade_setup: str,
        actual_outcome: str,
        reasoning_correct: bool,
    ) -> AccountabilityRecord:
        """Evaluate a closed trade.

        Args:
            trade_id: unique trade identifier
            symbol: trading symbol
            direction: "BUY" or "SELL"
            pnl: realized P&L
            pre_trade_setup: AI's pre-trade thesis
            actual_outcome: what actually happened in the market
            reasoning_correct: was the thesis correct (regardless of P&L)?
        """
        profitable = pnl > 0

        if reasoning_correct and profitable:
            classification = "skilled_win"
            lessons = ["Thesis confirmed — reinforce this pattern"]
        elif reasoning_correct and not profitable:
            classification = "correct_process"
            lessons = ["Correct analysis but market variance — no adjustment needed"]
        elif not reasoning_correct and profitable:
            classification = "lucky_win"
            lessons = [
                "WARNING: Profit from wrong reasoning — do NOT reinforce this pattern",
                f"Expected: {pre_trade_setup[:100]}",
                f"Actual: {actual_outcome[:100]}",
            ]
        else:
            classification = "real_mistake"
            lessons = [
                f"Learn from: {pre_trade_setup[:100]}",
                f"What happened: {actual_outcome[:100]}",
                "Adjust strategy parameters based on this error",
            ]

        record = AccountabilityRecord(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            pnl=pnl,
            pre_trade_setup=pre_trade_setup,
            actual_outcome=actual_outcome,
            reasoning_correct=reasoning_correct,
            classification=classification,
            lessons=lessons,
            timestamp=datetime.utcnow().isoformat(),
        )

        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records.pop(0)

        logger.info(
            f"Trade [{trade_id}] accountability: {classification} "
            f"(reasoning={'✓' if reasoning_correct else '✗'}, P&L={pnl:+.2f})"
        )

        return record

    def get_summary(self, last_n: int = 50) -> dict:
        """Get accountability summary statistics."""
        recent = self._records[-last_n:]
        if not recent:
            return {"total": 0, "breakdown": {}, "process_accuracy": 0, "pnl_accuracy": 0}

        counts = Counter(r.classification for r in recent)
        total = len(recent)

        # Process accuracy = % of trades with correct reasoning
        process_correct = sum(1 for r in recent if r.reasoning_correct)
        process_accuracy = process_correct / total if total > 0 else 0

        # P&L accuracy = % of profitable trades
        profitable = sum(1 for r in recent if r.pnl > 0)
        pnl_accuracy = profitable / total if total > 0 else 0

        # Lucky ratio = lucky_wins / total_wins (higher = more noise-driven)
        total_wins = counts.get("skilled_win", 0) + counts.get("lucky_win", 0)
        lucky_ratio = counts.get("lucky_win", 0) / total_wins if total_wins > 0 else 0

        return {
            "total": total,
            "breakdown": {
                "skilled_win": counts.get("skilled_win", 0),
                "correct_process": counts.get("correct_process", 0),
                "lucky_win": counts.get("lucky_win", 0),
                "real_mistake": counts.get("real_mistake", 0),
            },
            "process_accuracy": round(process_accuracy, 3),
            "pnl_accuracy": round(pnl_accuracy, 3),
            "lucky_ratio": round(lucky_ratio, 3),
        }

    def get_recent(self, n: int = 20) -> list[dict]:
        """Get recent accountability records."""
        return [r.to_dict() for r in self._records[-n:]]
