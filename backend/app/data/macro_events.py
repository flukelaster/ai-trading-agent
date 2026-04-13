"""
Macro Event Calendar — tracks economic events via API with hardcoded fallback.

Primary: Forex Factory JSON API (free, no key required)
Fallback: hardcoded FOMC/NFP/CPI dates
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger


# Fallback: known FOMC meeting dates for 2026
FOMC_2026 = [
    "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
    "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
]

CALENDAR_API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_KEY = "macro:economic_calendar"
CACHE_TTL = 3600  # 1 hour


class MacroEventCalendar:
    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._cached_events: list[dict] = []

    async def fetch_from_api(self) -> list[dict]:
        """Fetch economic events from Forex Factory API, filter USD high-impact."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(CALENDAR_API_URL)
                resp.raise_for_status()
                data = resp.json()

            events = []
            for item in data:
                # Filter: USD only, high impact
                if item.get("country") != "USD":
                    continue
                if item.get("impact") not in ("High", "high"):
                    continue

                # Parse date
                date_str = item.get("date", "")
                try:
                    event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                events.append({
                    "type": item.get("title", "Unknown")[:20],
                    "name": item.get("title", "Unknown Event"),
                    "date": event_dt.strftime("%Y-%m-%d"),
                    "time": event_dt.strftime("%H:%M"),
                    "impact": "high",
                    "note": f"{item.get('title', '')} — USD high-impact event",
                })

            # Cache in Redis if available
            if self._redis and events:
                await self._redis.setex(CACHE_KEY, CACHE_TTL, json.dumps(events))
                logger.info(f"Economic calendar: cached {len(events)} USD high-impact events")

            return events
        except Exception as e:
            logger.warning(f"Economic calendar API failed: {e}")
            return []

    async def _get_cached_events(self) -> list[dict] | None:
        """Try to get events from Redis cache."""
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(CACHE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    def get_upcoming_events(self, days_ahead: int = 7) -> list[dict]:
        """Return economic events in the next N days (sync, uses cache or fallback)."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)

        # Use cached API events if available
        if self._cached_events:
            filtered = []
            for e in self._cached_events:
                try:
                    dt = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
                    if now.date() <= dt.date() <= end.date():
                        filtered.append(e)
                except (ValueError, KeyError):
                    continue
            if filtered:
                return sorted(filtered, key=lambda e: e["date"])

        # Fallback: hardcoded events
        return self._hardcoded_events(now, end)

    async def refresh(self) -> int:
        """Refresh events from API and update cache. Returns event count."""
        # Try Redis cache first
        cached = await self._get_cached_events()
        if cached:
            self._cached_events = cached
            return len(cached)

        # Fetch from API
        events = await self.fetch_from_api()
        if events:
            self._cached_events = events
            return len(events)

        # Fallback: use hardcoded
        now = datetime.now(timezone.utc)
        self._cached_events = self._hardcoded_events(now, now + timedelta(days=7))
        return len(self._cached_events)

    def is_near_event(self, hours_before: int = 4) -> dict | None:
        """Check if we're within hours_before of a high-impact event."""
        events = self.get_upcoming_events(days_ahead=1)
        now = datetime.now(timezone.utc)
        for event in events:
            time_str = event.get("time", "13:30")
            hour, minute = (int(x) for x in time_str.split(":")) if ":" in time_str else (13, 30)
            event_dt = datetime.fromisoformat(event["date"]).replace(
                hour=hour, minute=minute, tzinfo=timezone.utc,
            )
            if timedelta(0) <= (event_dt - now) <= timedelta(hours=hours_before):
                return event
        return None

    def _hardcoded_events(self, now: datetime, end: datetime) -> list[dict]:
        """Fallback hardcoded events (FOMC 2026 + dynamic NFP/CPI)."""
        events = []

        for date_str in FOMC_2026:
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            if now <= dt <= end:
                events.append({
                    "type": "FOMC", "name": "FOMC Meeting Decision",
                    "date": date_str, "time": "19:00", "impact": "high",
                    "note": "Fed rate decision — high volatility expected",
                })

        for month_offset in range(2):
            nfp = self._first_friday(now.year, now.month + month_offset)
            if nfp and now <= nfp <= end:
                events.append({
                    "type": "NFP", "name": "Non-Farm Payrolls",
                    "date": nfp.strftime("%Y-%m-%d"), "time": "13:30", "impact": "high",
                    "note": "Employment data — strong USD impact",
                })

        for month_offset in range(2):
            m = now.month + month_offset
            y = now.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            cpi_approx = datetime(y, m, 12, tzinfo=timezone.utc)
            if now <= cpi_approx <= end:
                events.append({
                    "type": "CPI", "name": "CPI Release",
                    "date": cpi_approx.strftime("%Y-%m-%d"), "time": "13:30", "impact": "high",
                    "note": "Inflation data — high CPI = USD impact",
                })

        events.sort(key=lambda e: e["date"])
        return events

    def _first_friday(self, year: int, month: int) -> datetime | None:
        if month > 12:
            year += (month - 1) // 12
            month = ((month - 1) % 12) + 1
        try:
            dt = datetime(year, month, 1, tzinfo=timezone.utc)
            days_until_friday = (4 - dt.weekday()) % 7
            return dt + timedelta(days=days_until_friday)
        except ValueError:
            return None
