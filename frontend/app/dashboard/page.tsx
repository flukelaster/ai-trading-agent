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
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import SentimentBadge from "@/components/ai/SentimentBadge";
import NewsCard from "@/components/ai/NewsCard";
import PriceChart from "@/components/chart/PriceChart";
import EventFeed from "@/components/dashboard/EventFeed";
import {
  getBotStatus, startBot, stopBot, emergencyStop, getPositions,
  getLatestSentiment, getSentimentHistory, updateSettings, updateStrategy, getAccount,
  getDailyPnl,
  getBotEvents,
  getSymbols,
} from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
import { useBotStore } from "@/store/botStore";

export default function DashboardPage() {
  const {
    activeSymbol, symbols, status, symbolStatuses, positions, sentiment, tick, ticks, events,
    setActiveSymbol, setSymbols, setStatus, setSymbolStatuses, setPositions, setSentiment, setTick, addEvent,
  } = useBotStore();
  const [loading, setLoading] = useState(true);
  const [account, setAccount] = useState<{ balance: number; equity: number; margin: number; free_margin: number; profit: number } | null>(null);
  const [dailyPnl, setDailyPnl] = useState<{ daily_pnl: number; trade_count: number; wins: number; losses: number } | null>(null);
  const [news, setNews] = useState<
    { headline: string; source: string; sentiment_label: string; sentiment_score: number; created_at: string }[]
  >([]);
  const { isConnected, subscribe } = useWebSocket();

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, symbolsRes, posRes, sentRes, newsRes, accRes, pnlRes] = await Promise.all([
        getBotStatus().catch(() => null),
        getSymbols().catch(() => null),
        getPositions().catch(() => null),
        getLatestSentiment().catch(() => null),
        getSentimentHistory(1).catch(() => null),
        getAccount().catch(() => null),
        getDailyPnl().catch(() => null),
      ]);

      // Aggregate status response has { symbols: { XAUUSD: {...}, ... }, active_count, total_count }
      if (statusRes?.data?.symbols) {
        setSymbolStatuses(statusRes.data.symbols);
        // Set active symbol's status for backward compat
        const activeStatus = statusRes.data.symbols[activeSymbol];
        if (activeStatus) setStatus(activeStatus);
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
      <div className="p-3 sm:p-6 space-y-4 sm:space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 sm:h-28 rounded-2xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
          <Skeleton className="h-60 sm:h-80 rounded-2xl lg:col-span-2" />
          <Skeleton className="h-60 sm:h-80 rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 sm:p-6 space-y-4 sm:space-y-6">
      <PageHeader title="Dashboard" subtitle="Real-time trading overview">
        {activeTick && (
          <div className="border border-border rounded-full px-3 py-1.5 sm:px-4 sm:py-2 flex items-center gap-2 sm:gap-3 bg-card">
            <span className="text-[10px] sm:text-xs text-muted-foreground font-medium">{activeSymbol}</span>
            <span className="text-xs sm:text-sm font-mono font-bold text-foreground">
              {activeTick.bid.toFixed(priceDecimals)}
            </span>
            <span className="text-[10px] text-muted-foreground">/</span>
            <span className="text-xs sm:text-sm font-mono text-muted-foreground">
              {activeTick.ask.toFixed(priceDecimals)}
            </span>
            <span className="hidden sm:inline text-[10px] text-muted-foreground font-medium">
              spd: {activeTick.spread.toFixed(1)}
            </span>
          </div>
        )}
        {status?.paper_trade && (
          <Badge variant="outline" className="border-amber-500 text-amber-600 dark:text-amber-400 text-[10px] font-semibold">
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

      {/* Symbol Selector Tabs */}
      {symbols.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {symbols.map((s) => {
            const isActive = s.symbol === activeSymbol;
            const symTick = ticks[s.symbol];
            const symStatus = symbolStatuses[s.symbol];
            return (
              <button
                key={s.symbol}
                type="button"
                onClick={() => setActiveSymbol(s.symbol)}
                className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-semibold transition-all whitespace-nowrap ${
                  isActive
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-card text-foreground border-border hover:border-primary/50"
                }`}
              >
                <span>{s.display_name}</span>
                <span className="font-mono text-[10px] opacity-75">
                  {symTick ? symTick.bid.toFixed(s.price_decimals) : "---"}
                </span>
                <span
                  className={`size-1.5 rounded-full ${
                    symStatus?.state === "RUNNING" ? "bg-green-400" : "bg-muted-foreground/30"
                  }`}
                />
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setViewMode(viewMode === "single" ? "multi" : "single")}
            className="px-3 py-2 rounded-xl border border-border bg-card text-xs font-semibold hover:border-primary/50 transition-all"
          >
            {viewMode === "single" ? "4-Grid" : "Single"}
          </button>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
        <StatCard icon={Wallet} label="Balance" value={account ? `$${account.balance.toLocaleString("en", { minimumFractionDigits: 2 })}` : "—"} variant="gold" />
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
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
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

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground font-medium">AI Filter</span>
                <Switch
                  checked={status?.use_ai_filter ?? true}
                  onCheckedChange={handleAIFilterToggle}
                />
              </div>
            </div>

            {status?.paper_trade && (
              <p className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 rounded-xl px-3 py-1.5 font-medium">
                Paper mode — no real orders sent to MT5
              </p>
            )}

            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex items-center justify-between">
                <span className="font-medium">Strategy</span>
                <Select
                  value={status?.strategy || "ema_crossover"}
                  onValueChange={async (v) => {
                    if (v) {
                      await updateStrategy(v, undefined, activeSymbol);
                      fetchData();
                    }
                  }}
                >
                  <SelectTrigger className="w-32 h-7 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["ema_crossover", "rsi_filter", "breakout", "ml_signal"].map((s) => (
                      <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                    {["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map((tf) => (
                      <SelectItem key={tf} value={tf}>{tf}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        {viewMode === "multi" ? (
          <Card className="order-2 lg:order-1 lg:col-span-2">
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold flex items-center justify-between">
                <span>All Symbols</span>
                <div className="flex gap-0.5 bg-muted rounded-xl p-0.5">
                  {["M1", "M5", "M15", "H1", "H4", "D1"].map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setChartTimeframe(tf)}
                      className={`px-1.5 sm:px-2 py-0.5 rounded-lg text-[10px] font-semibold transition-colors ${
                        chartTimeframe === tf
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
              <div className="grid grid-cols-2 gap-2">
                {symbols.map((s) => (
                  <div
                    key={s.symbol}
                    className="border border-border rounded-xl p-2 cursor-pointer hover:border-primary/50 transition-colors"
                    onClick={() => { setActiveSymbol(s.symbol); setViewMode("single"); }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold">{s.display_name}</span>
                      <span className="text-[10px] font-mono text-muted-foreground">
                        {ticks[s.symbol]?.bid.toFixed(s.price_decimals) || "---"}
                      </span>
                    </div>
                    <div className="h-32">
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
          <Card className="order-2 lg:order-1 lg:col-span-2">
            <CardHeader className="p-3 sm:p-6">
              <CardTitle className="text-sm font-bold flex items-center justify-between">
                <div className="flex items-center gap-2 sm:gap-3">
                  <span>{activeSymbolInfo?.display_name || activeSymbol}</span>
                  {sentiment && (
                    <SentimentBadge label={sentiment.label} score={sentiment.score} size="sm" />
                  )}
                </div>
                <div className="flex gap-0.5 bg-muted rounded-xl p-0.5">
                  {["M1", "M5", "M15", "H1", "H4", "D1"].map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setChartTimeframe(tf)}
                      className={`px-1.5 sm:px-2 py-0.5 rounded-lg text-[10px] font-semibold transition-colors ${
                        chartTimeframe === tf
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="h-48 sm:h-64 p-3 pt-0 sm:p-6 sm:pt-0">
              <PriceChart
                symbol={activeSymbol}
                timeframe={chartTimeframe}
                tick={activeTick}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* News + Positions + Events */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">News Feed</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
            <ScrollArea className="h-48 sm:h-64">
              <div className="space-y-2 pr-3">
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
            </ScrollArea>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">Open Positions</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
            {positions.length > 0 ? (
              <div className="overflow-x-auto -mx-3 px-3 sm:mx-0 sm:px-0">
                <ScrollArea className="h-48 sm:h-64">
                  <Table className="min-w-[480px]">
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
                        <TableRow key={p.ticket}>
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
                </ScrollArea>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8 font-medium">
                No open positions
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="md:col-span-2 lg:col-span-1">
          <CardHeader className="p-3 sm:p-6">
            <CardTitle className="text-sm font-bold">Events</CardTitle>
          </CardHeader>
          <CardContent className="p-3 pt-0 sm:p-6 sm:pt-0">
            <EventFeed events={events} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
