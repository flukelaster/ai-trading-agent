"""
Multiple Confirmation Gate — requires 3/5 independent confirmations before trading.

Confirmations:
1. Quant signal (z-score, momentum, breakout)
2. ML prediction (LightGBM confidence > threshold)
3. Regime match (HMM state suitable for strategy)
4. Risk/reward (TP/SL ratio > 1.5)
5. AI reasoning (Claude analysis agrees)

If only 2 pass → NO TRADE, even if each is highly confident.
"""

from dataclasses import dataclass


@dataclass
class Confirmation:
    """A single confirmation source."""

    name: str
    passed: bool
    confidence: float  # 0-1
    detail: str  # human-readable explanation

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "confidence": round(self.confidence, 3),
            "detail": self.detail,
        }


@dataclass
class ConfirmationResult:
    """Result of the confirmation gate."""

    confirmations: list[Confirmation]
    passed_count: int
    required: int
    approved: bool
    decision: str  # BUY, SELL, HOLD, UNCERTAIN

    def to_dict(self) -> dict:
        return {
            "confirmations": [c.to_dict() for c in self.confirmations],
            "passed_count": self.passed_count,
            "required": self.required,
            "approved": self.approved,
            "decision": self.decision,
        }


class ConfirmationGate:
    """Gate that requires multiple independent confirmations."""

    def __init__(self, required: int = 3):
        self.required = required

    def evaluate(
        self,
        signal: int,
        quant_signals: dict | None = None,
        ml_prediction: dict | None = None,
        regime: dict | None = None,
        risk_reward: dict | None = None,
        ai_reasoning: dict | None = None,
    ) -> ConfirmationResult:
        """Evaluate all confirmation sources.

        Args:
            signal: proposed signal (1=BUY, -1=SELL)
            quant_signals: {"z_score": float, "momentum_factor": float, ...}
            ml_prediction: {"signal": int, "confidence": float}
            regime: {"label": str, "probabilities": dict}
            risk_reward: {"ratio": float, "sl": float, "tp": float}
            ai_reasoning: {"agrees": bool, "confidence": float, "reasoning": str}
        """
        confirmations = []

        # 1. Quant signal confirmation
        if quant_signals:
            z = quant_signals.get("z_score", 0)
            mom = quant_signals.get("momentum_factor", 0)
            # BUY confirmed if z_score < -1.5 (oversold) or momentum positive
            # SELL confirmed if z_score > 1.5 (overbought) or momentum negative
            if signal == 1:
                quant_agrees = z < -1.0 or mom > 0.5
            elif signal == -1:
                quant_agrees = z > 1.0 or mom < -0.5
            else:
                quant_agrees = False

            confirmations.append(
                Confirmation(
                    name="quant_signal",
                    passed=quant_agrees,
                    confidence=min(abs(z) / 2, 1.0),
                    detail=f"z-score={z:.2f}, momentum={mom:.2f}",
                )
            )
        else:
            confirmations.append(Confirmation("quant_signal", False, 0, "no data"))

        # 2. ML prediction
        if ml_prediction:
            ml_signal = ml_prediction.get("signal", 0)
            ml_conf = ml_prediction.get("confidence", 0)
            ml_agrees = ml_signal == signal and ml_conf > 0.6

            confirmations.append(
                Confirmation(
                    name="ml_prediction",
                    passed=ml_agrees,
                    confidence=ml_conf,
                    detail=f"ML signal={ml_signal}, confidence={ml_conf:.0%}",
                )
            )
        else:
            confirmations.append(Confirmation("ml_prediction", False, 0, "no model"))

        # 3. Regime match
        if regime:
            regime_label = regime.get("label", "normal")
            # BUY in trending is good, SELL in trending is good
            # BUY/SELL in ranging → less confident (mean reversion preferred)
            regime_suitable = regime_label != "ranging" or abs(signal) == 0

            confirmations.append(
                Confirmation(
                    name="regime_match",
                    passed=regime_suitable,
                    confidence=regime.get("probabilities", {}).get(regime_label, 0.5),
                    detail=f"regime={regime_label}",
                )
            )
        else:
            confirmations.append(Confirmation("regime_match", False, 0, "no data"))

        # 4. Risk/reward
        if risk_reward:
            ratio = risk_reward.get("ratio", 0)
            rr_good = ratio >= 1.5

            confirmations.append(
                Confirmation(
                    name="risk_reward",
                    passed=rr_good,
                    confidence=min(ratio / 3.0, 1.0),
                    detail=f"R:R={ratio:.1f}",
                )
            )
        else:
            confirmations.append(Confirmation("risk_reward", False, 0, "no data"))

        # 5. AI reasoning
        if ai_reasoning:
            ai_agrees = ai_reasoning.get("agrees", False)
            ai_conf = ai_reasoning.get("confidence", 0)

            confirmations.append(
                Confirmation(
                    name="ai_reasoning",
                    passed=ai_agrees,
                    confidence=ai_conf,
                    detail=ai_reasoning.get("reasoning", "")[:100],
                )
            )
        else:
            confirmations.append(Confirmation("ai_reasoning", False, 0, "no analysis"))

        # Decision
        passed = sum(1 for c in confirmations if c.passed)
        approved = passed >= self.required

        if not approved and signal != 0:
            decision = "UNCERTAIN"
        elif approved and signal == 1:
            decision = "BUY"
        elif approved and signal == -1:
            decision = "SELL"
        else:
            decision = "HOLD"

        return ConfirmationResult(
            confirmations=confirmations,
            passed_count=passed,
            required=self.required,
            approved=approved,
            decision=decision,
        )
