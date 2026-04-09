"""
ML Strategy — uses a trained LightGBM model for signal generation.
Loads model from DB (model_binary) so it persists across Railway deploys.
Uses lazy async loading: model is loaded on first calculate() call.
"""

import io
from pathlib import Path

import joblib
import pandas as pd
from loguru import logger

from app.ml.features import FEATURE_COLUMNS, build_features
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr
from app.config import settings


class MLStrategy(BaseStrategy):
    def __init__(self, model_path: str = "models/xauusd_signal.pkl", confidence_threshold: float = 0.5):
        self._model_path = model_path
        self._confidence_threshold = confidence_threshold
        self._model = None
        self._feature_columns = FEATURE_COLUMNS
        self._model_loaded = False

        # Try loading from file immediately (works locally)
        if Path(self._model_path).exists():
            try:
                data = joblib.load(self._model_path)
                self._model = data["model"]
                self._feature_columns = data.get("features", FEATURE_COLUMNS)
                self._model_loaded = True
                logger.info(f"ML model loaded from file: {self._model_path}")
            except Exception as e:
                logger.warning(f"Failed to load model from file: {e}")

    async def _ensure_model(self):
        """Load model from DB if not already loaded."""
        if self._model_loaded:
            return
        self._model_loaded = True  # prevent retry loops

        try:
            from app.db.session import async_session
            from app.db.models import MLModelLog
            from sqlalchemy import select

            async with async_session() as session:
                result = await session.execute(
                    select(MLModelLog).where(
                        MLModelLog.is_active == True,
                        MLModelLog.model_binary.isnot(None),
                    ).limit(1)
                )
                log = result.scalar_one_or_none()
                if log and log.model_binary:
                    buf = io.BytesIO(log.model_binary)
                    data = joblib.load(buf)
                    self._model = data["model"]
                    self._feature_columns = data.get("features", FEATURE_COLUMNS)
                    logger.info("ML model loaded from DB successfully")
                else:
                    logger.warning("No trained ML model found in DB — Train a model on the ML page first")
        except Exception as e:
            logger.warning(f"Failed to load ML model from DB: {e}")

    @property
    def name(self) -> str:
        return "ml_signal"

    @property
    def min_bars_required(self) -> int:
        return 200

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sync wrapper — actual work in _calculate_async called from engine."""
        df = df.copy()
        df["signal"] = 0
        df["ml_confidence"] = 0.0
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        if self._model is None:
            return df

        features = build_features(df)
        available = [c for c in self._feature_columns if c in features.columns]
        X = features[available]
        valid_mask = X.notna().all(axis=1)
        if valid_mask.sum() == 0:
            return df

        X_valid = X[valid_mask]
        proba = self._model.predict(X_valid)

        signal_map = {0: -1, 1: 0, 2: 1}
        for row_idx, prob in zip(X_valid.index, proba):
            predicted_class = prob.argmax()
            confidence = float(prob[predicted_class])
            signal = signal_map[predicted_class]

            # Phase D: ADX regime gate — suppress signals in low-ADX sideways markets
            if settings.ml_adx_regime_filter and signal != 0:
                adx_val = features.loc[row_idx, "adx_14"] if "adx_14" in features.columns else None
                atr_pct_val = features.loc[row_idx, "atr_percentile"] if "atr_percentile" in features.columns else None
                if adx_val is not None and atr_pct_val is not None:
                    if adx_val < 20 and atr_pct_val < 0.4:
                        confidence *= 0.7  # reduce confidence in ranging/low-vol markets

            # Phase E: Dynamic confidence threshold based on ATR volatility
            effective_threshold = self._confidence_threshold
            if settings.ml_confidence_dynamic and "atr_pct" in features.columns:
                atr_pct = features.loc[row_idx, "atr_pct"]
                if atr_pct > 0.5:    # high volatility (> 0.5% per bar)
                    effective_threshold = self._confidence_threshold + 0.10
                elif atr_pct < 0.2:  # low volatility / sideways
                    effective_threshold = self._confidence_threshold + 0.15

            if confidence >= effective_threshold and signal != 0:
                df.loc[row_idx, "signal"] = signal
            df.loc[row_idx, "ml_confidence"] = confidence

        return df

    def get_params(self) -> dict:
        return {
            "model_path": self._model_path,
            "confidence_threshold": self._confidence_threshold,
        }
