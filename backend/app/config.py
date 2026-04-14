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
        "contract_size": 100,
        "ml_tp_pips": 10.0,       # ~$10 move on XAUUSD ~$3,000
        "ml_sl_pips": 10.0,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
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
        "ml_tp_pips": 0.5,        # ~$0.50 move on WTI ~$70
        "ml_sl_pips": 0.5,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
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
        "ml_tp_pips": 500.0,      # ~$500 move on BTC ~$100,000
        "ml_sl_pips": 500.0,
        "ml_forward_bars": 5,     # BTC moves fast — shorter horizon
        "ml_timeframe": "H1",     # H1 better for BTC volatility
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
        "ml_tp_pips": 0.3,        # ~30 pips on USDJPY ~145
        "ml_sl_pips": 0.3,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
    },
}

# ─── Symbol Aliases (broker-specific names → canonical profile) ────────────
# XM micro accounts use suffixed symbol names (e.g., GOLDmicro, OILCashmicro)
SYMBOL_ALIASES: dict[str, str] = {
    "GOLDmicro": "GOLD",
    "OILCashmicro": "OILCash",
    "BTCUSDmicro": "BTCUSD",
    "USDJPYmicro": "USDJPY",
}


def get_symbol_profile(symbol: str) -> dict:
    """Get profile for a symbol, resolving aliases (e.g., GOLDmicro → GOLD)."""
    canonical = SYMBOL_ALIASES.get(symbol, symbol)
    profile = SYMBOL_PROFILES.get(canonical, SYMBOL_PROFILES.get(symbol, {}))
    if not profile:
        # Fallback: try stripping common suffixes
        for suffix in ("micro", ".micro", "m"):
            base = symbol.removesuffix(suffix)
            if base != symbol and base in SYMBOL_PROFILES:
                return SYMBOL_PROFILES[base]
    return profile


def get_canonical_symbol(symbol: str) -> str:
    """Resolve alias to canonical symbol name (e.g., GOLDmicro → GOLD)."""
    return SYMBOL_ALIASES.get(symbol, symbol)


def resolve_broker_symbol(symbol: str) -> str:
    """Resolve canonical symbol to broker name via live engine (e.g., GOLD → GOLDmicro).

    Falls back to the input symbol if the bot manager is unavailable.
    """
    try:
        from app.api.routes.bot import _get_engine
        return _get_engine(symbol).symbol
    except Exception:
        return symbol


# Auto-register aliased profiles so SYMBOL_PROFILES["GOLDmicro"] works directly
for _alias, _canonical in SYMBOL_ALIASES.items():
    if _canonical in SYMBOL_PROFILES and _alias not in SYMBOL_PROFILES:
        _profile = SYMBOL_PROFILES[_canonical].copy()
        _profile["display_name"] = f"{_profile['display_name']} (Micro)"
        _profile["canonical"] = _canonical
        # Micro accounts typically have smaller lot sizes
        _profile["default_lot"] = min(_profile["default_lot"], 0.1)
        _profile["max_lot"] = min(_profile["max_lot"], 1.0)
        SYMBOL_PROFILES[_alias] = _profile


# Session profiles — SL/TP multiplier overrides by trading session
SESSION_PROFILES = {
    "asian":   {"hours": (0, 8),   "sl_atr_mult": 1.2, "tp_atr_mult": 1.5, "confidence_boost": 0.05},
    "london":  {"hours": (8, 13),  "sl_atr_mult": 1.5, "tp_atr_mult": 2.0, "confidence_boost": 0.0},
    "overlap": {"hours": (13, 16), "sl_atr_mult": 1.8, "tp_atr_mult": 2.5, "confidence_boost": -0.05},
    "ny":      {"hours": (16, 21), "sl_atr_mult": 1.5, "tp_atr_mult": 2.0, "confidence_boost": 0.0},
    "off":     {"hours": (21, 24), "sl_atr_mult": 1.0, "tp_atr_mult": 1.2, "confidence_boost": 0.10},
}


def get_current_session(utc_hour: int) -> dict:
    """Return session profile for the given UTC hour."""
    for name, profile in SESSION_PROFILES.items():
        start, end = profile["hours"]
        if start <= utc_hour < end:
            return {**profile, "name": name}
    return {**SESSION_PROFILES["off"], "name": "off"}


class Settings(BaseSettings):
    # MT5 Bridge
    mt5_bridge_url: str = "http://localhost:8001"
    mt5_bridge_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/goldbot"
    database_url_sync: str = "postgresql://user:password@localhost:5432/goldbot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI (Claude Agent SDK uses CLAUDE_CODE_OAUTH_TOKEN env var directly)

    # Binance (for BTCUSD — uses Binance API instead of MT5)
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_base_url: str = "https://testnet.binance.vision"  # testnet default; live = https://api.binance.com
    binance_symbols: str = ""  # comma-separated symbols to route via Binance, e.g. "BTCUSD"

    @property
    def binance_symbol_list(self) -> list[str]:
        return [s.strip() for s in self.binance_symbols.split(",") if s.strip()]

    # Bot Config
    symbol: str = "GOLD"  # kept for backward compat
    symbols: str = "GOLD"  # comma-separated list, e.g. "GOLD,OILCash,BTCUSD,USDJPY"
    timeframe: str = "M15"
    max_risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_concurrent_trades: int = 3
    max_lot: float = 1.0
    max_drawdown_from_peak: float = 0.15  # 15% absolute drawdown → halt
    use_ai_filter: bool = True
    ai_confidence_threshold: float = 0.7
    paper_trade: bool = False

    # Position management
    max_position_duration_hours: float = 0  # 0=disabled, e.g. 8.0 = auto-close after 8h
    partial_tp_atr_mult: float = 1.0  # partial TP trigger at ATR * this multiplier
    breakeven_atr_mult: float = 0.5   # move SL to breakeven after profit > this * ATR
    enable_scale_in: bool = False     # enable momentum add-on positions
    max_scale_in_count: int = 1       # max add-on entries per position
    enable_partial_tp: bool = False   # enable close-and-reopen partial TP

    # Portfolio risk
    max_portfolio_leverage: float = 3.0  # block trades when total leverage exceeds this

    # Session-aware trading
    use_session_profiles: bool = False  # adjust SL/TP per trading session

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
    use_mtf_filter: bool = True          # Phase G: multi-timeframe trend confirmation
    mtf_timeframes: str = "H4,D1"       # timeframes for MTF consensus (comma-separated)

    # Strategy ensemble
    ensemble_strategies: str = ""        # e.g. "ema_crossover:0.3,breakout:0.3,mean_reversion:0.2,rsi_filter:0.2"

    # ML auto-rollback
    ml_auto_rollback: bool = True
    ml_rollback_accuracy_floor: float = 0.30  # rollback if accuracy drops below this
    ml_rollback_min_predictions: int = 50     # minimum predictions before rollback check

    # Runner
    runner_backend: str = "process"  # "process" or "docker"
    docker_host: str = ""  # e.g. "tcp://vps:2376" for remote Docker
    docker_tls_ca: str = ""
    docker_tls_cert: str = ""
    docker_tls_key: str = ""
    runner_default_image: str = "trading-agent:latest"
    runner_heartbeat_interval: int = 30  # seconds
    runner_heartbeat_max_misses: int = 3
    runner_max_concurrent_jobs: int = 3

    # Agent
    agent_mode: str = "single"  # "single" (Phase C) or "multi" (Phase D: orchestrator + specialists)
    trading_mode: str = "strategy"  # "strategy" (strategy-first, AI filter) | "ai_autonomous" (AI decides)
    rollout_mode: str = "shadow"  # "shadow" | "paper" | "micro" | "live" (Phase F gradual rollout)

    # Logging
    log_format: str = "text"  # "json" for production, "text" for development
    log_dir: str = "logs"

    # Authentication
    auth_username: str = "admin"          # legacy password auth (deprecated)
    auth_password_hash: str = ""          # bcrypt hash; empty = auth disabled
    jwt_expire_hours: int = 24

    # WebAuthn (Passkey) — new auth system
    webauthn_rp_id: str = "localhost"     # e.g. "gold-trader-01.up.railway.app" for prod
    webauthn_origin: str = "http://localhost:3000"  # frontend origin for WebAuthn verification

    # Secrets Vault
    vault_master_key: str = ""  # AES-256 master key for encrypting secrets; empty = vault disabled

    # API
    secret_key: str = ""
    cors_origins: str = "http://localhost:3000"

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    # DB connection pool
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
