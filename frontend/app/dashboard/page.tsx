"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  TrendingUp, Layers, Activity, Play, Square, ShieldAlert, Wifi, WifiOff, DollarSign, Loader2,
} from "lucide-react";
import dynamic from "next/dynamic";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import SentimentBadge from "@/components/ai/SentimentBadge";
import NewsCard from "@/components/ai/NewsCard";
import EventFeed from "@/components/dashboard/EventFeed";

const Markdown = dynamic(() => import("react-markdown"), { ssr: false });
const PriceChart = dynamic(() => import("@/components/chart/PriceChart"), { ssr: false, loading: () => <Skeleton className="h-56 sm:h-72 xl:h-80 rounded-xl" /> });
const LazyRecharts = dynamic(() => import("recharts").then((mod) => {
  const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = mod;
  return { default: ({ data }: { data: { time: string; equity: number }[] }) => (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={data}>
        <defs><linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9fe870" stopOpacity={0.3} /><stop offset="100%" stopColor="#9fe870" stopOpacity={0} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="time" hide fontSize={10} className="fill-muted-foreground" />
        <YAxis fontSize={10} className="fill-muted-foreground" />
        <Tooltip contentStyle={{ backgroundColor: "var(--popover)", border: "1px solid var(--border)", borderRadius: "12px", color: "var(--foreground)" }} />
        <Area type="monotone" dataKey="equity" stroke="#9fe870" fill="url(#eqGrad)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  )};
}), { ssr: false, loading: () => <Skeleton className="h-[180px] rounded-xl" /> });
import {
  getBotStatus, startBot, stopBot, emergencyStop, getPositions,
  getLatestSentiment, getSentimentHistory, updateSettings, updateStrategy, getAccount,
  getDailyPnl,
  getBotEvents,
  getSymbols,
  getAnalytics,
  resetPeakBalance,
} from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
import { showSuccess, showError } from "@/lib/toast";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { SkeletonCard, SkeletonChart } from "@/components/ui/skeleton-compositions";
import { useBotStore } from "@/store/botStore";
import { SymbolTabs } from "@/components/ui/symbol-tabs";
import { TimeframeSelector, TIMEFRAMES } from "@/components/ui/timeframe-selector";

const STRATEGY_TH: Record<string, string> = {
  trend_following: "ตามเทรนด์",
  momentum: "โมเมนตัม",
  mean_reversion: "กลับตัว",
  breakout: "ทะลุแนวรับ/ต้าน",
  ai_autonomous: "AI อัตโนมัติ",
  scalping: "สแคลป์ปิง",
  ema_crossover: "EMA Crossover",
  rsi_filter: "RSI Filter",
  dca: "DCA ถัวเฉลี่ย",
  grid: "Grid เทรด",
  risk_parity: "Risk Parity",
  momentum_rank: "Momentum Rank",
  pair_spread: "Pair Spread",
  ml_signal: "ML Signal",
};

export default function DashboardPage() {
  const activeSymbol = useBotStore((s) => s.activeSymbol);
  const symbols = useBotStore((s) => s.symbols);
  const status = useBotStore((s) => s.status);
  const symbolStatuses = useBotStore((s) => s.symbolStatuses);
  const positions = useBotStore((s) => s.positions);
  const sentiment = useBotStore((s) => s.sentiment);
  const tick = useBotStore((s) => s.tick);
  const ticks = useBotStore((s) => s.ticks);
  const events = useBotStore((s) => s.events);
  const setActiveSymbol = useBotStore((s) => s.setActiveSymbol);
  const setSymbols = useBotStore((s) => s.setSymbols);
  const setStatus = useBotStore((s) => s.setStatus);
  const setSymbolStatuses = useBotStore((s) => s.setSymbolStatuses);
  const setPositions = useBotStore((s) => s.setPositions);
  const setSentiment = useBotStore((s) => s.setSentiment);
  const setTick = useBotStore((s) => s.setTick);
  const addEvent = useBotStore((s) => s.addEvent);
  const [loading, setLoading] = useState(true);
  const [account, setAccount] = useState<{ balance: number; equity: number; margin: number; free_margin: number; profit: number; peak_balance?: number; drawdown_pct?: number; accounts?: { connector: string; balance: number; equity: number; currency: string }[] } | null>(null);
  const [dailyPnl, setDailyPnl] = useState<{ daily_pnl: number; trade_count: number; wins: number; losses: number } | null>(null);
  const [news, setNews] = useState<
    { headline: string; source: string; sentiment_label: string; sentiment_score: number; created_at: string }[]
  >([]);
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const { isConnected, subscribe } = useWebSocket();
  const activeSymbolRef = useRef(activeSymbol);
  activeSymbolRef.current = activeSymbol;

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, symbolsRes, posRes, sentRes, newsRes, accRes, pnlRes, analyticsRes, eventsRes] = await Promise.all([
        getBotStatus().catch(() => null),
        getSymbols().catch(() => null),
        getPositions().catch(() => null),
        getLatestSentiment().catch(() => null),
        getSentimentHistory(1).catch(() => null),
        getAccount().catch(() => null),
        getDailyPnl().catch(() => null),
        getAnalytics(undefined, 30).catch(() => null),
        getBotEvents({ days: 1, limit: 50 }).catch(() => null),
      ]);

      // Aggregate status response has { symbols: { XAUUSD: {...}, ... }, active_count, total_count }
      if (statusRes?.data?.symbols) {
        setSymbolStatuses(statusRes.data.symbols);
        // Set active symbol's status for backward compat
        const activeStatus = statusRes.data.symbols[activeSymbolRef.current];
        if (activeStatus) setStatus(activeStatus);
        // Populate per-symbol sentiment from status
        for (const [sym, st] of Object.entries(statusRes.data.symbols)) {
          const s = st as Record<string, unknown>;
          if (s.sentiment) setSentiment({ ...(s.sentiment as Record<string, unknown>), symbol: sym } as Parameters<typeof setSentiment>[0]);
        }
      } else if (statusRes) {
        // Single-symbol fallback
        setStatus(statusRes.data);
      }

      if (symbolsRes?.data?.symbols) {
        setSymbols(symbolsRes.data.symbols);
      }

      if (posRes?.data?.positions) setPositions(posRes.data.positions);
      if (sentRes?.data) setSentiment(sentRes.data);
      if (newsRes?.data?.history) setNews(newsRes.data.history.slice(0, 5));
      // Only update if data actually returned (prevent clearing on API failure)
      if (accRes?.data?.balance !== undefined) setAccount(accRes.data);
      if (pnlRes?.data?.daily_pnl !== undefined) setDailyPnl(pnlRes.data);
      if (analyticsRes?.data) setAnalytics(analyticsRes.data);

      // Load persisted events from DB (survives page refresh)
      if (eventsRes?.data?.events) {
        const dbEvents = eventsRes.data.events.map((e: { type: string; message: string; created_at: string }) => ({
          type: e.type,
          message: e.message,
          timestamp: e.created_at,
        }));
        // Only seed if store is empty (don't overwrite live WS events)
        // Backend returns DESC (newest first); keep order so addEvent prepend stays consistent
        if (useBotStore.getState().events.length === 0 && dbEvents.length > 0) {
          useBotStore.getState().seedEvents(dbEvents);
        }
      }
    } catch (e) {
      console.error("Failed to fetch data:", e);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setStatus, setSymbolStatuses, setSymbols, setPositions, setSentiment]);

  useEffect(() => {
    fetchData();
    // Phase 4.1: WS pushes status every 15s → REST poll is now fallback only.
    // Raise interval to 5min so REST is a safety net, not the primary data source.
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") fetchData();
    }, 300000);
    // Re-fetch immediately when tab becomes visible (after idle/sleep)
    const onVisible = () => {
      if (document.visibilityState === "visible") fetchData();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [fetchData]);

  useEffect(() => {
    // Phase 4.1: server pushes aggregate status every 15s via Redis pub/sub.
    // Replaces per-client REST polling → 1 in-memory read broadcast to N clients.
    subscribe("status_update", (data) => {
      const d = data as { symbols?: Record<string, Parameters<typeof setStatus>[0]>; active_count?: number; total_count?: number };
      if (d?.symbols) {
        setSymbolStatuses(d.symbols as Parameters<typeof setSymbolStatuses>[0]);
        const active = d.symbols[activeSymbolRef.current];
        if (active) setStatus(active);
        for (const [sym, st] of Object.entries(d.symbols)) {
          const s = st as Record<string, unknown>;
          if (s.sentiment) setSentiment({ ...(s.sentiment as Record<string, unknown>), symbol: sym } as Parameters<typeof setSentiment>[0]);
        }
      }
    });
    subscribe("price_update", (data) => { if (data) setTick(data as NonNullable<typeof tick>); });
    subscribe("position_update", (data) => {
      const d = data as { symbol?: string; positions: typeof positions };
      if (d.positions) {
        // Each engine pushes only its own symbol's positions — merge, don't replace
        const sym = d.symbol || (d.positions.length > 0 ? d.positions[0].symbol : null);
        if (sym) {
          setPositions([
            ...useBotStore.getState().positions.filter((p) => p.symbol !== sym),
            ...d.positions,
          ]);
        }
      }
    });
    subscribe("sentiment_update", (data) => { if (data) setSentiment(data as NonNullable<typeof sentiment>); });
    subscribe("bot_event", (data) => {
      const d = data as { type: string; data?: Record<string, unknown>; ticket?: number; signal?: string; reason?: string; error?: string; symbol?: string; lot?: number; close_price?: number; profit?: number; order?: string };
      let message = d.type;
      if (d.type === "trade_opened") {
        message = `${d.data?.type} ${d.data?.lot} @ ${d.data?.price}`;
      } else if (d.type === "trade_closed") {
        const pnl = d.profit != null ? (d.profit >= 0 ? `+$${d.profit.toFixed(2)}` : `-$${Math.abs(d.profit).toFixed(2)}`) : "";
        message = `#${d.ticket} closed @ ${d.close_price} ${pnl}`;
      } else if (d.type === "signal_detected") {
        message = `${d.signal} signal on ${d.symbol}`;
      } else if (d.type === "trade_blocked") {
        message = `${d.signal} blocked: ${d.reason}`;
      } else if (d.type === "order_failed") {
        message = `${d.order} ${d.lot} ${d.symbol} failed: ${d.error}`;
      }
      addEvent({ type: d.type, message, timestamp: new Date().toISOString() });
      if (d.type === "trade_opened" || d.type === "trade_closed") fetchData();
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const handleStart = async () => { setActionLoading("start"); try { await startBot(activeSymbol); showSuccess(`${activeSymbol} bot started`); await fetchData(); } catch (e) { showError(`Failed to start ${activeSymbol}`); } finally { setActionLoading(null); } };
  const handleStop = async () => { setActionLoading("stop"); try { await stopBot(activeSymbol); showSuccess(`${activeSymbol} bot stopped`); await fetchData(); } catch (e) { showError(`Failed to stop ${activeSymbol}`); } finally { setActionLoading(null); } };
  const handleEmergencyStop = async () => {
    if (confirm("Are you sure? This will close ALL positions for " + activeSymbol + " immediately.")) {
      try { await emergencyStop(activeSymbol); showSuccess(`Emergency stop executed for ${activeSymbol}`); await fetchData(); } catch { showError("Emergency stop failed"); }
    }
  };
  const handleAIFilterToggle = async (enabled: boolean) => {
    try { await updateSettings({ symbol: activeSymbol, use_ai_filter: enabled }); showSuccess(`AI filter ${enabled ? "enabled" : "disabled"}`); await fetchData(); } catch { showError("Failed to update AI filter"); }
  };

  const [chartTimeframe, setChartTimeframe] = useState("M5");
  const [viewMode, setViewMode] = useState<"single" | "multi">("single");
  const chartTfSynced = useRef(false);
  useEffect(() => {
    if (status?.timeframe && !chartTfSynced.current) {
      setChartTimeframe(status.timeframe);
      chartTfSynced.current = true;
    }
  }, [status?.timeframe]);

  // Update status when active symbol changes
  useEffect(() => {
    const s = symbolStatuses[activeSymbol];
    if (s) setStatus(s);
    chartTfSynced.current = false;
  }, [activeSymbol, symbolStatuses]);

  const isRunning = status?.state === "RUNNING";
  const unrealizedPnL = positions.reduce((sum, p) => sum + (p.profit || 0), 0);
  const activeTick = ticks[activeSymbol] || tick;
  const activeSymbolInfo = symbols.find((s) => s.symbol === activeSymbol);
  const priceDecimals = activeSymbolInfo?.price_decimals ?? 2;

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} lines={1} />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
          <SkeletonChart className="lg:col-span-3" />
          <SkeletonCard lines={4} />
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="Dashboard" subtitle="Real-time trading overview">
        {activeTick && (
          <div className="border border-border rounded-full px-3 py-1.5 sm:px-4 sm:py-2 flex items-center gap-2 sm:gap-3 bg-card">
            <span className="text-xs text-muted-foreground font-medium">{activeSymbol}</span>
            <span className="text-xs sm:text-sm font-mono font-bold text-foreground">
              {activeTick.bid.toFixed(priceDecimals)}
            </span>
            <span className="text-xs text-muted-foreground">/</span>
            <span className="text-xs sm:text-sm font-mono text-muted-foreground">
              {activeTick.ask.toFixed(priceDecimals)}
            </span>
            <span className="hidden sm:inline text-xs text-muted-foreground font-medium">
              spd: {activeTick.spread.toFixed(1)}
            </span>
          </div>
        )}
        {status?.paper_trade && (
          <Badge variant="outline" className="border-amber-500 text-amber-600 dark:text-amber-400 text-xs font-semibold">
            PAPER
          </Badge>
        )}
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <Wifi className="size-3.5 text-success dark:text-green-400" />
          ) : (
            <WifiOff className="size-3.5 text-destructive" />
          )}
          <span className="text-xs text-muted-foreground font-medium">
            {isConnected ? "Live" : "Offline"}
          </span>
        </div>
      </PageHeader>

      <PageInstructions

        items={[
          "Start/Stop controls the trading bot. Emergency Stop closes all positions immediately.",
          "The bot trades automatically based on the selected strategy. Monitor open positions, equity, and live events below.",
        ]}
      />

      {/* Symbol Selector Tabs */}
      <SymbolTabs
        symbols={symbols.map(s => ({ ...s, state: symbolStatuses[s.symbol]?.state }))}
        active={activeSymbol}
        onSelect={setActiveSymbol}
      >
        <button
          type="button"
          onClick={() => setViewMode(viewMode === "single" ? "multi" : "single")}
          className="min-h-[44px] px-4 py-2.5 rounded-xl border border-border bg-card text-xs font-semibold hover:border-primary/50 transition-all"
        >
          {viewMode === "single" ? "4-Grid" : "Single"}
        </button>
      </SymbolTabs>

      {/* Account Balances Bar */}
      {account && (
        <div className="flex flex-wrap gap-4 items-center px-4 py-3 rounded-2xl border border-border bg-card">
          {account.accounts && account.accounts.length > 1 ? (
            account.accounts.map((acc, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="size-8 rounded-lg bg-muted flex items-center justify-center">
                  {acc.connector === "binance" ? (
                    <svg viewBox="0 0 511.97 511.97" className="size-5">
                      <path fill="#f3ba2f" d="M156.56,215.14,256,115.71l99.47,99.47,57.86-57.85L256,0,98.71,157.28l57.85,57.85M0,256l57.86-57.87L115.71,256,57.85,313.83Zm156.56,40.85L256,396.27l99.47-99.47,57.89,57.82,0,0L256,512,98.71,354.7l-.08-.09,57.93-57.77M396.27,256l57.85-57.85L512,256l-57.85,57.85Z"/>
                      <path fill="#f3ba2f" d="M314.66,256h0L256,197.25,212.6,240.63h0l-5,5L197.33,255.9l-.08.08.08.08L256,314.72l58.7-58.7,0,0-.05,0"/>
                    </svg>
                  ) : (
                    <img src="/coin.svg" alt="MT5" className="size-5" />
                  )}
                </div>
                <div>
                  <p className="text-xs text-muted-foreground font-medium uppercase">{acc.connector}</p>
                  <p className="text-sm font-bold font-mono"><AnimatedCounter value={acc.balance} prefix="$" />{acc.currency === "USDT" ? " USDT" : ""}</p>
                </div>
                {i < (account.accounts?.length ?? 0) - 1 && <div className="h-8 w-px bg-border ml-2" />}
              </div>
            ))
          ) : (
            <div className="flex items-center gap-3">
              <img src="/coin.svg" alt="Balance" className="size-7" />
              <div>
                <p className="text-xs text-muted-foreground font-medium">Balance</p>
                <p className="text-sm font-bold font-mono"><AnimatedCounter value={account.balance} prefix="$" /></p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2">
        <StatCard
          icon={TrendingUp}
          label="Unrealized P&L"
          value={`${unrealizedPnL >= 0 ? "+" : ""}$${unrealizedPnL.toFixed(2)}`}
          variant={unrealizedPnL >= 0 ? "success" : "danger"}
        />
        <StatCard
          icon={DollarSign}
          label="Daily P&L"
          value={
            dailyPnl
              ? `${dailyPnl.daily_pnl >= 0 ? "+" : ""}$${dailyPnl.daily_pnl.toFixed(2)}`
              : "—"
          }
          subtitle={dailyPnl ? `${dailyPnl.wins}W / ${dailyPnl.losses}L (${dailyPnl.trade_count} trades)` : undefined}
          variant={!dailyPnl ? "default" : dailyPnl.daily_pnl >= 0 ? "success" : "danger"}
        />
        <StatCard icon={Layers} label="Open Positions" value={positions.length} variant="default" />
        <StatCard
          icon={Activity}
          label="Bot Status"
          value={status?.state || "UNKNOWN"}
          variant={isRunning ? "success" : "warning"}
        />
        <div
          className="cursor-pointer"
          title="Click to reset peak balance"
          onClick={async () => {
            if (confirm("Reset peak balance to current balance?")) {
              try {
                await resetPeakBalance();
                window.location.reload();
              } catch (e) {
                console.error("Reset peak failed:", e);
              }
            }
          }}
        >
          <StatCard
            icon={ShieldAlert}
            label="Drawdown"
            value={account?.drawdown_pct != null ? `${(account.drawdown_pct * 100).toFixed(1)}%` : "—"}
            subtitle={account?.peak_balance ? `Peak: $${account.peak_balance.toFixed(0)} (click reset)` : undefined}
            variant={
              !account?.drawdown_pct ? "default"
              : account.drawdown_pct < 0.05 ? "success"
              : account.drawdown_pct < 0.10 ? "warning"
              : "danger"
            }
          />
        </div>
      </div>

      {/* Controls + Price Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 xl:gap-6">
        <Card className="order-1 lg:order-2">
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">Controls</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0 space-y-3 sm:space-y-4">
            <div className="flex gap-2">
              <Button
                onClick={handleStart}
                disabled={isRunning || actionLoading === "start"}
                className="flex-1 rounded-full bg-primary text-primary-foreground font-semibold hover-scale"
              >
                {actionLoading === "start" ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Play className="size-4 mr-1.5" />}
                {actionLoading === "start" ? "Starting..." : "Start"}
              </Button>
              <Button
                onClick={handleStop}
                disabled={!isRunning || actionLoading === "stop"}
                variant="secondary"
                className="flex-1 rounded-full"
              >
                {actionLoading === "stop" ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Square className="size-3.5 mr-1.5" />}
                {actionLoading === "stop" ? "Stopping..." : "Stop"}
              </Button>
            </div>
            <Button
              onClick={handleEmergencyStop}
              variant="destructive"
              className="w-full rounded-full"
            >
              <ShieldAlert className="size-4 mr-1.5" />
              Emergency Stop
            </Button>

            <Separator />

            {status?.paper_trade && (
              <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 rounded-xl px-3 py-1.5 font-medium">
                Paper mode — no real orders
              </p>
            )}

            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span className="font-medium">Mode</span>
                <span className="font-semibold text-green-400">Strategy-First</span>
              </div>
              <div className="flex justify-between">
                <span className="font-medium">Strategy</span>
                <span className="text-foreground font-semibold">{status?.strategy || "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="font-medium">Symbol</span>
                <span className="text-foreground font-semibold">{activeSymbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="font-medium">Timeframe</span>
                <span className="text-foreground font-semibold">{status?.timeframe || "M15"}</span>
              </div>
              <div className="flex justify-between">
                <span className="font-medium">Lot</span>
                <span className="text-foreground font-semibold">{status?.fixed_lot != null ? `Fixed ${status.fixed_lot}` : "Auto"}</span>
              </div>
              {(status?.multi_tf_regime || status?.regime) && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">Regime</span>
                    <Badge variant="outline" className={`text-[10px] ${
                      (status.multi_tf_regime?.composite || status.regime) === "trending_high_vol" ? "border-red-500/30 text-red-400" :
                      (status.multi_tf_regime?.composite || status.regime) === "ranging" ? "border-blue-500/30 text-blue-400" :
                      (status.multi_tf_regime?.composite || status.regime) === "trending_low_vol" ? "border-green-500/30 text-green-400" :
                      "border-border text-muted-foreground"
                    }`}>
                      {(status.multi_tf_regime?.composite || status.regime) === "trending_high_vol" ? "🔥 Trend+HV" :
                       (status.multi_tf_regime?.composite || status.regime) === "trending_low_vol" ? "📊 Trend+LV" :
                       (status.multi_tf_regime?.composite || status.regime) === "ranging" ? "↔️ Ranging" :
                       "⚖️ Normal"}
                      {status.multi_tf_regime?.style && ` · ${status.multi_tf_regime.style}`}
                    </Badge>
                  </div>
                  {status.multi_tf_regime && (
                    <div className="flex gap-1 justify-end">
                      {(["m15", "h1", "h4"] as const).map((tf) => {
                        const r = status.multi_tf_regime?.[tf];
                        const short = r === "trending_high_vol" ? "T↑" : r === "trending_low_vol" ? "T↓" : r === "ranging" ? "R" : "N";
                        const color = r === "trending_high_vol" ? "text-red-400" : r === "ranging" ? "text-blue-400" : r === "trending_low_vol" ? "text-green-400" : "text-muted-foreground";
                        return <span key={tf} className={`text-[9px] font-mono ${color}`}>{tf.toUpperCase()}:{short}</span>;
                      })}
                    </div>
                  )}
                </div>
              )}
              <Separator />
              <a href="/settings" className="text-[11px] text-primary hover:underline">
                Settings
              </a>
            </div>
          </CardContent>
        </Card>

        <div className="order-2 lg:order-1 lg:col-span-3 flex flex-col gap-4 xl:gap-6">
          {viewMode === "multi" ? (
            <Card>
              <CardHeader className="p-3 sm:p-6">
                <CardTitle className="text-sm font-bold flex items-center justify-between">
                  <span>All Symbols</span>
                  <TimeframeSelector value={chartTimeframe} onChange={setChartTimeframe} />
                </CardTitle>
              </CardHeader>
              <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
                <div className="grid grid-cols-2 gap-2">
                  {symbols.map((s) => (
                    <div
                      key={s.symbol}
                      className="border border-border rounded-xl p-2 cursor-pointer hover:border-primary/50 glow-hover transition-colors"
                      onClick={() => { setActiveSymbol(s.symbol); setViewMode("single"); }}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-bold">{s.display_name}</span>
                        <span className="text-xs font-mono text-muted-foreground">
                          {ticks[s.symbol]?.bid.toFixed(s.price_decimals) || "---"}
                        </span>
                      </div>
                      <div className="h-40">
                        <PriceChart
                          symbol={s.symbol}
                          timeframe={chartTimeframe}
                          tick={ticks[s.symbol] || null}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="p-3 sm:p-6">
                <CardTitle className="text-sm font-bold space-y-2 sm:space-y-0">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2 sm:gap-3">
                      <span>{activeSymbolInfo?.display_name || activeSymbol}</span>
                      <SentimentBadge label={sentiment?.label || "neutral"} score={sentiment?.score || 0} size="sm" />
                    </div>
                    <TimeframeSelector value={chartTimeframe} onChange={setChartTimeframe} />
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent className="h-56 sm:h-72 xl:h-80 p-3 pt-0 sm:p-6 sm:pt-0">
                <PriceChart
                  key={`${activeSymbol}-${chartTimeframe}`}
                  symbol={activeSymbol}
                  timeframe={chartTimeframe}
                  tick={activeTick}
                />
              </CardContent>
            </Card>
          )}

          {/* Open Positions — below chart */}
          <Card>
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold">Open Positions</CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
              {positions.length > 0 ? (
                <div className="overflow-x-auto -mx-3 px-3 sm:mx-0 sm:px-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead className="text-right">Lots</TableHead>
                        <TableHead className="text-right">Entry</TableHead>
                        <TableHead className="text-right">SL</TableHead>
                        <TableHead className="text-right">TP</TableHead>
                        <TableHead className="text-right">P&L</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {positions.map((p) => (
                        <TableRow key={p.ticket} className="hover:bg-muted/30 transition-colors">
                          <TableCell className="font-medium text-xs">{p.symbol}</TableCell>
                          <TableCell
                            className={`font-semibold ${p.type === "BUY" ? "text-success dark:text-green-400" : "text-destructive"}`}
                          >
                            {p.type}
                          </TableCell>
                          <TableCell className="text-right font-mono">{p.lot}</TableCell>
                          <TableCell className="text-right font-mono">{p.open_price.toFixed(2)}</TableCell>
                          <TableCell className="text-right font-mono text-muted-foreground">
                            {p.sl.toFixed(2)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-muted-foreground">
                            {p.tp.toFixed(2)}
                          </TableCell>
                          <TableCell
                            className={`text-right font-mono font-semibold ${p.profit >= 0 ? "text-success dark:text-green-400" : "text-destructive"}`}
                          >
                            {p.profit >= 0 ? "+" : ""}
                            {p.profit.toFixed(2)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8 font-medium">
                  No open positions
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* AI Decision + News + Positions + Events — single column */}
      <div className="space-y-4 xl:space-y-6">
        {/* AI Decision */}
        {status?.ai_decision && (
          <Card>
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Activity className="size-4 text-primary" />
                    AI วิเคราะห์ล่าสุด
                    {(() => {
                      const d = (status.ai_decision.decision as string || "").toLowerCase();
                      const signal = d.includes("buy") && !d.includes("hold") ? "BUY" : d.includes("sell") && !d.includes("hold") ? "SELL" : "HOLD";
                      const color = signal === "BUY" ? "bg-green-500/10 text-green-400 border-green-500/20" : signal === "SELL" ? "bg-red-500/10 text-red-400 border-red-500/20" : "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
                      return <Badge variant="outline" className={`text-[10px] ${color}`}>{signal}</Badge>;
                    })()}
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-normal text-muted-foreground">
                  <span>{(status.ai_decision as Record<string, unknown>).timestamp ? new Date((status.ai_decision as Record<string, unknown>).timestamp as string).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }) : "—"}</span>
                  <span>{status.ai_decision.tool_calls} tools</span>
                  <span>{status.ai_decision.turns} turns</span>
                  <span>{status.ai_decision.duration_s}s</span>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
              <div className="text-sm text-foreground leading-relaxed max-w-none [&_h2]:text-base [&_h2]:font-bold [&_h2]:mt-3 [&_h2]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1 [&_p]:my-1 [&_ul]:my-1 [&_ul]:pl-4 [&_ul]:list-disc [&_li]:my-0.5 [&_strong]:text-primary">
                <Markdown>{status.ai_decision.decision}</Markdown>
              </div>
            </CardContent>
          </Card>
        )}

        {/* News Feed */}
        <Card>
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">News Feed</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
            <div>
              {news.length > 0 ? (
                news.map((n, i) => (
                  <NewsCard
                    key={i}
                    headline={n.headline}
                    source={n.source}
                    time={n.created_at}
                    sentimentLabel={n.sentiment_label}
                    sentimentScore={n.sentiment_score}
                  />
                ))
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8 font-medium">
                  No recent news
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Events */}
        <Card>
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">Events</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
            <EventFeed events={events} />
          </CardContent>
        </Card>
      </div>

      {/* Performance Analytics */}
      {analytics && (analytics.total_trades as number) > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-bold text-foreground">Performance Analytics (30d)</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Sharpe</p>
              <p className={`text-lg font-bold ${(analytics.sharpe_ratio as number) > 1 ? "text-success dark:text-green-400" : "text-foreground"}`}>
                {(analytics.sharpe_ratio as number).toFixed(2)}
              </p>
            </div>
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Sortino</p>
              <p className={`text-lg font-bold ${(analytics.sortino_ratio as number) > 1.5 ? "text-success dark:text-green-400" : "text-foreground"}`}>
                {(analytics.sortino_ratio as number).toFixed(2)}
              </p>
            </div>
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Profit Factor</p>
              <p className={`text-lg font-bold ${(analytics.profit_factor as number) > 1.5 ? "text-success dark:text-green-400" : "text-foreground"}`}>
                {(analytics.profit_factor as number).toFixed(2)}
              </p>
            </div>
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Max Drawdown</p>
              <p className="text-lg font-bold text-destructive">
                {(analytics.max_drawdown_pct as number).toFixed(1)}%
              </p>
            </div>
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Win Streak</p>
              <p className="text-lg font-bold text-foreground">{analytics.consecutive_wins as number}</p>
            </div>
            <div className="border border-border rounded-xl p-4 text-center">
              <p className="text-xs text-muted-foreground font-medium">Loss Streak</p>
              <p className="text-lg font-bold text-foreground">{analytics.consecutive_losses as number}</p>
            </div>
          </div>

          {(analytics.equity_curve as {time: string; equity: number}[])?.length > 1 && (
            <Card>
              <CardHeader className="p-3 sm:p-6">
                <CardTitle className="text-sm font-bold">Equity Curve</CardTitle>
              </CardHeader>
              <CardContent className="h-48 p-3 pt-0 sm:p-6 sm:pt-0">
                <LazyRecharts data={analytics.equity_curve as {time: string; equity: number}[]} />
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
