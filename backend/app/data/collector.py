"""
Historical Data Collector — fetches OHLCV from MT5 bridge and stores in DB.
"""

from datetime import datetime, timedelta

import pandas as pd
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OHLCVData
from app.db.session import async_session
from app.mt5.market_data import MarketDataService


class HistoricalDataCollector:
    def __init__(self, market_data: MarketDataService, db_session: AsyncSession):
        self.market_data = market_data
        # Retained for backward compatibility (load_from_db / status readers that
        # run inside a request-scoped session). Write paths open their own
        # session to avoid racing with the scheduler's long-lived shared session.
        self.db = db_session

    async def collect(self, symbol: str, timeframe: str, from_date: str, to_date: str) -> dict:
        """
        Fetch historical OHLCV from MT5 in 30-day chunks and upsert into DB.

        Uses a dedicated session per call so concurrent scheduler work on the
        shared bot session does not raise "concurrent operations are not
        permitted" from asyncpg.
        """
        dt_from = datetime.fromisoformat(from_date)
        dt_to = datetime.fromisoformat(to_date)
        total_bars = 0
        total_new = 0

        current = dt_from
        while current < dt_to:
            chunk_end = min(current + timedelta(days=30), dt_to)
            chunk_from = current.strftime("%Y-%m-%d")
            chunk_to = chunk_end.strftime("%Y-%m-%d")

            logger.info(f"Collecting {symbol} {timeframe} {chunk_from} -> {chunk_to}")
            df = await self.market_data.get_ohlcv_range(symbol, timeframe, chunk_from, chunk_to)

            if df.empty:
                logger.warning(f"No data for chunk {chunk_from} -> {chunk_to}")
                current = chunk_end
                continue

            # Each chunk commits in its own isolated session — partial progress
            # is durable if a later chunk fails.
            async with async_session() as session:
                new_bars = await self._upsert_bars(session, symbol, timeframe, df)
                await session.commit()
            total_bars += len(df)
            total_new += new_bars
            logger.info(f"Chunk {chunk_from}->{chunk_to}: {len(df)} bars, {new_bars} new")

            current = chunk_end

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "from_date": from_date,
            "to_date": to_date,
            "total_bars_fetched": total_bars,
            "new_bars_inserted": total_new,
        }

    async def _upsert_bars(self, session: AsyncSession, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        """Insert bars, skip duplicates via ON CONFLICT DO NOTHING."""
        rows = []
        for time_idx, row in df.iterrows():
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "time": time_idx.to_pydatetime(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("tick_volume", row.get("volume", 0))),
                }
            )

        if not rows:
            return 0

        stmt = text("""
            INSERT INTO ohlcv_data (symbol, timeframe, time, open, high, low, close, volume)
            VALUES (:symbol, :timeframe, :time, :open, :high, :low, :close, :volume)
            ON CONFLICT (symbol, timeframe, time) DO NOTHING
        """)
        result = await session.execute(stmt, rows)
        return result.rowcount

    async def load_from_db(
        self, symbol: str, timeframe: str, from_date: str | None = None, to_date: str | None = None
    ) -> pd.DataFrame:
        """Load historical OHLCV from DB as a DataFrame matching MarketDataService format.

        Uses an isolated session so a poisoned `self.db` transaction from a
        concurrent caller cannot leak into this read.
        """
        query = select(OHLCVData).where(
            OHLCVData.symbol == symbol,
            OHLCVData.timeframe == timeframe,
        )
        if from_date:
            query = query.where(OHLCVData.time >= datetime.fromisoformat(from_date))
        if to_date:
            query = query.where(OHLCVData.time <= datetime.fromisoformat(to_date))
        query = query.order_by(OHLCVData.time)

        async with async_session() as session:
            result = await session.execute(query)
            rows = result.scalars().all()

        if not rows:
            return pd.DataFrame()

        data = [
            {
                "time": r.time,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "tick_volume": r.volume,
            }
            for r in rows
        ]

        df = pd.DataFrame(data)
        df = df.assign(time=pd.to_datetime(df["time"])).set_index("time")
        return df

    async def get_data_status(self, symbol: str | None = None) -> list[dict]:
        """Return data coverage info per symbol/timeframe.

        Isolated session avoids `InterfaceError: cannot use
        Connection.transaction() in a manually started transaction` when a
        concurrent caller leaves `self.db` mid-transaction.
        """
        if symbol:
            query = text("""
                SELECT symbol, timeframe,
                       MIN(time) as first_bar,
                       MAX(time) as last_bar,
                       COUNT(*) as bar_count
                FROM ohlcv_data
                WHERE symbol = :symbol
                GROUP BY symbol, timeframe
                ORDER BY symbol, timeframe
            """)
            params = {"symbol": symbol}
        else:
            query = text("""
                SELECT symbol, timeframe,
                       MIN(time) as first_bar,
                       MAX(time) as last_bar,
                       COUNT(*) as bar_count
                FROM ohlcv_data
                GROUP BY symbol, timeframe
                ORDER BY symbol, timeframe
            """)
            params = {}

        async with async_session() as session:
            result = await session.execute(query, params)
            rows = result.fetchall()
        return [
            {
                "symbol": r[0],
                "timeframe": r[1],
                "first_bar": r[2].isoformat() if r[2] else None,
                "last_bar": r[3].isoformat() if r[3] else None,
                "bar_count": r[4],
            }
            for r in rows
        ]
