"""HMAC integrity helpers for ML model binaries.

Pickled model bytes go through ``joblib.load`` — equivalent to ``pickle.load``
which executes arbitrary Python on deserialization. Any path that lets an
attacker write to the ``ml_model_logs.model_binary`` column (SQL injection,
compromised admin, malicious migration) becomes RCE.

We mitigate by signing the blob with HMAC-SHA256 at save time and rejecting
the load when the digest does not match a fresh recompute. The signing key is
the application ``SECRET_KEY``; rotating it invalidates all prior models, which
is the desired behavior because rotation is itself a security event.
"""

from __future__ import annotations

import hashlib
import hmac

from loguru import logger

from app.config import settings


def compute_model_digest(model_bytes: bytes) -> str:
    """Hex HMAC-SHA256 of ``model_bytes`` keyed by SECRET_KEY."""
    key = settings.secret_key.encode() if settings.secret_key else b""
    return hmac.new(key, model_bytes, hashlib.sha256).hexdigest()


def verify_model_digest(model_bytes: bytes, expected_digest: str | None, *, context: str) -> bool:
    """Return True iff the digest matches. Logs a warning on mismatch.

    Empty / missing ``expected_digest`` is treated as a verification failure
    — a legacy row written before this check existed must be re-trained
    rather than loaded blindly. Set the env var ``ML_DIGEST_REQUIRED=0`` to
    grant a one-time grace period during rollout (logs WARN but allows load).
    """
    import os

    if not expected_digest:
        if os.getenv("ML_DIGEST_REQUIRED", "1") == "0":
            logger.warning(f"ml_digest missing [{context}] — allowed by ML_DIGEST_REQUIRED=0 grace flag")
            return True
        logger.error(f"ml_digest missing [{context}] — refusing to load (set ML_DIGEST_REQUIRED=0 for grace period)")
        return False
    actual = compute_model_digest(model_bytes)
    if not hmac.compare_digest(actual, expected_digest):
        logger.error(f"ml_digest mismatch [{context}] — refusing to load (possible tampering)")
        return False
    return True
