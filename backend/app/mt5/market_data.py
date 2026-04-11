"""
Market Data Service — fetches tick and OHLCV data via MT5 Bridge.
Includes stale data detection and OHLCV gap validation.
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable

import pandas as pd
from loguru import logger

from app.mt5.connector import MT5BridgeConnector

# Max tick age before considered stale (seconds)
MAX_TICK_AGE_SECONDS = 30


class MarketDataService:
    def __init__(self, connector: MT5BridgeConnector):
        self.connector = connector
        self._avg_spread: dict[str, float] = {}  # symbol → rolling avg spread

    async def get_current_tick(self, symbol: str, validate: bool = True) -> dict | None:
        result = await self.connector.get_tick(symbol)
        if not result.get("success"):
            logger.warning(f"Failed to get tick for {symbol}: {result.get('error')}")
            return None

        tick = result["data"]

        if validate:
            # Check tick age
            tick_time_str = tick.get("time")
            if tick_time_str:
                try:
                    tick_time = datetime.fromisoformat(tick_time_str.replace("Z", "+00:00"))
                    if tick_time.tzinfo is None:
                        tick_time = tick_time.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - tick_time).total_seconds()
                    if age > MAX_TICK_AGE_SECONDS:
                        logger.warning(f"Stale tick for {symbol}: {age:.0f}s old (max {MAX_TICK_AGE_SECONDS}s)")
                        return None
                except (ValueError, TypeError):
                    pass  # Can't validate time, proceed anyway

            # Check abnormal spread (> 3x rolling average)
            spread = tick.get("spread", 0)
            avg = self._avg_spread.get(symbol)
            if avg and avg > 0 and spread > avg * 3:
                logger.warning(f"Abnormal spread {symbol}: {spread:.2f} vs avg {avg:.2f}")
                return None

            # Update rolling average spread
            if spread > 0:
                if symbol in self._avg_spread:
                    self._avg_spread[symbol] = self._avg_spread[symbol] * 0.95 + spread * 0.05
                else:
                    self._avg_spread[symbol] = spread

        return tick

    async def get_ohlcv(self, symbol: str, timeframe: str = "M15", count: int = 100, validate: bool = True) -> pd.DataFrame:
        result = await self.connector.get_ohlcv(symbol, timeframe, count)
        if not result.get("success") or not result.get("data"):
            logger.warning(f"Failed to get OHLCV for {symbol}: {result.get('error')}")
            return pd.DataFrame()

        df = pd.DataFrame(result["data"])
        df = df.assign(time=pd.to_datetime(df["time"])).set_index("time")

        if validate and not df.empty:
            # Check for duplicate timestamps
            if df.index.duplicated().any():
                dup_count = df.index.duplicated().sum()
                logger.warning(f"Duplicate candles in {symbol} {timeframe}: {dup_count} removed")
                df = df[~df.index.duplicated(keep="last")]

            # Check for gaps (> 2x expected interval)
            if len(df) >= 2:
                intervals = df.index.to_series().diff().dropna()
                median_interval = intervals.median()
                if median_interval and median_interval.total_seconds() > 0:
                    gaps = intervals[intervals > median_interval * 2.5]
                    if len(gaps) > 0:
                        logger.debug(f"OHLCV gaps in {symbol} {timeframe}: {len(gaps)} gaps detected (may be market close)")

            # Check for zero-volume bars (possible bad data)
            if "tick_volume" in df.columns:
                zero_vol = (df["tick_volume"] == 0).sum()
                if zero_vol > len(df) * 0.1:
                    logger.warning(f"High zero-volume bars in {symbol} {timeframe}: {zero_vol}/{len(df)}")

        return df

    async def get_ohlcv_range(self, symbol: str, timeframe: str, from_date: str, to_date: str) -> pd.DataFrame:
        """Fetch historical OHLCV data by date range from MT5 Bridge."""
        result = await self.connector.get_ohlcv_range(symbol, timeframe, from_date, to_date)
        if not result.get("success") or not result.get("data"):
            logger.warning(f"Failed to get historical OHLCV for {symbol}: {result.get('error')}")
            return pd.DataFrame()

        df = pd.DataFrame(result["data"])
        df = df.assign(time=pd.to_datetime(df["time"])).set_index("time")
        return df

    async def stream_ticks(self, symbol: str, callback: Callable, interval: float = 1.0):
        last_tick = None
        while True:
            tick = await self.get_current_tick(symbol, validate=True)
            if tick:
                # Skip duplicate ticks
                if last_tick and tick["bid"] == last_tick["bid"] and tick["ask"] == last_tick["ask"]:
                    await asyncio.sleep(interval)
                    continue
                await callback(tick)
                last_tick = tick
            await asyncio.sleep(interval)
