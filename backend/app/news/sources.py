"""
News source configuration for market sentiment analysis (per-symbol).
"""

NEWS_SOURCES_BY_SYMBOL = {
    "GOLD": [
        {"name": "FXStreet News RSS", "url": "https://www.fxstreet.com/rss/news", "type": "rss", "filter_keywords": ["gold", "XAU", "bullion", "precious metal"]},
        {"name": "Google News Gold RSS", "url": "https://news.google.com/rss/search?q=gold+XAU+price&hl=en&gl=US&ceid=US:en", "type": "rss", "filter_keywords": None},
        {"name": "Investing.com Economy RSS", "url": "https://www.investing.com/rss/news_14.rss", "type": "rss", "filter_keywords": ["gold", "XAU", "bullion", "Fed", "inflation", "dollar", "treasury"]},
    ],
    "OILCash": [
        {"name": "Google News Oil RSS", "url": "https://news.google.com/rss/search?q=crude+oil+WTI+price&hl=en&gl=US&ceid=US:en", "type": "rss", "filter_keywords": None},
        {"name": "Investing.com Economy RSS", "url": "https://www.investing.com/rss/news_14.rss", "type": "rss", "filter_keywords": ["oil", "crude", "WTI", "OPEC", "energy", "petroleum"]},
    ],
    "BTCUSD": [
        {"name": "Google News Bitcoin RSS", "url": "https://news.google.com/rss/search?q=bitcoin+BTC+crypto+price&hl=en&gl=US&ceid=US:en", "type": "rss", "filter_keywords": None},
        {"name": "Investing.com Economy RSS", "url": "https://www.investing.com/rss/news_14.rss", "type": "rss", "filter_keywords": ["bitcoin", "crypto", "BTC", "blockchain", "SEC"]},
    ],
    "USDJPY": [
        {"name": "Google News USDJPY RSS", "url": "https://news.google.com/rss/search?q=USDJPY+yen+dollar+BOJ&hl=en&gl=US&ceid=US:en", "type": "rss", "filter_keywords": None},
        {"name": "Investing.com Economy RSS", "url": "https://www.investing.com/rss/news_14.rss", "type": "rss", "filter_keywords": ["yen", "JPY", "BOJ", "Japan", "dollar", "Fed"]},
    ],
}

# Keep backward compat
NEWS_SOURCES = NEWS_SOURCES_BY_SYMBOL.get("GOLD", [])
