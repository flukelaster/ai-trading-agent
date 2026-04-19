"""
News source configuration for market sentiment analysis (per-symbol).
"""

# ─── Shared: Trump / Trade Policy / Geopolitics (affects ALL markets) ─────────
_TRUMP_TRADE_SOURCES = [
    {
        "name": "Google News Trump Tariff",
        "url": "https://news.google.com/rss/search?q=Trump+tariff+trade+war&hl=en&gl=US&ceid=US:en",
        "type": "rss",
        "filter_keywords": None,
    },
    {
        "name": "Google News US Trade Policy",
        "url": "https://news.google.com/rss/search?q=US+trade+policy+sanctions+tariff&hl=en&gl=US&ceid=US:en",
        "type": "rss",
        "filter_keywords": None,
    },
]

NEWS_SOURCES_BY_SYMBOL = {
    "GOLD": [
        {
            "name": "FXStreet News RSS",
            "url": "https://www.fxstreet.com/rss/news",
            "type": "rss",
            "filter_keywords": ["gold", "XAU", "bullion", "precious metal"],
        },
        {
            "name": "Google News Gold RSS",
            "url": "https://news.google.com/rss/search?q=gold+XAU+price&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["gold", "XAU", "bullion", "Fed", "inflation", "dollar", "treasury"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
    "XAUUSD": None,  # alias → resolved to GOLD below
    "OILCash": [
        {
            "name": "Google News Oil RSS",
            "url": "https://news.google.com/rss/search?q=crude+oil+WTI+price&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["oil", "crude", "WTI", "OPEC", "energy", "petroleum"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
    "OIL": None,  # alias → resolved to OILCash below
    "BTCUSD": [
        {
            "name": "Google News Bitcoin RSS",
            "url": "https://news.google.com/rss/search?q=bitcoin+BTC+crypto+price&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["bitcoin", "crypto", "BTC", "blockchain", "SEC"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
    "USDJPY": [
        {
            "name": "Google News USDJPY RSS",
            "url": "https://news.google.com/rss/search?q=USDJPY+yen+dollar+BOJ&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["yen", "JPY", "BOJ", "Japan", "dollar", "Fed"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
    "EURUSD": [
        {
            "name": "Google News EURUSD RSS",
            "url": "https://news.google.com/rss/search?q=EURUSD+euro+dollar+ECB+Fed&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["euro", "EUR", "ECB", "eurozone", "dollar", "Fed"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
    "US100": [
        {
            "name": "Google News Nasdaq RSS",
            "url": "https://news.google.com/rss/search?q=Nasdaq+100+tech+stocks+earnings&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        {
            "name": "Investing.com Economy RSS",
            "url": "https://www.investing.com/rss/news_14.rss",
            "type": "rss",
            "filter_keywords": ["Nasdaq", "tech", "NVDA", "MSFT", "AAPL", "GOOGL", "AI", "earnings", "Fed"],
        },
        *_TRUMP_TRADE_SOURCES,
    ],
}

# Aliases → canonical. Saves duplication across XAUUSD/GOLD, OIL/OILCash, etc.
_SYMBOL_ALIASES = {"XAUUSD": "GOLD", "OIL": "OILCash"}
for _alias, _canonical in _SYMBOL_ALIASES.items():
    NEWS_SOURCES_BY_SYMBOL[_alias] = NEWS_SOURCES_BY_SYMBOL[_canonical]


def build_generic_sources(symbol: str, display_name: str | None = None) -> list[dict]:
    """Fallback: build Google News RSS + Trump feeds from symbol name.

    Used when NEWS_SOURCES_BY_SYMBOL has no explicit entry — keeps news relevant
    for user-added symbols (ENJ, SOL, TSLA, etc.) without hand-written config.
    """
    from urllib.parse import quote_plus

    query_parts = [symbol]
    if display_name and display_name.lower() != symbol.lower():
        query_parts.append(display_name)
    query_parts.append("price")
    query = quote_plus(" ".join(query_parts))
    return [
        {
            "name": f"Google News {symbol} RSS",
            "url": f"https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en",
            "type": "rss",
            "filter_keywords": None,
        },
        *_TRUMP_TRADE_SOURCES,
    ]


# Keep backward compat
NEWS_SOURCES = NEWS_SOURCES_BY_SYMBOL.get("GOLD", [])
