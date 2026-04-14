"""
Hallucination checker — cross-validates AI decision text against actual market data.

Parses claims from the AI's reasoning (RSI values, trend direction, price levels, etc.)
and compares against real indicator data. Flags inconsistencies.
"""

import re
from loguru import logger


async def check_hallucination(decision_text: str, symbol: str, market_data) -> dict:
    """Validate AI decision claims against actual market data.

    Args:
        decision_text: The AI agent's full decision/reasoning text
        symbol: Trading symbol
        market_data: MarketDataService instance for fetching real data

    Returns:
        Dict with flags list, severity, and pass/fail status.
    """
    flags: list[dict] = []
    text = decision_text.lower()

    # Fetch actual data
    try:
        from app.strategy.indicators import ema, rsi, atr, adx, bollinger_bands
        import pandas as pd

        df = await market_data.get_ohlcv(symbol, "M15", 200)
        if df.empty or len(df) < 50:
            return {"status": "skipped", "reason": "insufficient data", "flags": []}

        close = df["close"]
        high = df["high"]
        low = df["low"]
        last_price = float(close.iloc[-1])

        # Calculate actual indicators
        rsi_val = float(rsi(close, 14).iloc[-1])
        adx_result = adx(high, low, close, 14)
        adx_val = float(adx_result["adx"].iloc[-1])
        di_plus = float(adx_result["di_plus"].iloc[-1])
        di_minus = float(adx_result["di_minus"].iloc[-1])
        ema_20 = float(ema(close, 20).iloc[-1])
        ema_50 = float(ema(close, 50).iloc[-1])
        bb = bollinger_bands(close, 20, 2.0)
        bb_pct_b = float(bb["pct_b"].iloc[-1])
        atr_val = float(atr(high, low, close, 14).iloc[-1])

        actual = {
            "rsi": rsi_val,
            "adx": adx_val,
            "di_plus": di_plus,
            "di_minus": di_minus,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "price": last_price,
            "bb_pct_b": bb_pct_b,
            "atr": atr_val,
        }

    except Exception as e:
        logger.warning(f"Hallucination check data fetch failed: {e}")
        return {"status": "error", "reason": str(e), "flags": []}

    # ─── Check RSI claims ────────────────────────────────────────────

    # Check "RSI overbought" claim
    if "overbought" in text and "rsi" in text:
        if rsi_val < 65:
            flags.append({
                "claim": "RSI overbought",
                "actual": f"RSI = {rsi_val:.1f} (not overbought, needs > 70)",
                "severity": "high",
            })

    # Check "RSI oversold" claim
    if "oversold" in text and "rsi" in text:
        if rsi_val > 35:
            flags.append({
                "claim": "RSI oversold",
                "actual": f"RSI = {rsi_val:.1f} (not oversold, needs < 30)",
                "severity": "high",
            })

    # Check claimed RSI value vs actual
    rsi_match = re.search(r'rsi[:\s]+(\d+\.?\d*)', text)
    if rsi_match:
        claimed_rsi = float(rsi_match.group(1))
        if abs(claimed_rsi - rsi_val) > 5:
            flags.append({
                "claim": f"RSI = {claimed_rsi:.1f}",
                "actual": f"RSI = {rsi_val:.1f} (off by {abs(claimed_rsi - rsi_val):.1f})",
                "severity": "high" if abs(claimed_rsi - rsi_val) > 10 else "medium",
            })

    # ─── Check ADX / trend strength claims ────────────────────────────

    if "strong trend" in text or "trending" in text:
        if adx_val < 20:
            flags.append({
                "claim": "strong trend / trending",
                "actual": f"ADX = {adx_val:.1f} (weak, needs > 25 for trend)",
                "severity": "high",
            })

    if "weak trend" in text or "ranging" in text or "sideways" in text:
        if adx_val > 30:
            flags.append({
                "claim": "weak trend / ranging",
                "actual": f"ADX = {adx_val:.1f} (strong trend, > 30)",
                "severity": "medium",
            })

    # Check ADX value claim
    adx_match = re.search(r'adx[:\s]+(\d+\.?\d*)', text)
    if adx_match:
        claimed_adx = float(adx_match.group(1))
        if abs(claimed_adx - adx_val) > 3:
            flags.append({
                "claim": f"ADX = {claimed_adx:.1f}",
                "actual": f"ADX = {adx_val:.1f} (off by {abs(claimed_adx - adx_val):.1f})",
                "severity": "medium",
            })

    # ─── Check trend direction claims ─────────────────────────────────

    actual_trend = "bullish" if ema_20 > ema_50 else "bearish"

    if "bullish" in text and "trend" in text and actual_trend == "bearish":
        flags.append({
            "claim": "bullish trend",
            "actual": f"EMA20 ({ema_20:.2f}) < EMA50 ({ema_50:.2f}) → bearish",
            "severity": "high",
        })

    if "bearish" in text and "trend" in text and actual_trend == "bullish":
        if "weak bearish" not in text and "not bearish" not in text:
            flags.append({
                "claim": "bearish trend",
                "actual": f"EMA20 ({ema_20:.2f}) > EMA50 ({ema_50:.2f}) → bullish",
                "severity": "high",
            })

    # ─── Check price claims ──────────────────────────────────────────

    price_match = re.search(r'(?:price|ราคา)[:\s]*(\d{3,5}\.?\d*)', text)
    if price_match:
        claimed_price = float(price_match.group(1))
        pct_diff = abs(claimed_price - last_price) / last_price * 100
        if pct_diff > 0.5:
            flags.append({
                "claim": f"price = {claimed_price}",
                "actual": f"price = {last_price:.2f} (off by {pct_diff:.2f}%)",
                "severity": "high" if pct_diff > 2 else "medium",
            })

    # ─── Check BUY/SELL consistency with indicators ──────────────────

    # AI says BUY but indicators are bearish
    if re.search(r'\bbuy\b', text) and not re.search(r'\bhold\b.*buy|don.*buy|no.*buy|not.*buy', text):
        bearish_count = sum([
            rsi_val > 75,
            actual_trend == "bearish",
            di_minus > di_plus + 5,
            bb_pct_b > 1.0,
        ])
        if bearish_count >= 3:
            flags.append({
                "claim": "BUY signal",
                "actual": f"{bearish_count}/4 indicators are bearish (RSI={rsi_val:.0f}, trend={actual_trend}, DI->{di_minus:.0f}>DI+{di_plus:.0f})",
                "severity": "high",
            })

    # AI says SELL but indicators are bullish
    if re.search(r'\bsell\b', text) and not re.search(r'\bhold\b.*sell|don.*sell|no.*sell|not.*sell', text):
        bullish_count = sum([
            rsi_val < 25,
            actual_trend == "bullish",
            di_plus > di_minus + 5,
            bb_pct_b < 0.0,
        ])
        if bullish_count >= 3:
            flags.append({
                "claim": "SELL signal",
                "actual": f"{bullish_count}/4 indicators are bullish (RSI={rsi_val:.0f}, trend={actual_trend}, DI+{di_plus:.0f}>DI-{di_minus:.0f})",
                "severity": "high",
            })

    # ─── Result ──────────────────────────────────────────────────────

    high_flags = [f for f in flags if f["severity"] == "high"]

    return {
        "status": "fail" if high_flags else "pass",
        "flags": flags,
        "high_severity_count": len(high_flags),
        "total_flags": len(flags),
        "actual_indicators": {
            "rsi": round(rsi_val, 1),
            "adx": round(adx_val, 1),
            "trend": actual_trend,
            "price": round(last_price, 2),
        },
    }
