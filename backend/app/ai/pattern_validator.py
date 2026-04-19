"""
Pattern Validation Pipeline — multi-layer validation for AI-discovered patterns.

Prevents hallucination by requiring:
Layer 1: Backtest verification (does it actually work?)
Layer 2: Statistical test (better than random?)
Layer 3: Cross-validation (works across symbols?)
Layer 4: Confidence decay (patterns expire if not confirmed)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from loguru import logger


@dataclass
class PatternRecord:
    """A pattern discovered by AI, tracked with validation state."""

    pattern_id: str
    description: str
    discovered_at: str
    confidence: float  # 0-1, decays over time
    validation_layers: dict  # which layers passed
    evidence_count: int = 0  # times pattern was confirmed
    last_confirmed: str = ""
    decay_rate: float = 0.02  # confidence loss per day without confirmation
    status: str = "pending"  # pending, validated, expired, rejected

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "description": self.description,
            "discovered_at": self.discovered_at,
            "confidence": round(self.confidence, 3),
            "validation_layers": self.validation_layers,
            "evidence_count": self.evidence_count,
            "last_confirmed": self.last_confirmed,
            "status": self.status,
        }


class PatternValidator:
    """Multi-layer validation pipeline for AI-discovered trading patterns."""

    def __init__(
        self,
        min_backtest_trades: int = 20,
        min_win_rate: float = 0.52,
        p_value_threshold: float = 0.05,
        min_symbols: int = 2,
        decay_rate: float = 0.02,
        expire_days: int = 30,
    ):
        self.min_backtest_trades = min_backtest_trades
        self.min_win_rate = min_win_rate
        self.p_value_threshold = p_value_threshold
        self.min_symbols = min_symbols
        self.decay_rate = decay_rate
        self.expire_days = expire_days
        self._patterns: dict[str, PatternRecord] = {}

    def validate_pattern(
        self,
        pattern_id: str,
        description: str,
        backtest_results: dict | None = None,
        cross_symbol_results: dict[str, dict] | None = None,
    ) -> PatternRecord:
        """Run full validation pipeline on a pattern.

        Args:
            pattern_id: unique identifier
            description: human-readable description
            backtest_results: {"trades": int, "win_rate": float, "sharpe": float, "pnls": [...]}
            cross_symbol_results: {symbol: {"win_rate": float, "trades": int}}
        """
        now = datetime.utcnow().isoformat()
        layers = {}

        # Layer 1: Backtest verification
        if backtest_results:
            trades = backtest_results.get("trades", 0)
            win_rate = backtest_results.get("win_rate", 0)
            layers["backtest"] = {
                "passed": trades >= self.min_backtest_trades and win_rate >= self.min_win_rate,
                "trades": trades,
                "win_rate": round(win_rate, 3),
                "min_required": self.min_backtest_trades,
            }
        else:
            layers["backtest"] = {"passed": False, "reason": "no backtest data"}

        # Layer 2: Statistical significance
        pnls = backtest_results.get("pnls", []) if backtest_results else []
        if len(pnls) >= 20:
            pnl_arr = np.array(pnls)
            observed_mean = pnl_arr.mean()

            # Permutation test
            count = 0
            for _ in range(500):
                shuffled = pnl_arr * np.random.choice([-1, 1], size=len(pnl_arr))
                if shuffled.mean() >= observed_mean:
                    count += 1
            p_value = count / 500

            layers["statistical"] = {
                "passed": p_value < self.p_value_threshold,
                "p_value": round(p_value, 4),
                "threshold": self.p_value_threshold,
            }
        else:
            layers["statistical"] = {"passed": False, "reason": "insufficient data"}

        # Layer 3: Cross-symbol validation
        if cross_symbol_results:
            passing_symbols = sum(
                1
                for r in cross_symbol_results.values()
                if r.get("win_rate", 0) >= self.min_win_rate and r.get("trades", 0) >= 10
            )
            layers["cross_symbol"] = {
                "passed": passing_symbols >= self.min_symbols,
                "passing_symbols": passing_symbols,
                "total_symbols": len(cross_symbol_results),
                "min_required": self.min_symbols,
            }
        else:
            layers["cross_symbol"] = {"passed": False, "reason": "no cross-symbol data"}

        # Overall: need at least 2/3 layers to pass
        passed_count = sum(1 for v in layers.values() if v.get("passed", False))
        status = "validated" if passed_count >= 2 else "rejected"
        confidence = min(0.9, passed_count / 3) if status == "validated" else 0.1

        record = PatternRecord(
            pattern_id=pattern_id,
            description=description,
            discovered_at=now,
            confidence=confidence,
            validation_layers=layers,
            status=status,
        )

        self._patterns[pattern_id] = record
        logger.info(f"Pattern [{pattern_id}] validated: {status} (layers passed: {passed_count}/3)")

        return record

    def confirm_pattern(self, pattern_id: str) -> None:
        """Record evidence that confirms a pattern (resets decay)."""
        if pattern_id in self._patterns:
            p = self._patterns[pattern_id]
            p.evidence_count += 1
            p.last_confirmed = datetime.utcnow().isoformat()
            p.confidence = min(1.0, p.confidence + 0.05)
            logger.debug(f"Pattern [{pattern_id}] confirmed (evidence #{p.evidence_count})")

    def decay_all(self) -> list[str]:
        """Apply daily confidence decay. Returns list of expired pattern IDs."""
        expired = []
        for pid, record in list(self._patterns.items()):
            if record.status == "expired":
                continue

            record.confidence -= self.decay_rate
            if record.confidence <= 0:
                record.status = "expired"
                expired.append(pid)
                logger.info(f"Pattern [{pid}] expired (confidence decayed to 0)")

            # Check age-based expiration
            discovered = datetime.fromisoformat(record.discovered_at)
            if datetime.utcnow() - discovered > timedelta(days=self.expire_days):
                if record.evidence_count < 3:
                    record.status = "expired"
                    expired.append(pid)

        return expired

    def get_active_patterns(self) -> list[PatternRecord]:
        """Return all validated, non-expired patterns."""
        return [p for p in self._patterns.values() if p.status == "validated"]

    def get_all_patterns(self) -> list[dict]:
        """Return all patterns as dicts (for API/frontend)."""
        return [p.to_dict() for p in self._patterns.values()]
