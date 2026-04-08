from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # MT5 Bridge
    mt5_bridge_url: str = "http://localhost:8001"
    mt5_bridge_api_key: str = "changeme"

    # Database
    database_url: str = "postgresql+asyncpg://goldbot:goldbot_dev@localhost:5432/goldbot"
    database_url_sync: str = "postgresql://goldbot:goldbot_dev@localhost:5432/goldbot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI
    anthropic_api_key: str = ""

    # Bot Config
    symbol: str = "GOLD"
    timeframe: str = "M15"
    max_risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_concurrent_trades: int = 3
    max_lot: float = 1.0
    use_ai_filter: bool = True
    ai_confidence_threshold: float = 0.7
    paper_trade: bool = False

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # FRED API (macro data)
    fred_api_key: str = ""

    # ML Model
    ml_model_path: str = "models/xauusd_signal.pkl"
    ml_confidence_threshold: float = 0.5

    # API
    secret_key: str = "changeme"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
