"""MCP tools for risk management — wraps backend/app/risk/manager.py."""

from app.risk.manager import RiskManager
from app.config import SYMBOL_PROFILES


def _get_risk_manager(symbol: str = "GOLD") -> RiskManager:
    """Create a RiskManager with symbol-specific profile.

    Falls back to defaults if symbol missing from SYMBOL_PROFILES — avoids KeyError
    when GOLD profile is removed/renamed.
    """
    profile = SYMBOL_PROFILES.get(symbol) or {}
    return RiskManager(
        pip_value=profile.get("pip_value", 1.0),
        price_decimals=profile.get("price_decimals", 2),
        sl_atr_mult=profile.get("sl_atr_mult", 1.5),
        tp_atr_mult=profile.get("tp_atr_mult", 2.0),
        max_lot=profile.get("max_lot", 1.0),
    )


def validate_trade(
    symbol: str,
    signal: int,
    current_positions: int,
    daily_pnl: float,
    balance: float,
    ai_sentiment: dict | None = None,
) -> dict:
    """Check if a trade is allowed under risk management rules.

    Args:
        symbol: Trading symbol
        signal: Trade direction (1=BUY, -1=SELL, 0=HOLD)
        current_positions: Number of open positions
        daily_pnl: Today's P&L
        balance: Account balance
        ai_sentiment: Optional sentiment data

    Returns:
        Dict with allowed (bool) and reason.
    """
    rm = _get_risk_manager(symbol)
    allowed, reason = rm.can_open_trade(
        current_positions=current_positions,
        daily_pnl=daily_pnl,
        balance=balance,
        signal=signal,
        ai_sentiment=ai_sentiment,
    )
    return {"allowed": allowed, "reason": reason}


def calculate_lot(
    symbol: str,
    balance: float,
    sl_pips: float,
    atr_pct: float | None = None,
) -> dict:
    """Calculate position size (lot) based on risk parameters.

    Args:
        symbol: Trading symbol
        balance: Account balance
        sl_pips: Stop loss distance in pips
        atr_pct: Optional ATR-based volatility percentage

    Returns:
        Dict with lot size.
    """
    rm = _get_risk_manager(symbol)
    lot = rm.calculate_lot_size(balance=balance, sl_pips=sl_pips, atr_pct=atr_pct)
    return {"symbol": symbol, "lot": lot, "balance": balance, "sl_pips": sl_pips}


def calculate_sl_tp(
    symbol: str,
    entry_price: float,
    signal: int,
    atr: float,
) -> dict:
    """Calculate stop-loss and take-profit levels.

    Args:
        symbol: Trading symbol
        entry_price: Entry price
        signal: Direction (1=BUY, -1=SELL)
        atr: Current ATR value

    Returns:
        Dict with sl and tp prices.
    """
    rm = _get_risk_manager(symbol)
    result = rm.calculate_sl_tp(entry_price=entry_price, signal=signal, atr=atr)
    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "signal": "BUY" if signal == 1 else "SELL",
        "sl": result.sl,
        "tp": result.tp,
        "sl_distance": round(abs(entry_price - result.sl), 5),
        "tp_distance": round(abs(result.tp - entry_price), 5),
    }
