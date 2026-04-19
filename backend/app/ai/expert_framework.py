"""
Expert Decision Framework — encodes expert trader decision process.

Core principle: Default = don't trade. Must PROVE it's worth trading.

Expert checklist:
1. Market condition tradeable? → if not → sit out
2. Clear setup exists? → if not → sit out
3. Risk/reward acceptable? → if not → sit out
4. Enough confirmations? → if not → sit out
5. All checks pass → trade with appropriate size

4 out of 5 outcomes = "sit out" — experts trade less, but more accurately.
"""

from dataclasses import dataclass


@dataclass
class TradeReasoning:
    """Structured pre-trade reasoning — AI must fill this before any trade."""

    setup: str  # market setup description
    confirmations: list[str]  # list of confirming signals
    confirmation_count: int  # X out of 5
    risk_reward: str  # SL/TP description + ratio
    counter_evidence: str  # what could make this trade fail
    what_would_invalidate: str  # specific condition that kills the thesis
    confidence: float  # 0-1 overall confidence
    position_size_reason: str  # why this lot size
    decision: str  # BUY, SELL, HOLD, UNCERTAIN

    def to_dict(self) -> dict:
        return {
            "setup": self.setup,
            "confirmations": self.confirmations,
            "confirmation_count": self.confirmation_count,
            "risk_reward": self.risk_reward,
            "counter_evidence": self.counter_evidence,
            "what_would_invalidate": self.what_would_invalidate,
            "confidence": round(self.confidence, 3),
            "position_size_reason": self.position_size_reason,
            "decision": self.decision,
        }

    @property
    def is_valid(self) -> bool:
        """Check if reasoning is complete and non-contradictory."""
        if not self.setup or not self.counter_evidence:
            return False
        if self.confirmation_count < 3 and self.decision in ("BUY", "SELL"):
            return False
        return True


def validate_reasoning(reasoning: TradeReasoning) -> tuple[bool, str]:
    """Validate that AI reasoning meets expert standards.

    Returns:
        (approved, rejection_reason)
    """
    # Rule 1: Must have reasoning
    if not reasoning.setup:
        return False, "No setup description — cannot trade without thesis"

    # Rule 2: Must have counter-evidence (anti confirmation bias)
    if not reasoning.counter_evidence:
        return False, "No counter-evidence — confirmation bias risk"

    # Rule 3: Must have enough confirmations for BUY/SELL
    if reasoning.decision in ("BUY", "SELL") and reasoning.confirmation_count < 3:
        return False, f"Only {reasoning.confirmation_count}/5 confirmations — need at least 3"

    # Rule 4: Contradictory reasoning
    if reasoning.decision == "BUY" and "bearish" in reasoning.counter_evidence.lower():
        # This is OK — counter evidence is supposed to be bearish for a buy
        pass

    # Rule 5: Confidence too low
    if reasoning.decision in ("BUY", "SELL") and reasoning.confidence < 0.5:
        return False, f"Confidence {reasoning.confidence:.0%} too low for execution"

    return True, ""


@dataclass
class PostTradeAccountability:
    """Post-trade evaluation — judge process, not just P&L."""

    trade_id: str
    pre_reasoning: TradeReasoning
    actual_outcome: str  # what actually happened
    pnl: float  # actual P&L
    reasoning_correct: bool  # was the thesis correct?
    classification: str  # skilled_win, correct_process, lucky_win, real_mistake

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "decision": self.pre_reasoning.decision,
            "pnl": round(self.pnl, 2),
            "reasoning_correct": self.reasoning_correct,
            "classification": self.classification,
        }


def classify_trade(
    reasoning: TradeReasoning,
    pnl: float,
    reasoning_correct: bool,
) -> str:
    """Classify trade by process quality vs outcome.

    Returns one of:
    - "skilled_win": correct reasoning + profit → reinforce
    - "correct_process": correct reasoning + loss → don't adjust (variance)
    - "lucky_win": wrong reasoning + profit → DON'T reinforce (noise)
    - "real_mistake": wrong reasoning + loss → learn from this
    """
    profitable = pnl > 0

    if reasoning_correct and profitable:
        return "skilled_win"
    elif reasoning_correct and not profitable:
        return "correct_process"
    elif not reasoning_correct and profitable:
        return "lucky_win"
    else:
        return "real_mistake"
