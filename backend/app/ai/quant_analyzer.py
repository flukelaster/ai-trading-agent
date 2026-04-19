"""
AI Quant Analyzer — Claude AI analyzes quant metrics and suggests parameter adjustments.

Daily analysis cycle:
1. Collect quant metrics (GARCH accuracy, regime correctness, correlation changes)
2. Evaluate strategy performance per regime
3. Suggest parameter adjustments with reasoning
4. Pass through statistical gate before applying
"""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger


@dataclass
class QuantAnalysis:
    """Result of AI quant analysis."""

    timestamp: str
    garch_accuracy: dict  # forecast vs realized comparison
    regime_accuracy: dict  # predicted regime vs actual performance
    correlation_changes: list  # significant correlation shifts
    strategy_performance: dict  # per-strategy metrics in current regime
    suggestions: list[dict]  # parameter change suggestions
    reasoning: str  # overall AI reasoning

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "garch_accuracy": self.garch_accuracy,
            "regime_accuracy": self.regime_accuracy,
            "correlation_changes": self.correlation_changes,
            "strategy_performance": self.strategy_performance,
            "suggestions": self.suggestions,
            "reasoning": self.reasoning,
        }


async def build_quant_context(engines: dict) -> dict:
    """Build context dict from current quant state for AI analysis."""
    from app.risk.garch import fit_garch
    from app.risk.var import compute_var
    from app.strategy.quant_signals import compute_all_signals

    context = {"symbols": {}, "timestamp": datetime.utcnow().isoformat()}

    for sym, engine in engines.items():
        try:
            df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 200)
            if df is None or len(df) < 50:
                continue

            prices = df["close"].values

            var_result = compute_var(prices, method="historical")
            garch_result = fit_garch(prices)
            signals = compute_all_signals(prices)

            regime = str(getattr(engine, "_last_regime", "normal"))

            context["symbols"][sym] = {
                "var": var_result.to_dict(),
                "garch": garch_result.to_dict(),
                "signals": signals.to_dict(),
                "regime": regime,
                "last_sentiment": getattr(engine, "_last_sentiment", None),
            }
        except Exception as e:
            logger.warning(f"Quant context build failed for {sym}: {e}")

    return context


async def analyze_quant_metrics(
    ai_client,
    engines: dict,
    recent_trades: list[dict] | None = None,
) -> QuantAnalysis:
    """Run AI analysis on quant metrics.

    Args:
        ai_client: AIClient instance
        engines: {symbol: BotEngine}
        recent_trades: list of recent trade dicts for performance analysis
    """
    context = await build_quant_context(engines)

    system_prompt = """You are a quantitative analyst reviewing trading system metrics.
Analyze the provided quant data and suggest parameter adjustments.

Rules:
- Only suggest changes backed by statistical evidence
- Each suggestion must include: parameter, current_value, suggested_value, reasoning
- Be conservative — small adjustments only (max ±20% change)
- If metrics look healthy, say "no changes needed"
- Focus on: GARCH forecast accuracy, regime detection quality, correlation stability

Respond in JSON format:
{
  "garch_accuracy": {"assessment": "...", "score": 0-1},
  "regime_accuracy": {"assessment": "...", "score": 0-1},
  "correlation_changes": [{"pair": "...", "status": "stable|shifting|broken"}],
  "suggestions": [{"parameter": "...", "current": ..., "suggested": ..., "reasoning": "..."}],
  "reasoning": "overall assessment in 2-3 sentences"
}"""

    user_prompt = f"Current quant metrics:\n{context}"
    if recent_trades:
        user_prompt += f"\n\nRecent trades (last 7 days): {len(recent_trades)} trades"

    try:
        result = await ai_client.complete_json_async(system_prompt, user_prompt, max_tokens=1024, agent_id="quant")

        if result is None:
            return QuantAnalysis(
                timestamp=datetime.utcnow().isoformat(),
                garch_accuracy={},
                regime_accuracy={},
                correlation_changes=[],
                strategy_performance={},
                suggestions=[],
                reasoning="AI analysis failed — no response",
            )

        return QuantAnalysis(
            timestamp=datetime.utcnow().isoformat(),
            garch_accuracy=result.get("garch_accuracy", {}),
            regime_accuracy=result.get("regime_accuracy", {}),
            correlation_changes=result.get("correlation_changes", []),
            strategy_performance=result.get("strategy_performance", {}),
            suggestions=result.get("suggestions", []),
            reasoning=result.get("reasoning", ""),
        )

    except Exception as e:
        logger.error(f"AI quant analysis failed: {e}")
        return QuantAnalysis(
            timestamp=datetime.utcnow().isoformat(),
            garch_accuracy={},
            regime_accuracy={},
            correlation_changes=[],
            strategy_performance={},
            suggestions=[],
            reasoning=f"Analysis error: {e}",
        )
