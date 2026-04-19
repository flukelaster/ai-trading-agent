"""
Sentiment Features for ML — aggregates NewsSentiment data into ML-ready features.
"""

import pandas as pd
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NewsSentiment


async def get_sentiment_df_for_ml(session: AsyncSession, from_date: str | None = None) -> pd.DataFrame | None:
    """
    Query NewsSentiment table and aggregate per-day for ML feature engineering.

    Returns DataFrame with columns:
        - sent_score_mean: average sentiment score
        - sent_confidence_mean: average confidence
        - sent_bullish_ratio: fraction of bullish headlines
        - sent_bearish_ratio: fraction of bearish headlines
        - sent_count: total headlines per day
        - sent_momentum_3d: 3-day rolling change in sentiment score
    """
    try:
        query = select(NewsSentiment).order_by(NewsSentiment.created_at)
        if from_date:
            from datetime import datetime

            cutoff = datetime.strptime(from_date, "%Y-%m-%d")
            query = query.where(NewsSentiment.created_at >= cutoff)

        result = await session.execute(query)
        rows = result.scalars().all()

        if not rows or len(rows) < 5:
            return None

        records = []
        for r in rows:
            dt = r.created_at or r.published_at
            if not dt:
                continue
            records.append(
                {
                    "date": dt.date(),
                    "score": r.sentiment_score or 0.0,
                    "confidence": r.confidence or 0.0,
                    "label": r.sentiment_label or "neutral",
                }
            )

        if not records:
            return None

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])

        # Aggregate per day
        daily = (
            df.groupby("date")
            .agg(
                sent_score_mean=("score", "mean"),
                sent_confidence_mean=("confidence", "mean"),
                sent_count=("score", "count"),
                bullish_count=("label", lambda x: (x == "bullish").sum()),
                bearish_count=("label", lambda x: (x == "bearish").sum()),
            )
            .reset_index()
        )

        daily["sent_bullish_ratio"] = daily["bullish_count"] / daily["sent_count"]
        daily["sent_bearish_ratio"] = daily["bearish_count"] / daily["sent_count"]
        daily["sent_momentum_3d"] = daily["sent_score_mean"].rolling(3).mean().diff()

        # Clean up intermediate columns
        daily = daily.drop(columns=["bullish_count", "bearish_count"])
        daily = daily.set_index("date")

        logger.debug(f"Sentiment features: {len(daily)} days, {len(records)} total records")
        return daily

    except Exception as e:
        logger.warning(f"Sentiment feature extraction failed: {e}")
        return None
