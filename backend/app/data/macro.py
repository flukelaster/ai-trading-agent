"""
Macro Data Service — fetches economic indicators from FRED API and stores in DB.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import MacroData

# Key FRED series for gold trading
FRED_SERIES = {
    "DTWEXBGS": "Trade Weighted USD Index (DXY proxy)",
    "DFEDTARU": "Fed Funds Upper Target Rate",
    "CPIAUCSL": "CPI All Urban Consumers",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "GOLDAMGBD228NLBM": "Gold Fixing Price London (AM)",
}

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class MacroDataService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.api_key = settings.fred_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def fetch_fred_series(
        self, series_id: str, from_date: str | None = None, to_date: str | None = None
    ) -> list[dict]:
        """Fetch observations from FRED API."""
        if not self.api_key:
            logger.warning("FRED API key not configured")
            return []

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        if from_date:
            params["observation_start"] = from_date
        if to_date:
            params["observation_end"] = to_date

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(FRED_BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

            observations = data.get("observations", [])
            result = []
            for obs in observations:
                if obs["value"] == ".":  # FRED uses "." for missing data
                    continue
                result.append({
                    "date": obs["date"],
                    "value": float(obs["value"]),
                })
            return result
        except Exception as e:
            logger.error(f"FRED fetch failed for {series_id}: {e}")
            return []

    async def collect_all(self, from_date: str | None = None, to_date: str | None = None) -> dict:
        """Fetch all tracked FRED series and store in DB."""
        if not from_date:
            from_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        if not to_date:
            to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        stats = {}
        for series_id, series_name in FRED_SERIES.items():
            observations = await self.fetch_fred_series(series_id, from_date, to_date)
            if not observations:
                stats[series_id] = 0
                continue

            # Upsert into DB
            rows = [{
                "series_id": series_id,
                "series_name": series_name,
                "date": datetime.fromisoformat(obs["date"]),
                "value": obs["value"],
            } for obs in observations]

            stmt = text("""
                INSERT INTO macro_data (series_id, series_name, date, value)
                VALUES (:series_id, :series_name, :date, :value)
                ON CONFLICT (series_id, date) DO UPDATE SET value = EXCLUDED.value
            """)
            await self.db.execute(stmt, rows)
            stats[series_id] = len(observations)
            logger.info(f"FRED {series_id}: {len(observations)} observations stored")

        await self.db.commit()
        return stats

    async def get_latest_snapshot(self) -> dict:
        """Get latest value for each tracked series."""
        snapshot = {}
        for series_id, series_name in FRED_SERIES.items():
            result = await self.db.execute(
                select(MacroData)
                .where(MacroData.series_id == series_id)
                .order_by(MacroData.date.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                snapshot[series_id] = {
                    "name": series_name,
                    "value": row.value,
                    "date": row.date.strftime("%Y-%m-%d"),
                }
        return snapshot

    async def compute_correlations(self, symbol: str, timeframe: str, days: int = 90) -> dict:
        """Compute rolling correlation between gold price and macro series."""
        from app.db.models import OHLCVData

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Get daily gold closes
        result = await self.db.execute(
            select(OHLCVData)
            .where(OHLCVData.symbol == symbol, OHLCVData.timeframe == timeframe, OHLCVData.time >= cutoff)
            .order_by(OHLCVData.time)
        )
        ohlcv_rows = result.scalars().all()
        if len(ohlcv_rows) < 20:
            return {"error": "Insufficient OHLCV data for correlation"}

        gold_df = pd.DataFrame([{"date": r.time.date(), "gold_close": r.close} for r in ohlcv_rows])
        gold_daily = gold_df.groupby("date").last().reset_index()
        gold_daily["date"] = pd.to_datetime(gold_daily["date"])

        correlations = {}
        for series_id in FRED_SERIES:
            result = await self.db.execute(
                select(MacroData)
                .where(MacroData.series_id == series_id, MacroData.date >= cutoff)
                .order_by(MacroData.date)
            )
            macro_rows = result.scalars().all()
            if len(macro_rows) < 5:
                continue

            macro_df = pd.DataFrame([{"date": pd.to_datetime(r.date), "value": r.value} for r in macro_rows])

            # Merge on date
            merged = pd.merge(gold_daily, macro_df, on="date", how="inner")
            if len(merged) >= 5:
                corr = merged["gold_close"].corr(merged["value"])
                correlations[series_id] = {
                    "name": FRED_SERIES[series_id],
                    "correlation": round(corr, 4) if pd.notna(corr) else None,
                    "data_points": len(merged),
                }

        return correlations

    async def get_macro_df_for_ml(self, from_date: str | None = None) -> pd.DataFrame:
        """Get macro data as a pivoted DataFrame for ML feature merging."""
        query = select(MacroData).order_by(MacroData.date)
        if from_date:
            query = query.where(MacroData.date >= datetime.fromisoformat(from_date))

        result = await self.db.execute(query)
        rows = result.scalars().all()

        if not rows:
            return pd.DataFrame()

        data = [{"date": r.date, "series_id": r.series_id, "value": r.value} for r in rows]
        df = pd.DataFrame(data)
        pivoted = df.pivot_table(index="date", columns="series_id", values="value")
        pivoted = pivoted.ffill()
        return pivoted
