"""
ML Predictor — loads a trained model and predicts signal + confidence from OHLCV.
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from app.ml.features import FEATURE_COLUMNS, build_features


class MLPredictor:
    def __init__(self, model_path: str):
        self.model = None
        self.feature_columns = FEATURE_COLUMNS
        self._load(model_path)

    def _load(self, path: str):
        if not Path(path).exists():
            logger.warning(f"ML model not found at {path}")
            return
        import joblib

        data = joblib.load(path)
        self.model = data["model"]
        self.feature_columns = data.get("features", FEATURE_COLUMNS)
        logger.info(f"ML model loaded from {path}")

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def predict(self, df: pd.DataFrame, macro_df: pd.DataFrame | None = None) -> tuple[int, float]:
        """
        Predict signal from latest OHLCV bar.
        Returns (signal, confidence) where signal is -1, 0, or 1.
        """
        if not self.is_ready:
            return 0, 0.0

        features = build_features(df, macro_df)
        available = [c for c in self.feature_columns if c in features.columns]

        # Use last row
        X = features[available].iloc[[-1]]

        if X.isna().any(axis=1).iloc[0]:
            logger.warning("ML prediction has NaN features, returning HOLD")
            return 0, 0.0

        proba = self.model.predict(X)[0]  # [P(SELL), P(HOLD), P(BUY)]

        # Map: index 0=-1(SELL), 1=0(HOLD), 2=1(BUY)
        signal_map = {0: -1, 1: 0, 2: 1}
        predicted_class = proba.argmax()
        confidence = float(proba[predicted_class])
        signal = signal_map[predicted_class]

        return signal, confidence
