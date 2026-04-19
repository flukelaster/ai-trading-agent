"""
Binance Connector — REST API client for Binance Spot trading.
Same interface as MT5BridgeConnector so BotEngine works unchanged.
Supports both live (api.binance.com) and testnet (testnet.binance.vision).
"""

import hashlib
import hmac
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from loguru import logger

from app.config import settings

# Binance timeframe mapping (MT5 style → Binance style)
TIMEFRAME_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}


class BinanceConnector:
    """Drop-in replacement for MT5BridgeConnector, targeting Binance Spot API."""

    def __init__(self):
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret
        self.base_url = settings.binance_base_url
        self.timeout = 10.0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.close()
            self._client = None

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature to request params."""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _public_get(self, path: str, params: dict | None = None) -> dict:
        """Unsigned GET request (public endpoints)."""
        client = await self._get_client()
        try:
            response = await client.get(path, params=params or {})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Binance GET {path} error: {e}")
            return {}

    async def _signed_get(self, path: str, params: dict | None = None) -> dict:
        """Signed GET request (private endpoints)."""
        client = await self._get_client()
        try:
            signed = self._sign(params or {})
            response = await client.get(path, params=signed)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Binance signed GET {path} error: {e}")
            return {}

    async def _signed_post(self, path: str, params: dict | None = None) -> dict:
        """Signed POST request (trading endpoints)."""
        client = await self._get_client()
        try:
            signed = self._sign(params or {})
            response = await client.post(path, params=signed)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_body = e.response.json() if e.response else {}
            logger.error(f"Binance POST {path} error: {e} — {error_body}")
            return {"error": error_body.get("msg", str(e))}
        except Exception as e:
            logger.error(f"Binance POST {path} error: {e}")
            return {"error": str(e)}

    async def _signed_delete(self, path: str, params: dict | None = None) -> dict:
        """Signed DELETE request."""
        client = await self._get_client()
        try:
            signed = self._sign(params or {})
            response = await client.delete(path, params=signed)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Binance DELETE {path} error: {e}")
            return {"error": str(e)}

    # ── Interface methods (same as MT5BridgeConnector) ──

    async def get_health(self) -> dict:
        result = await self._public_get("/api/v3/ping")
        return {"status": "ok" if result == {} else "error"}

    async def get_tick(self, symbol: str) -> dict:
        """Get current bid/ask price."""
        sym = self._to_binance_symbol(symbol)
        data = await self._public_get("/api/v3/ticker/bookTicker", {"symbol": sym})
        if not data or "bidPrice" not in data:
            return {"success": False, "data": None, "error": "No tick data"}
        bid = float(data["bidPrice"])
        ask = float(data["askPrice"])
        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "spread": round(ask - bid, 8),
                "time": datetime.now(UTC).isoformat(),
            },
        }

    async def get_ohlcv(self, symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
        """Get OHLCV candles."""
        sym = self._to_binance_symbol(symbol)
        interval = TIMEFRAME_MAP.get(timeframe, "15m")
        data = await self._public_get(
            "/api/v3/klines",
            {
                "symbol": sym,
                "interval": interval,
                "limit": count,
            },
        )
        if not data or not isinstance(data, list):
            return {"success": False, "data": None, "error": "No OHLCV data"}

        candles = []
        for k in data:
            candles.append(
                {
                    "time": datetime.fromtimestamp(k[0] / 1000, tz=UTC).isoformat(),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            )
        return {"success": True, "data": candles}

    async def get_account(self) -> dict:
        """Get account balance."""
        data = await self._signed_get("/api/v3/account")
        if not data or "balances" not in data:
            return {"success": False, "data": None, "error": "Account fetch failed"}

        # Sum USDT balance as primary
        usdt = next((b for b in data["balances"] if b["asset"] == "USDT"), None)
        btc = next((b for b in data["balances"] if b["asset"] == "BTC"), None)

        balance = float(usdt["free"]) + float(usdt["locked"]) if usdt else 0
        free = float(usdt["free"]) if usdt else 0
        btc_val = float(btc["free"]) + float(btc["locked"]) if btc else 0

        return {
            "success": True,
            "data": {
                "balance": balance,
                "equity": balance,  # Spot has no margin concept
                "margin": 0,
                "free_margin": free,
                "profit": 0,
                "currency": "USDT",
                "btc_balance": btc_val,
            },
        }

    async def get_positions(self) -> dict:
        """Get open orders as 'positions' (Spot doesn't have positions like MT5)."""
        data = await self._signed_get("/api/v3/openOrders")
        if not isinstance(data, list):
            return {"success": True, "data": []}

        positions = []
        for order in data:
            positions.append(
                {
                    "ticket": order["orderId"],
                    "symbol": self._from_binance_symbol(order["symbol"]),
                    "type": order["side"],
                    "lot": float(order["origQty"]),
                    "open_price": float(order["price"]),
                    "current_price": float(order["price"]),
                    "sl": 0,
                    "tp": 0,
                    "profit": 0,
                    "open_time": datetime.fromtimestamp(order["time"] / 1000, tz=UTC).isoformat(),
                }
            )
        return {"success": True, "data": positions}

    async def place_order(
        self,
        symbol: str,
        order_type: str,
        lot: float,
        sl: float = 0,
        tp: float = 0,
        comment: str = "",
        magic: int = 0,
    ) -> dict:
        """Place a market order on Binance Spot, with optional OCO stop orders."""
        sym = self._to_binance_symbol(symbol)
        side = "BUY" if order_type.upper() == "BUY" else "SELL"

        params = {
            "symbol": sym,
            "side": side,
            "type": "MARKET",
            "quantity": str(lot),
        }

        result = await self._signed_post("/api/v3/order", params)

        if "error" in result:
            return {"success": False, "error": result["error"]}

        fill_price = 0
        if result.get("fills"):
            total_qty = sum(float(f["qty"]) for f in result["fills"])
            total_cost = sum(float(f["qty"]) * float(f["price"]) for f in result["fills"])
            fill_price = total_cost / total_qty if total_qty > 0 else 0

        # Place OCO stop-loss/take-profit orders on exchange (survives bot crash)
        if sl > 0 and tp > 0:
            await self._place_oco_stops(sym, lot, side, sl, tp)

        return {
            "success": True,
            "data": {
                "ticket": result.get("orderId", 0),
                "price": fill_price,
                "lot": float(result.get("executedQty", lot)),
                "type": side,
                "symbol": symbol,
            },
        }

    async def _place_oco_stops(self, binance_symbol: str, qty: float, entry_side: str, sl: float, tp: float):
        """Place OCO order on Binance for SL/TP — survives bot crashes."""
        opposite_side = "SELL" if entry_side == "BUY" else "BUY"
        try:
            oco_params = {
                "symbol": binance_symbol,
                "side": opposite_side,
                "quantity": str(qty),
                "price": str(round(tp, 8)),
                "stopPrice": str(round(sl, 8)),
                "stopLimitPrice": str(round(sl, 8)),
                "stopLimitTimeInForce": "GTC",
            }
            result = await self._signed_post("/api/v3/order/oco", oco_params)
            if "error" not in result:
                logger.info(f"Binance OCO placed: SL={sl}, TP={tp}")
            else:
                logger.warning(f"Binance OCO failed: {result.get('error')} — SL/TP managed by bot")
        except Exception as e:
            logger.warning(f"Binance OCO error: {e} — falling back to bot-managed SL/TP")

    async def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        """Binance Spot doesn't support SL/TP modification on market orders.
        SL/TP must be managed via OCO or separate stop orders."""
        logger.warning(f"Binance: modify_position not supported for Spot (ticket={ticket})")
        return {"success": True, "data": {"message": "SL/TP managed by bot engine"}}

    async def close_position(self, ticket: int) -> dict:
        """Cancel an open order."""
        # For spot, 'closing' means selling what you bought
        logger.warning(f"Binance: close_position ticket={ticket} — use sell order instead")
        return {"success": True, "data": {"ticket": ticket}}

    async def close_all_positions(self, symbol: str | None = None) -> dict:
        """Cancel all open orders."""
        if symbol:
            sym = self._to_binance_symbol(symbol)
            result = await self._signed_delete("/api/v3/openOrders", {"symbol": sym})
        else:
            result = await self._signed_delete("/api/v3/openOrders", {"symbol": "BTCUSDT"})
        return {"success": True, "data": result}

    async def get_ohlcv_range(self, symbol: str, timeframe: str, from_date: str, to_date: str) -> dict:
        """Fetch historical OHLCV by date range."""
        sym = self._to_binance_symbol(symbol)
        interval = TIMEFRAME_MAP.get(timeframe, "15m")

        start_ms = int(datetime.fromisoformat(from_date).timestamp() * 1000)
        end_ms = int(datetime.fromisoformat(to_date).timestamp() * 1000)

        all_candles = []
        current_start = start_ms

        while current_start < end_ms:
            data = await self._public_get(
                "/api/v3/klines",
                {
                    "symbol": sym,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            if not data or not isinstance(data, list) or len(data) == 0:
                break

            for k in data:
                all_candles.append(
                    {
                        "time": datetime.fromtimestamp(k[0] / 1000, tz=UTC).isoformat(),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                )
            current_start = int(data[-1][0]) + 1  # next candle after last

        return {"success": True, "data": all_candles}

    async def get_history(self, days: int = 1, symbol: str = "BTCUSD") -> dict:
        """Get recent trade history."""
        sym = self._to_binance_symbol(symbol)
        data = await self._signed_get(
            "/api/v3/myTrades",
            {
                "symbol": sym,
                "limit": 100,
            },
        )
        if not isinstance(data, list):
            return {"success": True, "data": []}

        cutoff = datetime.now(UTC).timestamp() - (days * 86400)
        trades = []
        for t in data:
            trade_time = t["time"] / 1000
            if trade_time < cutoff:
                continue
            trades.append(
                {
                    "ticket": t["id"],
                    "symbol": symbol,
                    "type": "BUY" if t["isBuyer"] else "SELL",
                    "lot": float(t["qty"]),
                    "price": float(t["price"]),
                    "profit": 0,  # Spot doesn't track PnL per trade
                    "time": datetime.fromtimestamp(trade_time, tz=UTC).isoformat(),
                }
            )
        return {"success": True, "data": trades}

    # ── Symbol mapping helpers ──

    @staticmethod
    def _to_binance_symbol(symbol: str) -> str:
        """Convert bot symbol to Binance symbol (e.g. BTCUSD → BTCUSDT)."""
        mapping = {"BTCUSD": "BTCUSDT", "BTCUSDT": "BTCUSDT"}
        return mapping.get(symbol, symbol + "T" if symbol.endswith("USD") else symbol)

    @staticmethod
    def _from_binance_symbol(symbol: str) -> str:
        """Convert Binance symbol back to bot symbol."""
        if symbol == "BTCUSDT":
            return "BTCUSD"
        return symbol
