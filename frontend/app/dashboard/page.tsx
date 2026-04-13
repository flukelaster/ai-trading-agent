"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Wallet, TrendingUp, Layers, Activity, Play, Square, ShieldAlert, Wifi, WifiOff, DollarSign,
} from "lucide-react";
import Markdown from "react-markdown";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import { AnimatedCounter } from "@/components/ui/animated-counter";
import SentimentBadge from "@/components/ai/SentimentBadge";
import NewsCard from "@/components/ai/NewsCard";
import PriceChart from "@/components/chart/PriceChart";
import EventFeed from "@/components/dashboard/EventFeed";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  getBotStatus, startBot, stopBot, emergencyStop, getPositions,
  getLatestSentiment, getSentimentHistory, updateSettings, updateStrategy, getAccount,
  getDailyPnl,
  getBotEvents,
  getSymbols,
  getAnalytics,
} from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
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
};

export default function DashboardPage() {
  const {
    activeSymbol, symbols, status, symbolStatuses, positions, sentiment, tick, ticks, events,
    setActiveSymbol, setSymbols, setStatus, setSymbolStatuses, setPositions, setSentiment, setTick, addEvent,
  } = useBotStore();
  const [loading, setLoading] = useState(true);
  const [account, setAccount] = useState<{ balance: number; equity: number; margin: number; free_margin: number; profit: number; accounts?: { connector: string; balance: number; equity: number; currency: string }[] } | null>(null);
  const [dailyPnl, setDailyPnl] = useState<{ daily_pnl: number; trade_count: number; wins: number; losses: number } | null>(null);
  const [news, setNews] = useState<
    { headline: string; source: string; sentiment_label: string; sentiment_score: number; created_at: string }[]
  >([]);
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const { isConnected, subscribe } = useWebSocket();

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, symbolsRes, posRes, sentRes, newsRes, accRes, pnlRes, analyticsRes] = await Promise.all([
        getBotStatus().catch(() => null),
        getSymbols().catch(() => null),
        getPositions().catch(() => null),
        getLatestSentiment().catch(() => null),
        getSentimentHistory(1).catch(() => null),
        getAccount().catch(() => null),
        getDailyPnl().catch(() => null),
        getAnalytics(undefined, 30).catch(() => null),
      ]);

      // Aggregate status response has { symbols: { XAUUSD: {...}, ... }, active_count, total_count }
      if (statusRes?.data?.symbols) {
        setSymbolStatuses(statusRes.data.symbols);
        // Set active symbol's status for backward compat
        const activeStatus = statusRes.data.symbols[activeSymbol];
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

      if (posRes) setPositions(posRes.data.positions || []);
      if (sentRes) setSentiment(sentRes.data);
      if (newsRes) setNews((newsRes.data.history || []).slice(0, 5));
      if (accRes) setAccount(accRes.data);
      if (pnlRes) setDailyPnl(pnlRes.data);
      if (analyticsRes) setAnalytics(analyticsRes.data);

      // Load persisted events from DB (survives page refresh)
      const eventsRes = await getBotEvents({ days: 1, limit: 50 }).catch(() => null);
      if (eventsRes?.data?.events) {
        const dbEvents = eventsRes.data.events.map((e: { type: string; message: string; created_at: string }) => ({
          type: e.type,
          message: e.message,
          timestamp: e.created_at,
        }));
        // Only seed if store is empty (don't overwrite live WS events)
        if (events.length === 0 && dbEvents.length > 0) {
          for (const ev of dbEvents.reverse()) {
            addEvent(ev);
          }
        }
      }
    } catch (e) {
      console.error("Failed to fetch data:", e);
    } finally {
      setLoading(false);
    }
  }, [activeSymbol, setStatus, setSymbolStatuses, setSymbols, setPositions, setSentiment]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    subscribe("price_update", (data) => { if (data) setTick(data as NonNullable<typeof tick>); });
    subscribe("position_update", (data) => {
      const d = data as { positions: typeof positions };
      if (d.positions) setPositions(d.positions);
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

  const handleStart = async () => { await startBot(activeSymbol); fetchData(); };
  const handleStop = async () => { await stopBot(activeSymbol); fetchData(); };
  const handleEmergencyStop = async () => {
    if (confirm("Are you sure? This will close ALL positions for " + activeSymbol + " immediately.")) {
      await emergencyStop(activeSymbol);
      fetchData();
    }
  };
  const handleAIFilterToggle = async (enabled: boolean) => {
    await updateSettings({ symbol: activeSymbol, use_ai_filter: enabled });
    fetchData();
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
            <Skeleton key={i} className="h-24 sm:h-28 rounded-2xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
          <Skeleton className="h-60 sm:h-80 rounded-2xl lg:col-span-3" />
          <Skeleton className="h-60 sm:h-80 rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
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
        <div className="flex flex-wrap gap-4 items-center px-4 py-3 rounded-2xl border border-border bg-card animate-fade-in">
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
                    <svg viewBox="0 0 122.88 122.88" className="size-5">
                      <path fill="#fecb00" d="M61.44,0A61.46,61.46,0,1,1,18,18,61.21,61.21,0,0,1,61.44,0Z"/>
                      <path fill="#db9300" d="M63.28,12.41A50.87,50.87,0,1,1,12.41,63.28,50.87,50.87,0,0,1,63.28,12.41Z"/>
                      <path fill="#fecb00" d="M81.19,45,67.1,47.22a14.53,14.53,0,0,0-1.91-3.68,9.19,9.19,0,0,0-2.81-2.08V52.38q11.48,3.07,15.34,6.47a14.92,14.92,0,0,1,5.09,11.61A15.77,15.77,0,0,1,81,78a18.66,18.66,0,0,1-4.68,5.75,18.87,18.87,0,0,1-6.07,3.35,30,30,0,0,1-7.85,1.22v7.12h-5.5V88.32a34.54,34.54,0,0,1-9-1.78,18.16,18.16,0,0,1-6-3.6A17.75,17.75,0,0,1,38,78a23.24,23.24,0,0,1-2-6.41l15.24-1.77a13.92,13.92,0,0,0,1.85,5.37,9.55,9.55,0,0,0,3.8,2.93V64.75A69.82,69.82,0,0,1,46,61.09a14.48,14.48,0,0,1-7.89-13.31,15,15,0,0,1,4.71-11.25q4.72-4.53,14-5V27.8h5.5v3.71q8.48.52,13,4A16.06,16.06,0,0,1,81.19,45ZM56.88,41.26a7.19,7.19,0,0,0-3.38,2,4.24,4.24,0,0,0-1,2.76,4.47,4.47,0,0,0,1,2.87,7.1,7.1,0,0,0,3.36,2.07V41.26Zm5.5,37.23a8.76,8.76,0,0,0,4.69-2.37,5.37,5.37,0,0,0,1.5-3.69,5.08,5.08,0,0,0-1.26-3.29,11.58,11.58,0,0,0-4.93-2.77V78.49Z"/>
                    </svg>
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
              <Wallet className="size-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground font-medium">Balance</p>
                <p className="text-sm font-bold font-mono"><AnimatedCounter value={account.balance} prefix="$" /></p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 animate-fade-in" style={{ animationDelay: "0.05s" }}>
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
      </div>

      {/* Controls + Price Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 xl:gap-6 animate-fade-in" style={{ animationDelay: "0.1s" }}>
        <Card className="order-1 lg:order-2">
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">Controls</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0 space-y-3 sm:space-y-4">
            <div className="flex gap-2">
              <Button
                onClick={handleStart}
                disabled={isRunning}
                className="flex-1 rounded-full bg-primary text-primary-foreground font-semibold hover-scale"
              >
                <Play className="size-4 mr-1.5" />
                Start
              </Button>
              <Button
                onClick={handleStop}
                disabled={!isRunning}
                variant="secondary"
                className="flex-1 rounded-full"
              >
                <Square className="size-3.5 mr-1.5" />
                Stop
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

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-1">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground font-medium">Paper Trade</span>
                <Switch
                  checked={status?.paper_trade ?? false}
                  onCheckedChange={async (v) => { await updateSettings({ symbol: activeSymbol, paper_trade: v }); fetchData(); }}
                />
              </div>

              </div>

            {status?.paper_trade && (
              <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 rounded-xl px-3 py-1.5 font-medium">
                Paper mode — no real orders sent to MT5
              </p>
            )}

            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex items-center justify-between">
                <span className="font-medium">Mode</span>
                <span className="font-semibold text-primary">AI Autonomous</span>
              </div>
              <div className="flex justify-between">
                <span className="font-medium">Symbol</span>
                <span className="text-foreground font-semibold">{activeSymbol}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-medium">Timeframe</span>
                <Select
                  value={status?.timeframe || "M15"}
                  onValueChange={async (v) => { if (v) { await updateSettings({ symbol: activeSymbol, timeframe: v }); fetchData(); } }}
                >
                  <SelectTrigger className="w-24 h-7 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIMEFRAMES.map((tf) => (
                      <SelectItem key={tf} value={tf}>{tf}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        {viewMode === "multi" ? (
          <Card className="order-2 lg:order-1 lg:col-span-3">
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
          <Card className="order-2 lg:order-1 lg:col-span-3">
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold flex items-center justify-between">
                <div className="flex items-center gap-2 sm:gap-3">
                  <span>{activeSymbolInfo?.display_name || activeSymbol}</span>
                  <SentimentBadge label={sentiment?.label || "neutral"} score={sentiment?.score || 0} size="sm" />
                </div>
                <TimeframeSelector value={chartTimeframe} onChange={setChartTimeframe} />
              </CardTitle>
            </CardHeader>
            <CardContent className="h-56 sm:h-72 xl:h-80 p-3 pt-0 sm:p-6 sm:pt-0">
              <PriceChart
                symbol={activeSymbol}
                timeframe={chartTimeframe}
                tick={activeTick}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* AI Decision + News + Positions + Events — single column */}
      <div className="space-y-4 xl:space-y-6 animate-fade-in" style={{ animationDelay: "0.15s" }}>
        {/* AI Decision */}
        {status?.ai_decision && (
          <Card>
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="size-4 text-primary" />
                  AI วิเคราะห์ล่าสุด
                </div>
                <div className="flex items-center gap-3 text-xs font-normal text-muted-foreground">
                  <span className="bg-primary/10 text-primary px-2 py-0.5 rounded-full font-medium">
                    {STRATEGY_TH[status.ai_decision.strategy] || status.ai_decision.strategy?.replace(/_/g, " ")}
                  </span>
                  <span>{status.ai_decision.tool_calls} เครื่องมือ</span>
                  <span>{status.ai_decision.turns} รอบ</span>
                  <span>{status.ai_decision.duration_s}วิ</span>
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
            <div className="space-y-2">
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

        {/* Open Positions */}
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
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={analytics.equity_curve as {time: string; equity: number}[]}>
                    <defs>
                      <linearGradient id="eqGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#9fe870" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#9fe870" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="time" hide />
                    <YAxis className="fill-muted-foreground" fontSize={10} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "var(--popover)",
                        border: "1px solid var(--border)",
                        borderRadius: "12px",
                        color: "var(--foreground)",
                        fontSize: "12px",
                      }}
                      formatter={(value) => [`$${Number(value).toFixed(2)}`, "Equity"]}
                      labelFormatter={() => ""}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#9fe870" strokeWidth={2} fill="url(#eqGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
