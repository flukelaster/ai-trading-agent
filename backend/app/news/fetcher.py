"""
News Fetcher — retrieves headlines from RSS feeds for sentiment analysis.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import feedparser
from loguru import logger

from app.news.sources import NEWS_SOURCES


class NewsFetcher:
    def __init__(self, max_age_hours: int = 2, max_headlines: int = 5):
        self.max_age_hours = max_age_hours
        self.max_headlines = max_headlines

    async def fetch_rss(self, url: str, filter_keywords: list[str] | None = None) -> list[dict]:
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
            items = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                # Filter by recency
                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")

                # Filter by keywords if specified
                if filter_keywords:
                    text = f"{title} {summary}".lower()
                    if not any(kw.lower() in text for kw in filter_keywords):
                        continue

                items.append({
                    "title": title,
                    "summary": summary[:200],
                    "published": published.isoformat() if published else None,
                    "source": url,
                })

            return items
        except Exception as e:
            logger.error(f"RSS fetch failed for {url}: {e}")
            return []

    def _dedup_and_limit(self, items: list[dict]) -> list[dict]:
        unique = []
        seen_words = []
        for item in items:
            words = set(item["title"].lower().split())
            is_dup = False
            for sw in seen_words:
                overlap = len(words & sw) / max(len(words | sw), 1)
                if overlap > 0.8:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(item)
                seen_words.append(words)
        unique.sort(key=lambda x: x.get("published") or "", reverse=True)
        return unique[:self.max_headlines]

    async def fetch_all_sources(self) -> list[dict]:
        tasks = []
        for source in NEWS_SOURCES:
            if source["type"] == "rss":
                tasks.append(self.fetch_rss(source["url"], source.get("filter_keywords")))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)

        return self._dedup_and_limit(all_items)

    async def fetch_for_symbol(self, symbol: str) -> list[dict]:
        from app.news.sources import NEWS_SOURCES_BY_SYMBOL
        sources = NEWS_SOURCES_BY_SYMBOL.get(symbol, NEWS_SOURCES_BY_SYMBOL.get("GOLD", []))
        tasks = []
        for source in sources:
            if source["type"] == "rss":
                tasks.append(self.fetch_rss(source["url"], source.get("filter_keywords")))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items = []
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)
        return self._dedup_and_limit(all_items)
