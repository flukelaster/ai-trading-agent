"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Wallet,
  TrendingUp,
  Layers,
  Activity,
  Play,
  Square,
  ShieldAlert,
  Wifi,
  WifiOff,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import SentimentBadge from "@/components/ai/SentimentBadge";
import NewsCard from "@/components/ai/NewsCard";
import PriceChart from "@/components/chart/PriceChart";
import EventFeed from "@/components/dashboard/EventFeed";
import {
  getBotStatus,
  startBot,
  stopBot,
  emergencyStop,
  getPositions,
  getLatestSentiment,
  getSentimentHistory,
  updateSettings,
  getAccount,
} from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
import { useBotStore } from "@/store/botStore";

export default function DashboardPage() {
  const { status, positions, sentiment, tick, events, setStatus, setPositions, setSentiment, setTick, addEvent } =
    useBotStore();
  const [loading, setLoading] = useState(true);
  const [account, setAccount] = useState<{ balance: number; equity: number; margin: number; free_margin: number; profit: number } | null>(null);
  const [news, setNews] = useState<
    { headline: string; source: string; sentiment_label: string; sentiment_score: number; created_at: string }[]
  >([]);
  const { isConnected, subscribe } = useWebSocket();

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, posRes, sentRes, newsRes, accRes] = await Promise.all([
        getBotStatus(),
        getPositions(),
        getLatestSentiment(),
        getSentimentHistory(1),
        getAccount().catch(() => null),
      ]);
      setStatus(statusRes.data);
      setPositions(posRes.data.positions || []);
      setSentiment(sentRes.data);
      setNews((newsRes.data.history || []).slice(0, 5));
      if (accRes) setAccount(accRes.data);
    } catch (e) {
      console.error("Failed to fetch data:", e);
    } finally {
      setLoading(false);
    }
  }, [setStatus, setPositions, setSentiment]);

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
      const d = data as { type: string; data?: Record<string, unknown>; ticket?: number };
      const message = d.type === "trade_opened"
        ? `${d.data?.type} ${d.data?.lot} @ ${d.data?.price}`
        : d.type === "trade_closed"
          ? `Position #${d.ticket} closed`
          : d.type;
      addEvent({ type: d.type, message, timestamp: new Date().toISOString() });
    });
  }, [subscribe, setTick, setPositions, setSentiment, addEvent]);

  const handleStart = async () => { await startBot(); fetchData(); };
  const handleStop = async () => { await stopBot(); fetchData(); };
  const handleEmergencyStop = async () => {
    if (confirm("Are you sure? This will close ALL positions immediately.")) {
      await emergencyStop();
      fetchData();
    }
  };
  const handleAIFilterToggle = async (enabled: boolean) => {
    await updateSettings({ use_ai_filter: enabled });
    fetchData();
  };

  const [chartTimeframe, setChartTimeframe] = useState("M15");
  const isRunning = status?.state === "RUNNING";
  const unrealizedPnL = positions.reduce((sum, p) => sum + (p.profit || 0), 0);

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="col-span-2 h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Dashboard" subtitle="Real-time trading overview">
        {tick && (
          <div className="glass glass-border rounded-full px-4 py-2 flex items-center gap-3">
            <span className="text-xs text-muted-foreground">XAUUSD</span>
            <span className="text-sm font-mono font-semibold text-primary">
              {tick.bid.toFixed(2)}
            </span>
            <span className="text-[10px] text-muted-foreground">/</span>
            <span className="text-sm font-mono text-muted-foreground">
              {tick.ask.toFixed(2)}
            </span>
            <span className="text-[10px] text-muted-foreground">
              spd: {tick.spread.toFixed(1)}
            </span>
          </div>
        )}
        {status?.paper_trade && (
          <Badge variant="outline" className="border-amber-400 text-amber-400 text-[10px]">
            PAPER
          </Badge>
        )}
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <Wifi className="size-3.5 text-green-400" />
          ) : (
            <WifiOff className="size-3.5 text-red-400" />
          )}
          <span className="text-xs text-muted-foreground">
            {isConnected ? "Live" : "Offline"}
          </span>
        </div>
      </PageHeader>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Wallet} label="Balance" value={account ? `$${account.balance.toLocaleString("en", { minimumFractionDigits: 2 })}` : "—"} variant="gold" />
        <StatCard
          icon={TrendingUp}
          label="Unrealized P&L"
          value={`${unrealizedPnL >= 0 ? "+" : ""}$${unrealizedPnL.toFixed(2)}`}
          variant={unrealizedPnL >= 0 ? "success" : "danger"}
        />
        <StatCard icon={Layers} label="Open Positions" value={positions.length} variant="default" />
        <StatCard
          icon={Activity}
          label="Bot Status"
          value={status?.state || "UNKNOWN"}
          variant={isRunning ? "success" : "warning"}
        />
      </div>

      {/* Price Chart + Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2 bg-card border-border border-t-2 border-t-primary">
          <CardHeader>
            <CardTitle className="text-sm flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span>{status?.symbol || "GOLD"}</span>
                {sentiment && (
                  <SentimentBadge label={sentiment.label} score={sentiment.score} size="sm" />
                )}
              </div>
              <div className="flex gap-0.5 bg-muted/50 rounded-md p-0.5">
                {["M1", "M5", "M15", "H1", "H4", "D1"].map((tf) => (
                  <button
                    key={tf}
                    type="button"
                    onClick={() => setChartTimeframe(tf)}
                    className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
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
          <CardContent className="h-64">
            <PriceChart
              symbol={status?.symbol || "GOLD"}
              timeframe={chartTimeframe}
              tick={tick}
            />
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm">Controls</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <Button
                onClick={handleStart}
                disabled={isRunning}
                className="flex-1 gold-gradient text-gold-foreground font-semibold hover:opacity-90"
              >
                <Play className="size-4 mr-1.5" />
                Start
              </Button>
              <Button
                onClick={handleStop}
                disabled={!isRunning}
                variant="secondary"
                className="flex-1"
              >
                <Square className="size-3.5 mr-1.5" />
                Stop
              </Button>
            </div>
            <Button
              onClick={handleEmergencyStop}
              variant="destructive"
              className="w-full"
            >
              <ShieldAlert className="size-4 mr-1.5" />
              Emergency Stop
            </Button>

            <Separator />

            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Paper Trade</span>
              <Switch
                checked={status?.paper_trade ?? false}
                onCheckedChange={async (v) => { await updateSettings({ paper_trade: v }); fetchData(); }}
              />
            </div>
            {status?.paper_trade && (
              <p className="text-[10px] text-amber-400 bg-amber-400/10 rounded px-2 py-1">
                Paper mode — no real orders sent to MT5
              </p>
            )}

            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">AI Filter</span>
              <Switch
                checked={status?.use_ai_filter ?? true}
                onCheckedChange={handleAIFilterToggle}
              />
            </div>

            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>Strategy</span>
                <span className="text-foreground font-medium">{status?.strategy || "—"}</span>
              </div>
              <div className="flex justify-between">
                <span>Symbol</span>
                <span className="text-foreground font-medium">{status?.symbol || "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Timeframe</span>
                <Select
                  value={status?.timeframe || "M15"}
                  onValueChange={async (v) => { if (v) { await updateSettings({ timeframe: v }); fetchData(); } }}
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
      </div>

      {/* News + Positions + Events */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm">News Feed</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-64">
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
                  <p className="text-sm text-muted-foreground text-center py-8">
                    No recent news
                  </p>
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm">Open Positions</CardTitle>
          </CardHeader>
          <CardContent>
            {positions.length > 0 ? (
              <ScrollArea className="h-64">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <TableHead className="text-muted-foreground">Type</TableHead>
                      <TableHead className="text-right text-muted-foreground">Lots</TableHead>
                      <TableHead className="text-right text-muted-foreground">Entry</TableHead>
                      <TableHead className="text-right text-muted-foreground">SL</TableHead>
                      <TableHead className="text-right text-muted-foreground">TP</TableHead>
                      <TableHead className="text-right text-muted-foreground">P&L</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {positions.map((p) => (
                      <TableRow key={p.ticket} className="border-border/50">
                        <TableCell
                          className={`font-medium ${p.type === "BUY" ? "text-green-400" : "text-red-400"}`}
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
                          className={`text-right font-mono font-medium ${p.profit >= 0 ? "text-green-400" : "text-red-400"}`}
                        >
                          {p.profit >= 0 ? "+" : ""}
                          {p.profit.toFixed(2)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                No open positions
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm">Events</CardTitle>
          </CardHeader>
          <CardContent>
            <EventFeed events={events} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
