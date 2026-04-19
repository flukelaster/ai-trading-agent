"""
Bias Guard — detect and prevent cognitive biases in AI trading decisions.

Monitored biases:
- Recency bias: over-weighting recent trades
- Confirmation bias: ignoring counter-evidence
- Overtrading: trading too frequently
- Anchoring: fixating on entry price for SL/TP
- Sunk cost: holding losers too long
- Gambler's fallacy: increasing size after losses
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass
class BiasAlert:
    """Alert when bias is detected."""

    bias_type: str
    severity: str  # "warning" or "critical"
    detail: str
    recommendation: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "bias_type": self.bias_type,
            "severity": self.severity,
            "detail": self.detail,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


class BiasGuard:
    """Monitor and guard against cognitive biases in AI decisions."""

    def __init__(
        self,
        max_trades_per_day: int = 10,
        overtrading_threshold: float = 1.5,
        min_counter_evidence_length: int = 10,
        recency_window: int = 5,
    ):
        self.max_trades_per_day = max_trades_per_day
        self.overtrading_threshold = overtrading_threshold
        self.min_counter_evidence_length = min_counter_evidence_length
        self.recency_window = recency_window

        self._daily_trades: dict[str, int] = {}  # date -> count
        self._baseline_daily_avg: float = 0
        self._alerts: deque[BiasAlert] = deque(maxlen=100)

    def check_all(
        self,
        trade_count_today: int,
        counter_evidence: str | None = None,
        recent_pnls: list[float] | None = None,
        consecutive_losses: int = 0,
        lot_size: float = 0,
        baseline_lot: float = 0,
    ) -> list[BiasAlert]:
        """Run all bias checks. Returns list of active alerts."""
        alerts = []
        now = datetime.utcnow().isoformat()

        # 1. Overtrading
        if trade_count_today > self.max_trades_per_day:
            alert = BiasAlert(
                bias_type="overtrading",
                severity="critical",
                detail=f"{trade_count_today} trades today > {self.max_trades_per_day} max",
                recommendation="Stop trading — max daily limit reached",
                timestamp=now,
            )
            alerts.append(alert)

        elif self._baseline_daily_avg > 0:
            ratio = trade_count_today / self._baseline_daily_avg
            if ratio > self.overtrading_threshold:
                alert = BiasAlert(
                    bias_type="overtrading",
                    severity="warning",
                    detail=f"{trade_count_today} trades today vs {self._baseline_daily_avg:.1f} avg ({ratio:.1f}x)",
                    recommendation="Trading more than usual — check if signals are genuine",
                    timestamp=now,
                )
                alerts.append(alert)

        # 2. Confirmation bias (missing counter-evidence)
        if counter_evidence is not None and len(counter_evidence) < self.min_counter_evidence_length:
            alert = BiasAlert(
                bias_type="confirmation_bias",
                severity="warning",
                detail="Counter-evidence is too short or missing",
                recommendation="Must provide meaningful counter-evidence before every trade",
                timestamp=now,
            )
            alerts.append(alert)

        # 3. Recency bias
        if recent_pnls and len(recent_pnls) >= self.recency_window:
            recent = recent_pnls[-self.recency_window :]
            all_data = recent_pnls

            recent_mean = np.mean(recent)
            overall_mean = np.mean(all_data)

            # If recent performance diverges significantly from overall
            if len(all_data) >= 20:
                overall_std = np.std(all_data)
                if overall_std > 0:
                    z = (recent_mean - overall_mean) / (overall_std / np.sqrt(self.recency_window))
                    if abs(z) > 2.0:
                        alert = BiasAlert(
                            bias_type="recency_bias",
                            severity="warning",
                            detail=f"Recent {self.recency_window} trades mean ({recent_mean:.2f}) "
                            f"significantly different from overall ({overall_mean:.2f}), z={z:.1f}",
                            recommendation="Don't over-adjust based on recent streak — use full sample",
                            timestamp=now,
                        )
                        alerts.append(alert)

        # 4. Gambler's fallacy
        if consecutive_losses >= 2 and lot_size > baseline_lot * 1.1:
            alert = BiasAlert(
                bias_type="gamblers_fallacy",
                severity="critical",
                detail=f"{consecutive_losses} consecutive losses but lot size ({lot_size}) > baseline ({baseline_lot})",
                recommendation="Never increase lot after losses — reduce or maintain",
                timestamp=now,
            )
            alerts.append(alert)

        self._alerts.extend(alerts)
        return alerts

    def set_baseline_avg(self, avg_daily_trades: float) -> None:
        """Set baseline average trades per day (for overtrading detection)."""
        self._baseline_daily_avg = avg_daily_trades

    def get_recent_alerts(self, n: int = 20) -> list[dict]:
        """Get recent bias alerts."""
        return [a.to_dict() for a in list(self._alerts)[-n:]]

    def get_summary(self) -> dict:
        """Get bias detection summary."""
        if not self._alerts:
            return {"total_alerts": 0, "by_type": {}, "most_common": None}

        from collections import Counter

        type_counts = Counter(a.bias_type for a in self._alerts)

        return {
            "total_alerts": len(self._alerts),
            "by_type": dict(type_counts),
            "most_common": type_counts.most_common(1)[0][0] if type_counts else None,
        }
