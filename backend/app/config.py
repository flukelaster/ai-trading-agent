from pydantic_settings import BaseSettings
from pydantic import Field


# Per-symbol trading profiles
SYMBOL_PROFILES: dict[str, dict] = {
    "GOLD": {
        "display_name": "Gold (XAUUSD)",
        "default_timeframe": "M15",
        "pip_value": 1.0,
        "default_lot": 0.1,
        "max_lot": 1.0,
        "price_decimals": 2,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100,  # profit = diff * lot * contract_size
    },
    "OILCash": {
        "display_name": "WTI Oil",
        "default_timeframe": "M15",
        "pip_value": 10.0,
        "default_lot": 0.1,
        "max_lot": 5.0,
        "price_decimals": 2,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100,
    },
    "BTCUSD": {
        "display_name": "Bitcoin",
        "default_timeframe": "M15",
        "pip_value": 1.0,
        "default_lot": 0.01,
        "max_lot": 0.5,
        "price_decimals": 2,
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "contract_size": 1,
    },
    "USDJPY": {
        "display_name": "USD/JPY",
        "default_timeframe": "M15",
        "pip_value": 100.0,
        "default_lot": 0.1,
        "max_lot": 5.0,
        "price_decimals": 3,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100000,
    },
}


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
    symbol: str = "GOLD"  # kept for backward compat
    symbols: str = "GOLD"  # comma-separated list, e.g. "GOLD,OILCash,BTCUSD,USDJPY"
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
    ml_confidence_dynamic: bool = True   # Phase E: ATR-based dynamic threshold
    ml_adx_regime_filter: bool = True    # Phase D: suppress trades in low-ADX market
    use_mtf_filter: bool = True          # Phase G: H1 trend confirmation

    # API
    secret_key: str = "changeme"
    cors_origins: str = "http://localhost:3000"

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
