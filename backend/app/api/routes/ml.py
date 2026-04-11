"""
ML Model API routes — training, prediction, and status (per-symbol).
"""

import asyncio
import io
import json
from datetime import datetime, timezone

import joblib
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.config import settings

router = APIRouter(prefix="/api/ml", tags=["ml"])

_collector = None
_db_session = None


async def _load_macro_from_db(db_session) -> "pd.DataFrame | None":
    """Load latest macro data from DB and return as wide DataFrame indexed by date."""
    try:
        import pandas as pd
        from app.db.models import MacroData
        from sqlalchemy import select

        result = await db_session.execute(select(MacroData).order_by(MacroData.date))
        rows = result.scalars().all()
        if not rows:
            return None

        records = [{"date": r.date, "series_id": r.series_id, "value": r.value} for r in rows]
        df = pd.DataFrame(records)
        # Pivot: rows=date, columns=series_id
        macro_wide = df.pivot_table(index="date", columns="series_id", values="value", aggfunc="last")
        macro_wide.index = pd.to_datetime(macro_wide.index)
        return macro_wide.reset_index().rename(columns={"index": "date"}).set_index("date")
    except Exception:
        return None


def set_ml_deps(collector, db_session):
    global _collector, _db_session
    _collector = collector
    _db_session = db_session


class TrainRequest(BaseModel):
    symbol: str = "GOLD"
    timeframe: str = "M15"
    from_date: str | None = None
    to_date: str | None = None
    forward_bars: int = Field(10, ge=1, le=50)
    tp_pips: float = Field(5.0, ge=0.1, le=5000.0)
    sl_pips: float = Field(5.0, ge=0.1, le=5000.0)
    test_size: float = Field(0.2, ge=0.05, le=0.5)
    use_walk_forward: bool = False


@router.post("/train")
async def train_model(req: TrainRequest):
    if _collector is None or _db_session is None:
        raise HTTPException(status_code=503, detail="ML dependencies not initialized")

    symbol = req.symbol
    model_name = f"lightgbm_{symbol.lower()}"
    model_path = f"models/{symbol.lower()}_signal.pkl"

    try:
        # Load data from DB
        df = await _collector.load_from_db(symbol, req.timeframe, req.from_date, req.to_date)
        if df.empty or len(df) < 500:
            return {"error": f"Insufficient data for {symbol}: {len(df) if not df.empty else 0} bars (need 500+). Collect data first."}

        # Load macro data from DB
        macro_df = await _load_macro_from_db(_db_session)

        from app.ml.trainer import ModelTrainer
        trainer = ModelTrainer()

        # Prepare dataset (with macro features if available)
        X, y = trainer.prepare_dataset(df, req.forward_bars, req.tp_pips, req.sl_pips, macro_df=macro_df)
        if len(X) < 200:
            return {"error": f"Insufficient labeled samples for {symbol}: {len(X)} (need 200+)"}

        # Train in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        if req.use_walk_forward:
            result = await loop.run_in_executor(None, trainer.train_walk_forward, X, y)
        else:
            result = await loop.run_in_executor(None, trainer.train, X, y, req.test_size)

        # Save model to file (local) and serialize to bytes (for DB)
        trainer.save_model(model_path)
        result.model_path = model_path

        # Serialize model to bytes for DB storage
        buf = io.BytesIO()
        joblib.dump({"model": trainer.model, "features": trainer.feature_columns}, buf)
        model_bytes = buf.getvalue()

        # Save to DB — deactivate old model for this symbol only
        try:
            from app.db.models import MLModelLog
            from sqlalchemy import update
            await _db_session.execute(
                update(MLModelLog)
                .where(MLModelLog.is_active == True, MLModelLog.model_name == model_name)
                .values(is_active=False)
            )

            split_idx = int(len(X) * (1 - req.test_size))
            log = MLModelLog(
                model_name=model_name,
                timeframe=req.timeframe,
                train_start=df.index[0].to_pydatetime(),
                train_end=df.index[split_idx].to_pydatetime(),
                test_start=df.index[split_idx].to_pydatetime(),
                test_end=df.index[-1].to_pydatetime(),
                metrics=json.dumps(result.report),
                feature_importance=json.dumps(result.feature_importance),
                model_path=model_path,
                model_binary=model_bytes,
                is_active=True,
            )
            _db_session.add(log)
            await _db_session.commit()
        except Exception as e:
            await _db_session.rollback()
            return {"warning": f"Model trained but DB log failed: {e}", **result.to_dict()}

        return {**result.to_dict(), "symbol": symbol}

    except Exception as e:
        from loguru import logger
        logger.error(f"Train model error [{symbol}]: {e}")
        return {"error": f"Training failed: {e}"}


@router.get("/status")
async def model_status(symbol: str = Query("GOLD")):
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Not initialized")

    from app.db.models import MLModelLog

    model_prefix = f"lightgbm_{symbol.lower()}"

    # Try symbol-specific model first
    result = await _db_session.execute(
        select(MLModelLog)
        .where(MLModelLog.is_active == True, MLModelLog.model_name.like(f"{model_prefix}%"))
        .limit(1)
    )
    log = result.scalar_one_or_none()

    # Fallback to any active model
    if not log:
        result = await _db_session.execute(
            select(MLModelLog).where(MLModelLog.is_active == True).limit(1)
        )
        log = result.scalar_one_or_none()

    if not log:
        return {"status": "no_model", "symbol": symbol, "message": f"No trained model found for {symbol}. Use POST /api/ml/train first."}

    return {
        "status": "ready",
        "symbol": symbol,
        "model_name": log.model_name,
        "timeframe": log.timeframe,
        "train_period": f"{log.train_start.isoformat()} to {log.train_end.isoformat()}",
        "test_period": f"{log.test_start.isoformat()} to {log.test_end.isoformat()}",
        "metrics": json.loads(log.metrics) if log.metrics else {},
        "feature_importance_top10": dict(list(json.loads(log.feature_importance).items())[:10]) if log.feature_importance else {},
        "model_path": log.model_path,
        "created_at": log.created_at.isoformat(),
    }


@router.post("/predict")
async def predict_now(symbol: str = Query("GOLD")):
    """Run ML prediction on current market data."""
    if _collector is None or _db_session is None:
        raise HTTPException(status_code=503, detail="Not initialized")

    model_prefix = f"lightgbm_{symbol.lower()}"

    # Try loading symbol-specific model from file first
    from pathlib import Path
    model_data = None
    symbol_path = f"models/{symbol.lower()}_signal.pkl"

    if Path(symbol_path).exists():
        model_data = joblib.load(symbol_path)
    elif Path(settings.ml_model_path).exists():
        model_data = joblib.load(settings.ml_model_path)
    else:
        # Load from DB
        from app.db.models import MLModelLog
        result = await _db_session.execute(
            select(MLModelLog).where(
                MLModelLog.is_active == True,
                MLModelLog.model_binary.isnot(None),
                MLModelLog.model_name.like(f"{model_prefix}%"),
            ).limit(1)
        )
        log = result.scalar_one_or_none()
        # Fallback to any active model
        if not log:
            result = await _db_session.execute(
                select(MLModelLog).where(
                    MLModelLog.is_active == True,
                    MLModelLog.model_binary.isnot(None),
                ).limit(1)
            )
            log = result.scalar_one_or_none()
        if log and log.model_binary:
            buf = io.BytesIO(log.model_binary)
            model_data = joblib.load(buf)

    if model_data is None:
        return {"error": f"No trained model found for {symbol}. Train one first."}

    from app.ml.predictor import MLPredictor
    predictor = MLPredictor.__new__(MLPredictor)
    predictor.model = model_data["model"]
    predictor.feature_columns = model_data.get("features", [])

    # Get recent OHLCV from DB — use symbol's ML timeframe, not global default
    from app.config import SYMBOL_PROFILES
    predict_tf = SYMBOL_PROFILES.get(symbol, {}).get("ml_timeframe", settings.timeframe)
    df = await _collector.load_from_db(symbol, predict_tf)
    if df.empty or len(df) < 200:
        return {"error": f"Insufficient market data for {symbol} ({predict_tf}). Collected {len(df) if not df.empty else 0} bars, need 200+."}

    # Use last 300 bars for feature computation
    df_recent = df.tail(300)
    signal, confidence = predictor.predict(df_recent)

    signal_label = {1: "BUY", -1: "SELL", 0: "HOLD"}[signal]
    return {
        "signal": signal_label,
        "signal_value": signal,
        "confidence": round(confidence, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": predict_tf,
    }


@router.get("/drift")
async def get_drift_report(symbol: str = Query("GOLD")):
    """Get feature and prediction drift report for the active model."""
    if _db_session is None:
        raise HTTPException(status_code=503, detail="ML dependencies not initialized")

    from app.db.models import MLModelLog, MLPredictionLog
    from app.ml.drift import check_drift

    # Get active model stats
    result = await _db_session.execute(
        select(MLModelLog)
        .where(MLModelLog.is_active == True, MLModelLog.model_name.like(f"lightgbm_{symbol.lower()}%"))
        .limit(1)
    )
    model_log = result.scalar_one_or_none()
    if not model_log or not model_log.metrics:
        return {"error": "No active model found"}

    metrics = json.loads(model_log.metrics)
    training_stats = metrics.get("feature_stats")
    training_label_dist = metrics.get("label_distribution")

    # Get recent predictions
    pred_result = await _db_session.execute(
        select(MLPredictionLog)
        .where(MLPredictionLog.symbol == symbol)
        .order_by(desc(MLPredictionLog.created_at))
        .limit(200)
    )
    predictions = pred_result.scalars().all()
    recent_signals = [p.predicted_signal for p in predictions]

    report = check_drift(
        training_stats=training_stats,
        training_label_dist=training_label_dist,
        recent_predictions=recent_signals if recent_signals else None,
    )
    return report.to_dict()


@router.get("/calibration")
async def get_calibration(symbol: str = Query("GOLD")):
    """Get confidence calibration — predicted vs actual win rate per bucket."""
    if _db_session is None:
        raise HTTPException(status_code=503, detail="ML dependencies not initialized")

    from app.db.models import MLPredictionLog

    result = await _db_session.execute(
        select(MLPredictionLog)
        .where(
            MLPredictionLog.symbol == symbol,
            MLPredictionLog.was_correct.isnot(None),
        )
        .order_by(desc(MLPredictionLog.created_at))
        .limit(1000)
    )
    predictions = result.scalars().all()

    if len(predictions) < 20:
        return {"error": f"Insufficient data ({len(predictions)} predictions, need 20+)"}

    # Bucket by confidence
    buckets = {}
    for p in predictions:
        bucket = int(p.confidence * 10) * 10  # 50, 60, 70, 80, 90
        bucket = max(50, min(90, bucket))
        key = f"{bucket}-{bucket + 10}%"
        if key not in buckets:
            buckets[key] = {"correct": 0, "total": 0, "predicted_confidence": bucket / 100 + 0.05}
        buckets[key]["total"] += 1
        if p.was_correct:
            buckets[key]["correct"] += 1

    calibration = {}
    for key, data in sorted(buckets.items()):
        actual_wr = data["correct"] / data["total"] if data["total"] > 0 else 0
        calibration[key] = {
            "predicted_confidence": round(data["predicted_confidence"], 2),
            "actual_win_rate": round(actual_wr, 4),
            "count": data["total"],
            "well_calibrated": abs(data["predicted_confidence"] - actual_wr) < 0.10,
        }

    return {"calibration": calibration, "total_predictions": len(predictions)}
