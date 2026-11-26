"""JSON-safe conversion for backtest results.

Backtest metrics are computed with numpy, so values like ``numpy.bool`` and
``numpy.float64`` leak into result dicts. FastAPI's encoder rejects
``numpy.bool`` (HTTP 500), so convert to plain Python before returning.
"""

import numpy as np


def to_native(obj):
    """Recursively convert numpy scalars/arrays to plain Python types."""
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj
