import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ─── Auth: Passkey (WebAuthn) ─────────────────────────────────────────────────

class Owner(Base):
    """Single-owner model — only 1 user ever exists."""
    __tablename__ = "owner"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(100))
    is_setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    device_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    jwt_jti: Mapped[str] = mapped_column(String(64), unique=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(50))
    actor: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BotEventType(str, enum.Enum):
    STARTED = "STARTED"
    STOPPED = "STOPPED"
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_CLOSED = "TRADE_CLOSED"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    TRADE_BLOCKED = "TRADE_BLOCKED"
    ORDER_FAILED = "ORDER_FAILED"
    ERROR = "ERROR"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    SENTIMENT_CHANGE = "SENTIMENT_CHANGE"
    OPTIMIZATION_RUN = "OPTIMIZATION_RUN"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    STRATEGY_CHANGED = "STRATEGY_CHANGED"


class OHLCVData(Base):
    __tablename__ = "ohlcv_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    time: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(10))  # BUY / SELL
    lot: Mapped[float] = mapped_column(Float)
    open_price: Mapped[float] = mapped_column(Float)
    expected_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # tick price before order, for slippage calc
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sl: Mapped[float] = mapped_column(Float)
    tp: Mapped[float] = mapped_column(Float)
    open_time: Mapped[datetime] = mapped_column(DateTime)
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(50))
    ai_sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_sentiment_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class NewsSentiment(Base):
    __tablename__ = "news_sentiments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sentiment_label: Mapped[str] = mapped_column(String(20))  # bullish/bearish/neutral
    sentiment_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class AIOptimizationLog(Base):
    __tablename__ = "ai_optimization_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    current_params: Mapped[str] = mapped_column(Text)  # JSON string
    suggested_params: Mapped[str] = mapped_column(Text)  # JSON string
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    backtest_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON backtest comparison
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class MacroData(Base):
    __tablename__ = "macro_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String(50), index=True)
    series_name: Mapped[str] = mapped_column(String(200))
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class MLModelLog(Base):
    __tablename__ = "ml_model_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(100))
    timeframe: Mapped[str] = mapped_column(String(10))
    train_start: Mapped[datetime] = mapped_column(DateTime)
    train_end: Mapped[datetime] = mapped_column(DateTime)
    test_start: Mapped[datetime] = mapped_column(DateTime)
    test_end: Mapped[datetime] = mapped_column(DateTime)
    metrics: Mapped[str] = mapped_column(Text)  # JSON
    feature_importance: Mapped[str] = mapped_column(Text)  # JSON
    model_path: Mapped[str] = mapped_column(String(255))
    model_binary: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class BotEvent(Base):
    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[BotEventType] = mapped_column(Enum(BotEventType))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class MLPredictionLog(Base):
    __tablename__ = "ml_prediction_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))
    predicted_signal: Mapped[int] = mapped_column(Integer)  # -1, 0, 1
    confidence: Mapped[float] = mapped_column(Float)
    actual_outcome: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # filled later
    was_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class OrderAudit(Base):
    __tablename__ = "order_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20))
    order_type: Mapped[str] = mapped_column(String(10))  # BUY / SELL
    requested_lot: Mapped[float] = mapped_column(Float)
    requested_sl: Mapped[float] = mapped_column(Float)
    requested_tp: Mapped[float] = mapped_column(Float)
    expected_price: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ticket: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # FILLED / REJECTED / TIMEOUT / ERROR
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_source: Mapped[str] = mapped_column(String(50))  # strategy name
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# ─── Secrets Vault ────────────────────────────────────────────────────────────

class Secret(Base):
    """Encrypted secrets store — managed via UI, injected into runners."""
    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)  # 12 bytes for AES-GCM
    category: Mapped[str] = mapped_column(String(50), default="general")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
