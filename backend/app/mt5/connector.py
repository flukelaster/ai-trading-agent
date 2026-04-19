"""
MT5 Bridge Connector — HTTP client that calls the MT5 Bridge on Windows VPS.
"""

import asyncio
from typing import Any

import httpx
from loguru import logger

from app.config import settings


class MT5BridgeConnector:
    def __init__(self):
        self.base_url = settings.mt5_bridge_url
        self.headers = {"X-Bridge-Key": settings.mt5_bridge_api_key}
        self.timeout = 8.0
        self.max_retries = 2
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.close()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        import time
        client = await self._get_client()
        start = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                response = await getattr(client, method)(path, **kwargs)
                response.raise_for_status()
                result = response.json()
                await self._record_timing(path, time.monotonic() - start)
                return result
            except (httpx.TimeoutException, httpx.ConnectError, ValueError) as e:
                if attempt < self.max_retries:
                    logger.warning(f"MT5 Bridge {method.upper()} {path} retry {attempt + 1}: {e}")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"MT5 Bridge {method.upper()} {path} failed after {self.max_retries + 1} attempts: {e}")
                    await self._record_timing(path, time.monotonic() - start, error=True)
                    return {"success": False, "data": None, "error": str(e)}
            except httpx.HTTPStatusError as e:
                logger.error(f"MT5 Bridge {method.upper()} {path} HTTP error: {e.response.status_code}")
                await self._record_timing(path, time.monotonic() - start, error=True)
                return {"success": False, "data": None, "error": str(e)}

    async def _record_timing(self, path: str, duration: float, error: bool = False):
        """Record request timing to metrics (if available)."""
        try:
            from app.metrics import get_metrics
            metrics = get_metrics()
            if metrics:
                name = f"mt5_bridge{path.replace('/', '_')}"
                await metrics.record_timing(name, round(duration * 1000, 1))
                if error:
                    await metrics.increment_counter(f"mt5_bridge_errors")
        except Exception:
            pass

    async def _request_fast(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Single attempt with short timeout — for ephemeral data like ticks."""
        client = await self._get_client()
        try:
            response = await getattr(client, method)(path, timeout=2.0, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, ValueError):
            return {"success": False, "data": None, "error": "tick timeout"}

    async def get_health(self) -> dict:
        return await self._request("get", "/health")

    async def get_tick(self, symbol: str) -> dict:
        return await self._request_fast("get", f"/tick/{symbol}")

    async def get_ohlcv(self, symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
        return await self._request("get", f"/ohlcv/{symbol}", params={"timeframe": timeframe, "count": count})

    async def get_symbol_spec(self, symbol: str) -> dict:
        """Fetch broker-side symbol spec (digits, volume limits, contract size)."""
        return await self._request("get", f"/symbol-spec/{symbol}")

    async def get_account(self) -> dict:
        return await self._request("get", "/account")

    async def get_positions(self) -> dict:
        return await self._request("get", "/positions")

    async def place_order(
        self, symbol: str, order_type: str, lot: float, sl: float, tp: float, comment: str = "", magic: int | None = None
    ) -> dict:
        from app.constants import MT5_MAGIC_NUMBER
        if magic is None:
            magic = MT5_MAGIC_NUMBER
        return await self._request("post", "/order", json={
            "symbol": symbol,
            "type": order_type,
            "lot": lot,
            "sl": sl,
            "tp": tp,
            "comment": comment,
            "magic": magic,
        })

    async def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        body = {}
        if sl is not None:
            body["sl"] = sl
        if tp is not None:
            body["tp"] = tp
        return await self._request("put", f"/position/{ticket}", json=body)

    async def close_position(self, ticket: int) -> dict:
        return await self._request("delete", f"/position/{ticket}")

    async def close_all_positions(self, symbol: str | None = None) -> dict:
        params = {"symbol": symbol} if symbol else {}
        return await self._request("delete", "/positions", params=params)

    async def get_ohlcv_range(self, symbol: str, timeframe: str, from_date: str, to_date: str) -> dict:
        """Fetch historical OHLCV data by date range. Uses longer timeout for large datasets."""
        client = await self._get_client()
        try:
            response = await client.get(
                f"/ohlcv/{symbol}/history",
                params={"timeframe": timeframe, "from_date": from_date, "to_date": to_date},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.error(f"MT5 Bridge historical OHLCV failed: {e}")
            return {"success": False, "data": None, "error": str(e)}
        except httpx.HTTPStatusError as e:
            logger.error(f"MT5 Bridge historical OHLCV HTTP error: {e.response.status_code}")
            return {"success": False, "data": None, "error": str(e)}
        except ValueError as e:
            logger.error(f"MT5 Bridge historical OHLCV invalid response: {e}")
            return {"success": False, "data": None, "error": str(e)}

    async def get_history(self, days: int = 1, symbol: str | None = None) -> dict:
        params: dict = {"days": days}
        if symbol:
            params["symbol"] = symbol
        return await self._request("get", "/history", params=params)
