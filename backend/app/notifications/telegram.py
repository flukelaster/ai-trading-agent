"""
Telegram Notifier — ส่งแจ้งเตือนการเทรด, sentiment, และ error ภาษาไทย
"""

import httpx
from loguru import logger

from app.config import SYMBOL_PROFILES, settings

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

SENTIMENT_TH = {"bullish": "ขาขึ้น", "bearish": "ขาลง", "neutral": "ทรงตัว"}

# Optional Thai overrides for well-known canonicals. Any symbol not listed
# falls back to the display_name from its SYMBOL_PROFILES entry, then the
# raw symbol — so user-added instruments never show as `None`.
SYMBOL_TH = {
    "GOLD": "ทองคำ",
    "OILCash": "น้ำมัน WTI",
    "BTCUSD": "Bitcoin",
    "USDJPY": "USD/JPY",
}


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

    def _sym(self, symbol: str) -> str:
        if symbol in SYMBOL_TH:
            return SYMBOL_TH[symbol]
        profile = SYMBOL_PROFILES.get(symbol) or {}
        return profile.get("display_name") or symbol

    async def send_trade_alert(
        self, trade_type: str, symbol: str, price: float, sl: float, tp: float, lot: float, sentiment_label: str = "", extra: str = ""
    ):
        is_close = "CLOSE" in trade_type.upper()
        if is_close:
            icon = "🏁"
            action = "ปิดสถานะ"
            lines = [
                f"{icon} <b>{action} {self._sym(symbol)}</b>",
                f"💰 ราคาปิด: {price:.2f}  |  Lot: {lot}",
            ]
            if extra:
                lines.append(f"📊 ผลลัพธ์: <b>{extra}</b>")
        else:
            icon = "🟢" if "BUY" in trade_type.upper() else "🔴"
            action = "ซื้อ" if "BUY" in trade_type.upper() else "ขาย"
            paper = " [จำลอง]" if "PAPER" in trade_type.upper() else ""
            lines = [
                f"{icon} <b>{action} {self._sym(symbol)}{paper}</b>",
                f"💵 ราคา: {price:.2f}  |  Lot: {lot}",
                f"🛑 SL: {sl:.2f}  |  🎯 TP: {tp:.2f}",
            ]
            if sentiment_label:
                s_th = SENTIMENT_TH.get(sentiment_label, sentiment_label)
                lines.append(f"📰 Sentiment: {s_th}")
        await self._send("\n".join(lines))

    async def send_sentiment_alert(self, label: str, score: float, key_factors: list[str], symbol: str = ""):
        icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(label, "⚪")
        s_th = SENTIMENT_TH.get(label, label)
        sym_name = self._sym(symbol) if symbol else "ตลาด"
        factors = "\n".join(f"  • {f}" for f in key_factors[:4]) if key_factors else "  • ไม่มีข้อมูล"
        lines = [
            f"{icon} <b>วิเคราะห์ข่าว {sym_name}</b>",
            f"📊 ทิศทาง: <b>{s_th}</b> ({score:+.2f})",
            f"📌 ปัจจัยสำคัญ:\n{factors}",
        ]
        await self._send("\n".join(lines))

    async def send_optimization_report(self, assessment: str, confidence: float):
        lines = [
            "🤖 <b>รายงาน Optimization รายสัปดาห์</b>",
            f"📋 {assessment}",
            f"🎯 ความมั่นใจ: {confidence:.0%}",
        ]
        await self._send("\n".join(lines))

    async def send_daily_report(self, trades: int, pnl: float, win_rate: float):
        icon = "📈" if pnl >= 0 else "📉"
        pnl_color = "กำไร" if pnl >= 0 else "ขาดทุน"
        lines = [
            f"{icon} <b>สรุปผลประจำวัน</b>",
            f"📊 เทรด: {trades} ครั้ง  |  อัตราชนะ: {win_rate:.1%}",
            f"💰 {pnl_color}: <b>${abs(pnl):.2f}</b>",
        ]
        await self._send("\n".join(lines))

    async def send_message(self, text: str):
        await self._send(text)

    async def send_error_alert(self, error: str):
        lines = [
            "⚠️ <b>แจ้งเตือนข้อผิดพลาด</b>",
            f"❌ {error[:500]}",
        ]
        await self._send("\n".join(lines))

    async def send_health_alert(self, status: str, details: str):
        if status == "recovered":
            text = f"✅ <b>ระบบกลับมาปกติ</b>\n{details}"
        else:
            text = f"🚨 <b>ระบบมีปัญหา</b>\n{details}"
        await self._send(text)

    async def send_start_alert(self, symbol: str, timeframe: str, mode: str = "AI Autonomous"):
        sym_name = self._sym(symbol)
        lines = [
            "▶️ <b>เริ่มเทรด</b>",
            f"📈 สินค้า: {sym_name} ({symbol})",
            f"⏱ Timeframe: {timeframe}",
            f"🤖 โหมด: {mode}",
        ]
        await self._send("\n".join(lines))

    async def send_stop_alert(self, symbol: str = ""):
        sym_name = f" {self._sym(symbol)}" if symbol else ""
        await self._send(f"⏹ <b>หยุดเทรด{sym_name}</b>")

    async def send_daily_summary(self, symbol_stats: list[dict], total_pnl: float, total_trades: int, total_win_rate: float):
        icon = "📈" if total_pnl >= 0 else "📉"
        lines = [
            f"{icon} <b>สรุปประจำวัน</b>",
            f"💰 P&L: <b>${total_pnl:+.2f}</b>  |  เทรด: {total_trades}  |  ชนะ: {total_win_rate:.0%}",
            "",
        ]
        for s in symbol_stats:
            regime_icon = {"trending_high_vol": "🔥", "trending_low_vol": "📊", "ranging": "↔️", "normal": "⚖️"}.get(s.get("regime", ""), "⚖️")
            pnl_str = f"${s['pnl']:+.2f}" if s.get("pnl") is not None else "—"
            lines.append(f"{regime_icon} {self._sym(s['symbol'])}: {pnl_str} ({s.get('trades', 0)} trades, regime: {s.get('regime', 'unknown')})")
        await self._send("\n".join(lines))

    async def send_losing_streak_alert(self, symbol: str, count: int, lot_factor: float):
        sym_name = self._sym(symbol)
        lines = [
            "🔴 <b>แจ้งเตือนขาดทุนติดต่อกัน</b>",
            f"📉 {sym_name}: ขาดทุน <b>{count} ครั้งติด</b>",
            f"⚙️ ปรับลด lot เหลือ {lot_factor:.0%} อัตโนมัติ",
        ]
        await self._send("\n".join(lines))

    async def send_trade_close_with_analysis(self, symbol: str, close_price: float, lot: float, profit: float, analysis: dict):
        icon = "📈" if profit >= 0 else "📉"
        outcome = "กำไร" if profit >= 0 else "ขาดทุน"
        summary = analysis.get("summary_th", "")
        exit_map = {"stop_loss": "🛑 SL", "take_profit": "🎯 TP", "manual_close": "👤 Manual"}
        exit_label = exit_map.get(analysis.get("exit_reason", ""), "❓")
        lines = [
            f"🏁 <b>ปิดสถานะ {self._sym(symbol)}</b>",
            f"💰 ราคา: {close_price:.2f}  |  Lot: {lot}",
            f"{icon} {outcome}: <b>${abs(profit):.2f}</b>",
            f"📋 {exit_label} | {summary}",
        ]
        if analysis.get("entry_regime"):
            lines.append(f"📊 Regime: {analysis['entry_regime']} → {analysis.get('exit_regime', '?')}")
        await self._send("\n".join(lines))

    async def send_regime_change(self, symbol: str, old_regime: str, new_regime: str):
        sym_name = self._sym(symbol)
        regime_th = {"trending_high_vol": "เทรนด์+ผันผวนสูง 🔥", "trending_low_vol": "เทรนด์+ผันผวนต่ำ", "ranging": "ไซด์เวย์ ↔️", "normal": "ปกติ ⚖️"}
        lines = [
            "🔄 <b>Regime เปลี่ยน</b>",
            f"📊 {sym_name}: {regime_th.get(old_regime, old_regime)} → {regime_th.get(new_regime, new_regime)}",
        ]
        await self._send("\n".join(lines))
