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
    walk_forward_results: list | None = None

    def to_dict(self) -> dict:
        d = {
            "accuracy": round(self.accuracy, 4),
            "report": self.report,
            "confusion_matrix": self.confusion,
            "feature_importance_top15": dict(list(self.feature_importance.items())[:15]),
            "train_size": self.train_size,
            "test_size": self.test_size,
            "class_distribution": self.class_distribution,
            "model_path": self.model_path,
        }
        if self.walk_forward_results:
            d["walk_forward_results"] = self.walk_forward_results
            d["walk_forward_avg_accuracy"] = round(
                sum(f["accuracy"] for f in self.walk_forward_results) / len(self.walk_forward_results), 4
            )
        return d


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

        # Align and drop NaN rows (Triple Barrier leaves NaN at tail — drop them)
        mask = X.notna().all(axis=1) & y.notna()
        X = X[mask]
        y = y[mask].astype(int)

        logger.info(f"Dataset: {len(X)} samples, features={len(available)}, "
                     f"label dist: {{1: {(y==1).sum()}, 0: {(y==0).sum()}, -1: {(y==-1).sum()}}}")
        return X, y

    def train(
        self, X: pd.DataFrame, y: pd.Series, test_size: float = 0.2
    ) -> TrainingResult:
        """Train LightGBM with chronological split."""
        label_map = {-1: 0, 0: 1, 1: 2}
        inv_map = {0: -1, 1: 0, 2: 1}

        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        y_train_mapped = y_train.map(label_map)
        y_test_mapped = y_test.map(label_map)

        self.model = self._fit_lgb(X_train, y_train_mapped, X_test, y_test_mapped)

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

    def _get_params(self) -> dict:
        return {
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

    def _fit_lgb(self, X_train, y_train_mapped, X_val, y_val_mapped):
        """Train one LightGBM model and return it."""
        import lightgbm as lgb

        label_map = {-1: 0, 0: 1, 1: 2}
        class_counts = y_train_mapped.value_counts()
        total = len(y_train_mapped)
        class_weights = {c: total / (3 * count) for c, count in class_counts.items()}
        sample_weights = y_train_mapped.map(class_weights)

        train_data = lgb.Dataset(X_train, label=y_train_mapped, weight=sample_weights)
        valid_data = lgb.Dataset(X_val, label=y_val_mapped, reference=train_data)

        model = lgb.train(
            self._get_params(),
            train_data,
            num_boost_round=100,
            valid_sets=[valid_data],
            callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)],
        )
        return model

    def train_walk_forward(
        self, X: pd.DataFrame, y: pd.Series
    ) -> TrainingResult:
        """
        Walk-forward validation with 3 expanding folds:
          Fold 1: train 60%, test 20%
          Fold 2: train 70%, test 10%
          Fold 3: train 80%, test 20%
        Returns best-fold model + per-fold accuracy summary.
        """
        label_map = {-1: 0, 0: 1, 1: 2}
        inv_map = {0: -1, 1: 0, 2: 1}
        n = len(X)
        folds = [
            (int(n * 0.60), int(n * 0.80)),   # train 0-60%, test 60-80%
            (int(n * 0.70), int(n * 0.80)),   # train 0-70%, test 70-80%
            (int(n * 0.80), n),               # train 0-80%, test 80-100%
        ]

        fold_results = []
        best_accuracy = -1.0
        best_model = None

        for fold_idx, (train_end, test_end) in enumerate(folds):
            X_train = X.iloc[:train_end]
            X_test = X.iloc[train_end:test_end]
            y_train = y.iloc[:train_end]
            y_test = y.iloc[train_end:test_end]

            if len(X_test) < 50:
                continue

            y_train_mapped = y_train.map(label_map)
            y_test_mapped = y_test.map(label_map)

            model = self._fit_lgb(X_train, y_train_mapped, X_test, y_test_mapped)

            y_pred_mapped = model.predict(X_test).argmax(axis=1)
            y_pred = pd.Series(y_pred_mapped).map(inv_map).values
            acc = accuracy_score(y_test.values, y_pred)

            fold_results.append({
                "fold": fold_idx + 1,
                "train_size": len(X_train),
                "test_size": len(X_test),
                "accuracy": round(acc, 4),
            })
            logger.info(f"Walk-forward fold {fold_idx+1}: accuracy={acc:.4f}, train={len(X_train)}, test={len(X_test)}")

            if acc > best_accuracy:
                best_accuracy = acc
                best_model = model

        # Use best fold model as final model
        self.model = best_model

        # Final evaluation on last 20%
        split_idx = int(n * 0.8)
        X_test_final = X.iloc[split_idx:]
        y_test_final = y.iloc[split_idx:]
        y_pred_proba = self.model.predict(X_test_final)
        y_pred_mapped = y_pred_proba.argmax(axis=1)
        y_pred = pd.Series(y_pred_mapped).map(inv_map).values

        accuracy = accuracy_score(y_test_final.values, y_pred)
        report = classification_report(
            y_test_final.values, y_pred,
            labels=[-1, 0, 1], target_names=["SELL", "HOLD", "BUY"],
            output_dict=True, zero_division=0,
        )
        conf = confusion_matrix(y_test_final.values, y_pred, labels=[-1, 0, 1]).tolist()

        importance = self.model.feature_importance(importance_type="gain")
        feature_names = X.columns.tolist()
        fi = dict(sorted(zip(feature_names, importance.tolist()), key=lambda x: x[1], reverse=True))

        class_dist = {
            "SELL(-1)": int((y == -1).sum()),
            "HOLD(0)": int((y == 0).sum()),
            "BUY(1)": int((y == 1).sum()),
        }

        avg_acc = sum(f["accuracy"] for f in fold_results) / len(fold_results) if fold_results else accuracy
        logger.info(f"Walk-forward complete: avg_accuracy={avg_acc:.4f}, best_fold_accuracy={best_accuracy:.4f}")

        return TrainingResult(
            accuracy=accuracy,
            report=report,
            confusion=conf,
            feature_importance=fi,
            train_size=split_idx,
            test_size=len(X_test_final),
            class_distribution=class_dist,
            model_path="",
            walk_forward_results=fold_results,
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
