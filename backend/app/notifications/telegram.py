"""
Telegram Notifier — sends alerts for trades, sentiment, and errors.
"""

import httpx
from loguru import logger

from app.config import settings

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)

    async def _send(self, text: str):
        if not self.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    TELEGRAM_API.format(token=self.token),
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def send_trade_alert(
        self, trade_type: str, symbol: str, price: float, sl: float, tp: float, lot: float, sentiment_label: str = "", extra: str = ""
    ):
        icon = "🟢" if trade_type == "BUY" else "🔴" if trade_type == "SELL" else "⏹"
        sentiment = f" | Sentiment: {sentiment_label}" if sentiment_label else ""
        extra_text = f"\nResult: {extra}" if extra else ""
        text = f"{icon} <b>{trade_type}</b> {symbol} @ {price:.2f}\nLot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}{sentiment}{extra_text}"
        await self._send(text)

    async def send_sentiment_alert(self, label: str, score: float, key_factors: list[str], symbol: str = ""):
        icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(label, "⚪")
        factors = ", ".join(key_factors[:3]) if key_factors else "N/A"
        if symbol:
            text = f"{icon} <b>Sentiment [{symbol}]: {label.upper()}</b> (score: {score:+.2f})\nFactors: {factors}"
        else:
            text = f"{icon} <b>Sentiment: {label.upper()}</b> (score: {score:+.2f})\nFactors: {factors}"
        await self._send(text)

    async def send_optimization_report(self, assessment: str, confidence: float):
        text = f"🤖 <b>Weekly Optimization</b>\n{assessment}\nConfidence: {confidence:.0%}"
        await self._send(text)

    async def send_daily_report(self, trades: int, pnl: float, win_rate: float):
        icon = "📈" if pnl >= 0 else "📉"
        text = f"{icon} <b>Daily Report</b>\nTrades: {trades} | P&L: ${pnl:.2f} | Win Rate: {win_rate:.1%}"
        await self._send(text)

    async def send_message(self, text: str):
        await self._send(text)

    async def send_error_alert(self, error: str):
        text = f"⚠️ <b>Error</b>\n{error[:500]}"
        await self._send(text)
