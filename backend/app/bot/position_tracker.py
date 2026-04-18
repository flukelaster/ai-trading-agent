"""
Position Tracker — Manages position tracking, synchronization, and reconciliation.

Responsibilities:
- Track open positions (known tickets)
- Sync positions from MT5 or paper mode
- Handle closed trades
- Reconcile orphans and phantoms
- Recover pending trades from Redis fallback
"""

import json
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.constants import PAPER_TICKET_START
from app.db.models import BotEvent, BotEventType, Trade
from app.mt5.connector import MT5BridgeConnector


def _naive_utc() -> datetime:
    """Return current UTC time without timezone info (for DB columns without tz)."""
    return datetime.utcnow()


class PositionTracker:
    """Tracks and synchronizes trading positions."""

    def __init__(
        self,
        executor,
        db_session: AsyncSession,
        redis_client,
        connector: MT5BridgeConnector,
        symbol: str,
        paper_trade: bool = False,
        notifier=None,
    ):
        self.executor = executor
        self.db = db_session
        self.redis = redis_client
        self.connector = connector
        self.symbol = symbol
        self.paper_trade = paper_trade
        self.notifier = notifier

        # Position tracking state
        self._known_tickets: set[int] = set()
        self._paper_positions: list[dict] = []
        self._paper_ticket_counter = PAPER_TICKET_START
        self._paper_balance = 100000.0  # PAPER_INITIAL_BALANCE

    async def seed_known_tickets(self):
        """Seed known tickets from current MT5 positions on startup."""
        try:
            positions = await self.executor.get_open_positions(self.symbol)
            self._known_tickets = {p["ticket"] for p in positions}
            if self._known_tickets:
                logger.info(f"Tracking {len(self._known_tickets)} existing positions")
        except Exception as e:
            logger.warning(f"Could not seed known tickets: {e}")

    async def sync_positions(self) -> list[dict]:
        """
        Sync open positions and update closed trades.
        Returns list of current positions.
        """
        if self.paper_trade:
            positions = await self._sync_paper_positions()
        else:
            positions = await self.executor.get_open_positions(self.symbol)

        current_tickets = {p["ticket"] for p in positions}

        # Safety: if fetch returned empty but we have known positions, skip sync
        if not positions and len(self._known_tickets) > 0 and not self.paper_trade:
            logger.warning(f"Position fetch returned empty but {len(self._known_tickets)} known — skipping sync")
            return []

        # Always track ALL open positions (including manually opened ones)
        self._known_tickets = self._known_tickets | current_tickets

        # Detect closed positions
        closed = self._known_tickets - current_tickets
        if closed and not self.paper_trade:
            await self._handle_closed_trades(closed)
        elif closed:
            for ticket in closed:
                logger.info(f"Paper position closed: ticket={ticket}")

        self._known_tickets = current_tickets
        return positions

    async def _handle_closed_trades(self, closed_tickets: set[int]):
        """Fetch close details from MT5 history and update DB."""
        history_result = await self.connector.get_history(days=1)
        history_deals = history_result.get("data", []) if history_result.get("success") else []
        history_map = {d["ticket"]: d for d in history_deals}

        for ticket in closed_tickets:
            deal = history_map.get(ticket)

            close_price = deal["price"] if deal else 0
            profit = deal["profit"] if deal else 0
            close_time = (
                datetime.fromisoformat(deal["time"]).replace(tzinfo=None)
                if deal and deal.get("time")
                else _naive_utc()
            )

            profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
            logger.info(f"Position closed: ticket={ticket} price={close_price} profit={profit_str}")

            # Update trade in DB
            from sqlalchemy import select
            stmt = select(Trade).where(Trade.ticket == ticket)
            try:
                await self.db.rollback()
            except Exception:
                pass
            result = await self.db.execute(stmt)
            trade = result.scalar_one_or_none()
            if trade:
                trade.close_price = close_price
                trade.close_time = close_time
                trade.profit = profit
                # Post-trade analysis
                from app.bot.engine import BotEngine
                analysis = BotEngine._build_post_trade_analysis(trade, deal, None)
                trade.post_trade_analysis = analysis
                await self.db.commit()

            # Log event
            await self._log_event(
                BotEventType.TRADE_CLOSED,
                f"#{ticket} closed @ {close_price} — {profit_str}",
            )

            # Push to frontend
            await self._push_event("bot_event", {
                "type": "trade_closed",
                "ticket": ticket,
                "close_price": close_price,
                "profit": profit,
            })

            # Telegram notification
            if self.notifier:
                if trade and trade.post_trade_analysis:
                    await self._notify(self.notifier.send_trade_close_with_analysis(
                        self.symbol, close_price, deal.get("lot", 0) if deal else 0,
                        profit, trade.post_trade_analysis,
                    ))
                else:
                    await self._notify(self.notifier.send_trade_alert(
                        "CLOSE", self.symbol, close_price, 0, 0,
                        deal.get("lot", 0) if deal else 0,
                        extra=profit_str,
                    ))

            # ML prediction feedback
            await self._update_prediction_feedback(profit)

    async def _sync_paper_positions(self) -> list[dict]:
        """Update paper positions with current prices, close if SL/TP hit."""
        from app.mt5.market_data import MarketDataService

        market_data = MarketDataService(self.connector)
        tick = await market_data.get_current_tick(self.symbol)
        if not tick:
            return self._paper_positions

        still_open = []
        for pos in self._paper_positions:
            price = tick["bid"] if pos["type"] == "BUY" else tick["ask"]
            pos["current_price"] = price

            # Calculate profit
            contract_size = 100  # TODO: get from symbol profile
            if pos["type"] == "BUY":
                pos["profit"] = round((price - pos["open_price"]) * pos["lot"] * contract_size, 2)
            else:
                pos["profit"] = round((pos["open_price"] - price) * pos["lot"] * contract_size, 2)

            # Check SL/TP hit
            hit = False
            if pos["type"] == "BUY":
                if pos["sl"] > 0 and price <= pos["sl"]:
                    hit = True
                elif pos["tp"] > 0 and price >= pos["tp"]:
                    hit = True
            else:
                if pos["sl"] > 0 and price >= pos["sl"]:
                    hit = True
                elif pos["tp"] > 0 and price <= pos["tp"]:
                    hit = True

            if hit:
                self._paper_balance += pos["profit"]
                logger.info(f"PAPER position {pos['ticket']} closed: profit={pos['profit']}")
                await self._push_event("bot_event", {"type": "trade_closed", "ticket": pos["ticket"]})
                if self.notifier:
                    await self._notify(self.notifier.send_trade_alert(
                        "CLOSE [PAPER]", self.symbol, price, 0, 0, pos["lot"],
                    ))
            else:
                still_open.append(pos)

        self._paper_positions = still_open
        return still_open

    async def reconcile_positions(self):
        """Compare DB open trades with MT5 positions to detect orphans and phantoms."""
        if self.paper_trade:
            return

        try:
            # 1. Get current MT5 positions
            positions = await self.executor.get_open_positions(self.symbol)
            mt5_tickets = {p["ticket"] for p in positions}

            # 2. Get DB trades that should be open (no close_time)
            stmt = select(Trade).where(Trade.symbol == self.symbol, Trade.close_time.is_(None))
            result = await self.db.execute(stmt)
            db_trades = result.scalars().all()
            db_tickets = {t.ticket for t in db_trades}

            # 3. Orphan detection: in MT5 but not in DB → auto-adopt
            orphans = mt5_tickets - db_tickets
            if orphans:
                await self._adopt_orphan_positions(orphans, positions, db_tickets)

            # 4. Phantom detection: in DB but not in MT5
            phantoms = db_tickets - mt5_tickets
            if phantoms:
                await self._reconcile_phantom_positions(phantoms, db_trades)

        except Exception as e:
            logger.error(f"Position reconciliation error [{self.symbol}]: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def _adopt_orphan_positions(self, orphans: set[int], positions: list[dict], db_tickets: set[int]):
        """Auto-adopt orphan positions found in MT5 but not in DB."""
        pos_map = {p["ticket"]: p for p in positions}
        adopted = []

        for ticket in orphans:
            p = pos_map.get(ticket)
            if not p:
                continue
            try:
                open_time = (
                    datetime.fromisoformat(p["open_time"]).replace(tzinfo=None)
                    if isinstance(p.get("open_time"), str)
                    else _naive_utc()
                )
                trade = Trade(
                    ticket=ticket,
                    symbol=self.symbol,
                    type=p.get("type", "BUY"),
                    lot=p.get("lot", 0.01),
                    open_price=p.get("open_price", 0),
                    sl=p.get("sl", 0),
                    tp=p.get("tp", 0),
                    open_time=open_time,
                    strategy_name=p.get("comment", "adopted_from_mt5") or "adopted_from_mt5",
                )
                self.db.add(trade)
                await self.db.commit()
                adopted.append(ticket)
                logger.info(f"Auto-adopted orphan [{self.symbol}]: ticket={ticket}")
            except Exception as e:
                logger.warning(f"Failed to adopt orphan {ticket}: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass

        if adopted:
            tickets_str = ", ".join(str(t) for t in sorted(adopted))
            await self._log_event(
                BotEventType.ERROR,
                f"Auto-adopted orphaned positions: {tickets_str}",
            )
            if self.notifier:
                await self._notify(self.notifier._send(
                    f"🔄 <b>Auto-adopted positions</b> [{self.symbol}]\n"
                    f"Tickets: {tickets_str}\n"
                    f"สร้าง record ใน DB ให้อัตโนมัติแล้ว"
                ))

    async def _reconcile_phantom_positions(self, phantoms: set[int], db_trades: list[Trade]):
        """Reconcile phantom records found in DB but not in MT5."""
        logger.warning(f"Phantom records [{self.symbol}]: {phantoms} (in DB, not in MT5)")

        # Try to find close details from MT5 history
        history_result = await self.connector.get_history(days=7)
        history_deals = history_result.get("data", []) if history_result.get("success") else []
        history_map = {d["ticket"]: d for d in history_deals}

        for trade in db_trades:
            if trade.ticket not in phantoms:
                continue
            deal = history_map.get(trade.ticket)
            if deal:
                trade.close_price = deal["price"]
                trade.close_time = (
                    datetime.fromisoformat(deal["time"]).replace(tzinfo=None)
                    if deal.get("time")
                    else _naive_utc()
                )
                trade.profit = deal.get("profit", 0)
                logger.info(f"Reconciled phantom #{trade.ticket}: closed @ {trade.close_price}, profit={trade.profit}")
            else:
                trade.close_time = _naive_utc()
                trade.profit = 0
                logger.warning(f"Reconciled phantom #{trade.ticket}: not found in 7-day history, marked closed")

        await self.db.commit()
        await self._log_event(
            BotEventType.ERROR,
            f"Phantom records reconciled: {phantoms}",
        )

    async def recover_pending_trades(self):
        """Recover trades that failed DB save and were stored in Redis fallback."""
        key = f"pending_trades:{self.symbol}"
        try:
            pending = await self.redis.lrange(key, 0, -1)
            if not pending:
                return

            logger.info(f"Recovering {len(pending)} pending trades [{self.symbol}]")
            for raw in pending:
                try:
                    data = json.loads(raw)
                    trade = Trade(
                        ticket=data["ticket"],
                        symbol=data["symbol"],
                        type=data["type"],
                        lot=data["lot"],
                        open_price=data["open_price"],
                        expected_price=data.get("expected_price"),
                        sl=data.get("sl"),
                        tp=data.get("tp"),
                        open_time=(
                            datetime.fromisoformat(data["open_time"])
                            if data.get("open_time")
                            else _naive_utc()
                        ),
                        strategy_name=data.get("strategy_name"),
                    )
                    self.db.add(trade)
                    await self.db.commit()
                    await self.redis.lrem(key, 1, raw)
                    logger.info(f"Recovered pending trade: ticket={data['ticket']}")
                except Exception as e:
                    logger.warning(f"Failed to recover pending trade: {e}")
                    try:
                        await self.db.rollback()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Pending trades recovery error [{self.symbol}]: {e}")

    def get_known_tickets(self) -> set[int]:
        """Return currently tracked tickets."""
        return self._known_tickets.copy()

    # Helper methods (delegated from BotEngine)

    async def _log_event(self, event_type: BotEventType, message: str):
        try:
            event = BotEvent(event_type=event_type, message=message)
            self.db.add(event)
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def _push_event(self, channel: str, data: dict):
        try:
            import redis.asyncio as redis
            await self.redis.publish(channel, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to push event: {e}")

    async def _notify(self, coro):
        """Fire-and-forget notification."""
        if not self.notifier:
            return
        try:
            await coro
        except Exception as e:
            logger.error(f"Notification failed: {e}")

    async def _update_prediction_feedback(self, profit: float) -> None:
        """Find matching MLPredictionLog and set was_correct + actual_outcome."""
        try:
            from app.db.models import MLPredictionLog
            from app.constants import PREDICTION_FEEDBACK_HOURS
            from sqlalchemy import and_
            from datetime import timedelta

            cutoff = _naive_utc() - timedelta(hours=PREDICTION_FEEDBACK_HOURS)
            stmt = (
                select(MLPredictionLog)
                .where(and_(
                    MLPredictionLog.symbol == self.symbol,
                    MLPredictionLog.was_correct.is_(None),
                    MLPredictionLog.created_at >= cutoff,
                ))
                .order_by(MLPredictionLog.created_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            pred = result.scalar_one_or_none()
            if pred:
                actual = 1 if profit > 0 else -1
                pred.actual_outcome = actual
                pred.was_correct = (pred.predicted_signal == actual) or (
                    pred.predicted_signal == 0 and abs(profit) < 1
                )
                await self.db.commit()
                logger.info(f"ML feedback [{self.symbol}]: prediction={pred.predicted_signal}, outcome={actual}, correct={pred.was_correct}")
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.warning(f"ML feedback update failed: {e}")

    # Paper trading state accessors

    @property
    def paper_balance(self) -> float:
        return self._paper_balance

    @property
    def paper_positions(self) -> list[dict]:
        return self._paper_positions.copy()

    def increment_paper_ticket(self) -> int:
        """Increment and return new paper ticket number."""
        self._paper_ticket_counter += 1
        return self._paper_ticket_counter

    def add_paper_position(self, position: dict):
        """Add a new paper position."""
        self._paper_positions.append(position)

    def update_paper_balance(self, amount: float):
        """Update paper balance by amount (can be negative for losses)."""
        self._paper_balance += amount
