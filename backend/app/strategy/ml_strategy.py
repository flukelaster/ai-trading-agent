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

from app.config import settings
from app.constants import (
    ADX_RANGING_THRESHOLD,
    ATR_PERCENTILE_LOW,
    HIGH_VOL_THRESHOLD,
    LOW_VOL_THRESHOLD,
    ML_HIGH_VOL_THRESHOLD_BOOST,
    ML_LOW_VOL_THRESHOLD_BOOST,
    RANGING_CONFIDENCE_FACTOR,
)
from app.ml.features import FEATURE_COLUMNS, build_features
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


class MLStrategy(BaseStrategy):
    # Throttle DB lookups when no model exists yet (e.g. fresh symbol pre-train).
    # We re-poll every N candles instead of every tick so a newly-trained model
    # gets picked up automatically without spamming the DB on each call.
    _MODEL_RECHECK_EVERY = 20

    def __init__(self, model_path: str | None = None, confidence_threshold: float = 0.5, symbol: str = "GOLD"):
        self._model_path = model_path or f"models/{symbol.lower()}_signal.pkl"
        self._confidence_threshold = confidence_threshold
        self._symbol = symbol
        self._model = None
        self._feature_columns = FEATURE_COLUMNS
        self._model_loaded = False
        self._missing_recheck_count = 0

        load_path = self._model_path
        if Path(load_path).exists():
            try:
                data = joblib.load(load_path)
                self._model = data["model"]
                self._feature_columns = data.get("features", FEATURE_COLUMNS)
                self._model_loaded = True
                logger.info(f"ML model loaded from file: {load_path} (symbol={symbol})")
            except Exception as e:
                logger.warning(f"Failed to load model from file: {e}")

    async def _ensure_model(self):
        """Load model from DB if not already loaded. Filters by symbol.

        When no model has been trained yet, this method previously set
        ``_model_loaded=True`` and never re-checked, so a model trained later
        (manual /retrain or weekly job) was ignored until the engine restarted.
        We now keep ``_model_loaded=False`` and only re-check the DB every
        ``_MODEL_RECHECK_EVERY`` candles so the lookup cost is bounded but the
        strategy actually picks up newly-trained models in-flight.
        """
        if self._model is not None and self._model_loaded:
            return
        if not self._model_loaded and self._missing_recheck_count > 0:
            self._missing_recheck_count -= 1
            return

        try:
            from sqlalchemy import select

            from app.db.models import MLModelLog
            from app.db.session import async_session

            model_prefix = f"lightgbm_{self._symbol.lower()}"

            async with async_session() as session:
                # Try symbol-specific model first
                result = await session.execute(
                    select(MLModelLog)
                    .where(
                        MLModelLog.is_active,
                        MLModelLog.model_binary.isnot(None),
                        MLModelLog.model_name.like(f"{model_prefix}%"),
                    )
                    .limit(1)
                )
                log = result.scalar_one_or_none()

                # Fallback to any active model if no symbol-specific one
                if not log:
                    result = await session.execute(
                        select(MLModelLog)
                        .where(
                            MLModelLog.is_active,
                            MLModelLog.model_binary.isnot(None),
                        )
                        .limit(1)
                    )
                    log = result.scalar_one_or_none()

                if log and log.model_binary:
                    from app.ml.integrity import verify_model_digest

                    if not verify_model_digest(
                        log.model_binary, log.model_digest, context=f"ml_strategy[{self._symbol}]"
                    ):
                        logger.error(
                            f"ML model integrity check failed for {self._symbol} — leaving strategy without a model"
                        )
                        self._missing_recheck_count = self._MODEL_RECHECK_EVERY
                        return
                    buf = io.BytesIO(log.model_binary)
                    data = joblib.load(buf)
                    self._model = data["model"]
                    self._feature_columns = data.get("features", FEATURE_COLUMNS)
                    self._model_loaded = True
                    self._missing_recheck_count = 0
                    logger.info(f"ML model loaded from DB: {log.model_name} (symbol={self._symbol})")
                else:
                    logger.warning(
                        f"No trained ML model found for {self._symbol} — re-checking in "
                        f"{self._MODEL_RECHECK_EVERY} candles (train via /symbols/{{symbol}}/retrain)"
                    )
                    self._missing_recheck_count = self._MODEL_RECHECK_EVERY
        except Exception as e:
            logger.warning(f"Failed to load ML model from DB: {e} — will retry next candle")

    @property
    def name(self) -> str:
        return "ml_signal"

    @property
    def min_bars_required(self) -> int:
        return 200

    @property
    def worst_case(self) -> str:
        return "Model trained on past regime that no longer exists — overfitting to historical patterns, confident but wrong"

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
        for row_idx, prob in zip(X_valid.index, proba, strict=False):
            predicted_class = prob.argmax()
            confidence = float(prob[predicted_class])
            signal = signal_map[predicted_class]

            # Phase D: ADX regime gate — suppress signals in low-ADX sideways markets
            if settings.ml_adx_regime_filter and signal != 0:
                adx_val = features.loc[row_idx, "adx_14"] if "adx_14" in features.columns else None
                atr_pct_val = features.loc[row_idx, "atr_percentile"] if "atr_percentile" in features.columns else None
                if adx_val is not None and atr_pct_val is not None:
                    if adx_val < ADX_RANGING_THRESHOLD and atr_pct_val < ATR_PERCENTILE_LOW:
                        confidence *= RANGING_CONFIDENCE_FACTOR

            # Phase E: Dynamic confidence threshold based on ATR volatility
            effective_threshold = self._confidence_threshold
            if settings.ml_confidence_dynamic and "atr_pct" in features.columns:
                atr_pct = features.loc[row_idx, "atr_pct"]
                if atr_pct > HIGH_VOL_THRESHOLD:
                    effective_threshold = self._confidence_threshold + ML_HIGH_VOL_THRESHOLD_BOOST
                elif atr_pct < LOW_VOL_THRESHOLD:
                    effective_threshold = self._confidence_threshold + ML_LOW_VOL_THRESHOLD_BOOST

            if confidence >= effective_threshold and signal != 0:
                df.loc[row_idx, "signal"] = signal
            df.loc[row_idx, "ml_confidence"] = confidence

        return df

    def get_params(self) -> dict:
        return {
            "model_path": self._model_path,
            "confidence_threshold": self._confidence_threshold,
        }
