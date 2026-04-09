"""
ML Model API routes — training, prediction, and status.
"""

import asyncio
import io
import json
from datetime import datetime, timezone

import joblib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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
    timeframe: str = "M15"
    from_date: str | None = None
    to_date: str | None = None
    forward_bars: int = 10
    tp_pips: float = 5.0
    sl_pips: float = 5.0
    test_size: float = 0.2
    use_walk_forward: bool = False


@router.post("/train")
async def train_model(req: TrainRequest):
    if _collector is None or _db_session is None:
        raise HTTPException(status_code=503, detail="ML dependencies not initialized")

    # Load data from DB
    df = await _collector.load_from_db(settings.symbol, req.timeframe, req.from_date, req.to_date)
    if df.empty or len(df) < 500:
        return {"error": f"Insufficient data: {len(df)} bars (need 500+)"}

    # Load macro data from DB
    macro_df = await _load_macro_from_db(_db_session)

    from app.ml.trainer import ModelTrainer
    trainer = ModelTrainer()

    # Prepare dataset (with macro features if available)
    X, y = trainer.prepare_dataset(df, req.forward_bars, req.tp_pips, req.sl_pips, macro_df=macro_df)
    if len(X) < 200:
        return {"error": f"Insufficient labeled samples: {len(X)} (need 200+)"}

    # Train in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    if req.use_walk_forward:
        result = await loop.run_in_executor(None, trainer.train_walk_forward, X, y)
    else:
        result = await loop.run_in_executor(None, trainer.train, X, y, req.test_size)

    # Save model to file (local) and serialize to bytes (for DB)
    model_path = settings.ml_model_path
    trainer.save_model(model_path)
    result.model_path = model_path

    # Serialize model to bytes for DB storage
    buf = io.BytesIO()
    joblib.dump({"model": trainer.model, "features": trainer.feature_columns}, buf)
    model_bytes = buf.getvalue()

    # Save to DB
    try:
        from app.db.models import MLModelLog
        from sqlalchemy import update
        await _db_session.execute(
            update(MLModelLog).where(MLModelLog.is_active == True).values(is_active=False)
        )

        split_idx = int(len(X) * (1 - req.test_size))
        log = MLModelLog(
            model_name="lightgbm_xauusd",
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

    return result.to_dict()


@router.get("/status")
async def model_status():
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Not initialized")

    from app.db.models import MLModelLog
    result = await _db_session.execute(
        select(MLModelLog).where(MLModelLog.is_active == True).limit(1)
    )
    log = result.scalar_one_or_none()

    if not log:
        return {"status": "no_model", "message": "No trained model found. Use POST /api/ml/train first."}

    return {
        "status": "ready",
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
async def predict_now():
    """Run ML prediction on current market data."""
    if _collector is None or _db_session is None:
        raise HTTPException(status_code=503, detail="Not initialized")

    # Try loading model from file first, then fall back to DB
    from pathlib import Path
    model_data = None

    if Path(settings.ml_model_path).exists():
        model_data = joblib.load(settings.ml_model_path)
    else:
        # Load from DB
        from app.db.models import MLModelLog
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
        return {"error": "No trained model found. Train one first."}

    from app.ml.predictor import MLPredictor
    predictor = MLPredictor.__new__(MLPredictor)
    predictor.model = model_data["model"]
    predictor.feature_columns = model_data.get("features", [])

    # Get recent OHLCV from DB
    df = await _collector.load_from_db(settings.symbol, settings.timeframe)
    if df.empty or len(df) < 200:
        return {"error": "Insufficient market data"}

    # Use last 300 bars for feature computation
    df_recent = df.tail(300)
    signal, confidence = predictor.predict(df_recent)

    signal_label = {1: "BUY", -1: "SELL", 0: "HOLD"}[signal]
    return {
        "signal": signal_label,
        "signal_value": signal,
        "confidence": round(confidence, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": settings.symbol,
        "timeframe": settings.timeframe,
    }
