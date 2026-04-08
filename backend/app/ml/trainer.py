"""
ML Model Trainer — trains LightGBM classifier on OHLCV features.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from app.ml.features import FEATURE_COLUMNS, build_features, build_labels


@dataclass
class TrainingResult:
    accuracy: float
    report: dict
    confusion: list
    feature_importance: dict
    train_size: int
    test_size: int
    class_distribution: dict
    model_path: str

    def to_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 4),
            "report": self.report,
            "confusion_matrix": self.confusion,
            "feature_importance_top15": dict(list(self.feature_importance.items())[:15]),
            "train_size": self.train_size,
            "test_size": self.test_size,
            "class_distribution": self.class_distribution,
            "model_path": self.model_path,
        }


class ModelTrainer:
    def __init__(self):
        self.model = None
        self.feature_columns = FEATURE_COLUMNS

    def prepare_dataset(
        self,
        df: pd.DataFrame,
        forward_bars: int = 10,
        tp_pips: float = 5.0,
        sl_pips: float = 5.0,
        macro_df: pd.DataFrame | None = None,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Build features and labels, drop NaN rows."""
        features = build_features(df, macro_df)
        labels = build_labels(df, forward_bars, tp_pips, sl_pips)

        # Select only known feature columns that exist
        available = [c for c in self.feature_columns if c in features.columns]
        X = features[available]
        y = labels

        # Align and drop NaN
        mask = X.notna().all(axis=1) & y.notna()
        X = X[mask]
        y = y[mask]

        # Remove rows with label 0 at the end (unlabeled tail)
        # but keep label 0 in the middle (genuine no-trade)
        last_valid = len(y) - forward_bars
        X = X.iloc[:last_valid]
        y = y.iloc[:last_valid]

        logger.info(f"Dataset: {len(X)} samples, features={len(available)}, "
                     f"label dist: {{1: {(y==1).sum()}, 0: {(y==0).sum()}, -1: {(y==-1).sum()}}}")
        return X, y

    def train(
        self, X: pd.DataFrame, y: pd.Series, test_size: float = 0.2
    ) -> TrainingResult:
        """Train LightGBM with chronological split."""
        import lightgbm as lgb

        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        # Map labels: -1 → 0, 0 → 1, 1 → 2 (LightGBM needs 0-indexed classes)
        label_map = {-1: 0, 0: 1, 1: 2}
        inv_map = {0: -1, 1: 0, 2: 1}
        y_train_mapped = y_train.map(label_map)
        y_test_mapped = y_test.map(label_map)

        # Handle class imbalance
        class_counts = y_train_mapped.value_counts()
        total = len(y_train_mapped)
        n_classes = 3
        class_weights = {c: total / (n_classes * count) for c, count in class_counts.items()}
        sample_weights = y_train_mapped.map(class_weights)

        params = {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "learning_rate": 0.1,
            "num_leaves": 15,
            "max_depth": 4,
            "min_child_samples": 50,
            "feature_fraction": 0.7,
            "bagging_fraction": 0.7,
            "bagging_freq": 5,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "verbose": -1,
            "num_threads": 1,
        }

        train_data = lgb.Dataset(X_train, label=y_train_mapped, weight=sample_weights)
        valid_data = lgb.Dataset(X_test, label=y_test_mapped, reference=train_data)

        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=100,
            valid_sets=[valid_data],
            callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)],
        )

        # Evaluate
        y_pred_proba = self.model.predict(X_test)
        y_pred_mapped = y_pred_proba.argmax(axis=1)
        y_pred = pd.Series(y_pred_mapped).map(inv_map).values
        y_test_orig = y_test.values

        accuracy = accuracy_score(y_test_orig, y_pred)
        report = classification_report(
            y_test_orig, y_pred,
            labels=[-1, 0, 1],
            target_names=["SELL", "HOLD", "BUY"],
            output_dict=True,
            zero_division=0,
        )
        conf = confusion_matrix(y_test_orig, y_pred, labels=[-1, 0, 1]).tolist()

        # Feature importance
        importance = self.model.feature_importance(importance_type="gain")
        feature_names = X_train.columns.tolist()
        fi = dict(sorted(
            zip(feature_names, importance.tolist()),
            key=lambda x: x[1], reverse=True,
        ))

        class_dist = {
            "SELL(-1)": int((y == -1).sum()),
            "HOLD(0)": int((y == 0).sum()),
            "BUY(1)": int((y == 1).sum()),
        }

        logger.info(f"Model trained: accuracy={accuracy:.4f}, "
                     f"train={len(X_train)}, test={len(X_test)}")

        return TrainingResult(
            accuracy=accuracy,
            report=report,
            confusion=conf,
            feature_importance=fi,
            train_size=len(X_train),
            test_size=len(X_test),
            class_distribution=class_dist,
            model_path="",  # Set by caller after save
        )

    def save_model(self, path: str):
        """Save model to disk."""
        if self.model is None:
            raise ValueError("No model to save")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "features": self.feature_columns}, path)
        logger.info(f"Model saved to {path}")

    def load_model(self, path: str):
        """Load model from disk."""
        data = joblib.load(path)
        self.model = data["model"]
        self.feature_columns = data.get("features", FEATURE_COLUMNS)
        logger.info(f"Model loaded from {path}")

    def get_feature_importance(self) -> dict:
        if self.model is None:
            return {}
        importance = self.model.feature_importance(importance_type="gain")
        feature_names = self.model.feature_name()
        return dict(sorted(
            zip(feature_names, importance.tolist()),
            key=lambda x: x[1], reverse=True,
        ))
