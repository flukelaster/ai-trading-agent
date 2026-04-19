"""
Metrics API — exposes timing and counter data for observability.
"""

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.metrics import get_metrics

router = APIRouter(
    prefix="/api/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
async def get_metrics_summary():
    metrics = get_metrics()
    if not metrics:
        return {"error": "Metrics not initialized"}
    return await metrics.get_summary()
