"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Download, BarChart3, TrendingUp, DollarSign, Target, History } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import SentimentBadge from "@/components/ai/SentimentBadge";
import { getTradeHistory, getPerformance, getSymbols } from "@/lib/api";
import { showSuccess, showError } from "@/lib/toast";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { SymbolTabs } from "@/components/ui/symbol-tabs";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

type Trade = {
  id: number; ticket: number; symbol: string; type: string; lot: number;
  open_price: number; close_price: number | null; sl: number; tp: number;
  open_time: string; close_time: string | null; profit: number | null;
  strategy_name: string; ai_sentiment_label: string | null; ai_sentiment_score: number | null;
  trade_reason: string | null;
  pre_trade_snapshot: Record<string, unknown> | null;
  post_trade_analysis: { exit_reason: string; duration_hours: number | null; outcome: string; profit_usd: number; entry_regime: string; exit_regime: string | null; summary_th: string } | null;
};

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [performance, setPerformance] = useState<Record<string, unknown> | null>(null);
  const [days, setDays] = useState(30);
  const [symbolFilter, setSymbolFilter] = useState<string>("all");
  const [symbols, setSymbols] = useState<{symbol: string; display_name: string}[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSymbols().then((res) => {
      if (res.data?.symbols) {
        setSymbols(res.data.symbols);
      }
    }).catch(() => {});
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const sym = symbolFilter === "all" ? undefined : symbolFilter;
    try {
      const [tradeRes, perfRes] = await Promise.all([
        getTradeHistory({ days, symbol: sym, limit: 200 }), getPerformance(days, sym),
      ]);
      setTrades(tradeRes.data.trades || []);
      setPerformance(perfRes.data);
    } catch (e) { console.error(e); showError("Failed to load trade history"); } finally { setLoading(false); }
  }, [days, symbolFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleExportCSV = () => {
    const headers = "Ticket,Symbol,Type,Lot,Open Price,Close Price,SL,TP,Profit,Strategy,Sentiment\n";
    const rows = trades
      .map((t) =>
        `${t.ticket},${t.symbol},${t.type},${t.lot},${t.open_price},${t.close_price ?? ""},${t.sl},${t.tp},${t.profit ?? ""},${t.strategy_name},${t.ai_sentiment_label ?? ""}`
      )
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `trades_${days}d.csv`;
    a.click();
    showSuccess("CSV exported", `${trades.length} trades exported`);
  };

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="Trade History" subtitle="Review past trades and performance">
        <SymbolTabs
          symbols={symbols}
          active={symbolFilter}
          onSelect={setSymbolFilter}
          showAll
        />
        <div className="flex gap-1 border border-border rounded-2xl p-1 bg-card">
          {[7, 30, 90].map((d) => (
            <Button
              key={d}
              variant={days === d ? "default" : "ghost"}
              size="sm"
              onClick={() => setDays(d)}
              className={`rounded-xl ${days === d ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
            >
              {d}d
            </Button>
          ))}
        </div>
      </PageHeader>

      <PageInstructions

        items={[
          "View all closed trades with P&L breakdown. Switch between table and equity chart views.",
          "Trades with AI sentiment data show the label and confidence score. Use the download button to export CSV.",
        ]}
      />

      <Tabs defaultValue="trades">
        <TabsList>
          <TabsTrigger value="trades">Trades</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
        </TabsList>

        <TabsContent value="trades" className="mt-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-bold">
                Trades <span className="text-muted-foreground font-medium">({trades.length})</span>
              </CardTitle>
              <Button variant="outline" size="sm" onClick={handleExportCSV} className="rounded-full">
                <Download className="size-3.5 mr-1.5" />
                Export CSV
              </Button>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3 py-4">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : trades.length > 0 ? (
                <>
                  {/* Detect which optional columns have data */}
                  {(() => {
                    const hasReason = trades.some((t) => t.trade_reason);
                    const hasSentiment = trades.some((t) => t.ai_sentiment_label);
                    const total = trades.reduce((s, t) => s + (t.profit ?? 0), 0);
                    const wins = trades.filter((t) => (t.profit ?? 0) > 0).length;
                    const losses = trades.length - wins;

                    return (
                      <>
                        <ScrollArea className="h-[400px] sm:h-[500px]">
                          <div className="overflow-x-auto">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-xs">Time</TableHead>
                                <TableHead className="text-xs">Symbol</TableHead>
                                <TableHead className="text-xs">Type</TableHead>
                                <TableHead className="text-xs text-right">Lot</TableHead>
                                <TableHead className="text-xs text-right">Open</TableHead>
                                <TableHead className="text-xs text-right">Close</TableHead>
                                <TableHead className="text-xs text-right">P&L</TableHead>
                                <TableHead className="text-xs">Strategy</TableHead>
                                {hasReason && <TableHead className="text-xs">Reason</TableHead>}
                                {hasSentiment && <TableHead className="text-xs text-center">AI</TableHead>}
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {trades.map((t) => (
                                <TableRow key={t.id} className="hover:bg-muted/30 transition-colors">
                                  <TableCell className="text-muted-foreground text-xs">
                                    {new Date(t.open_time).toLocaleDateString("en-GB", { timeZone: "Asia/Bangkok" })}
                                  </TableCell>
                                  <TableCell className="text-xs font-medium">{t.symbol}</TableCell>
                                  <TableCell className={`text-xs font-semibold ${t.type === "BUY" ? "text-success dark:text-green-400" : "text-destructive"}`}>
                                    {t.type}
                                  </TableCell>
                                  <TableCell className="text-right text-xs font-mono">{t.lot}</TableCell>
                                  <TableCell className="text-right text-xs font-mono">{t.open_price.toFixed(2)}</TableCell>
                                  <TableCell className="text-right text-xs font-mono">{t.close_price?.toFixed(2) ?? "—"}</TableCell>
                                  <TableCell className={`text-right text-xs font-mono font-semibold ${(t.profit ?? 0) >= 0 ? "text-success dark:text-green-400" : "text-destructive"}`}>
                                    {t.profit !== null ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}` : "—"}
                                  </TableCell>
                                  <TableCell className="text-xs text-muted-foreground">{t.strategy_name}</TableCell>
                                  {hasReason && (
                                    <TableCell className="text-xs text-muted-foreground max-w-[180px] truncate" title={t.trade_reason || undefined}>
                                      {t.trade_reason || "—"}
                                    </TableCell>
                                  )}
                                  {hasSentiment && (
                                    <TableCell className="text-center">
                                      {t.ai_sentiment_label ? (
                                        <SentimentBadge label={t.ai_sentiment_label} score={t.ai_sentiment_score || 0} size="sm" />
                                      ) : null}
                                    </TableCell>
                                  )}
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                          </div>
                        </ScrollArea>

                        {/* Summary bar at bottom */}
                        <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/20 rounded-b-xl">
                          <span className="text-xs text-muted-foreground font-medium">
                            {trades.length} trades · {wins}W / {losses}L · Win rate {trades.length > 0 ? ((wins / trades.length) * 100).toFixed(0) : 0}%
                          </span>
                          <span className={`text-sm font-bold font-mono ${total >= 0 ? "text-success dark:text-green-400" : "text-destructive"}`}>
                            {total >= 0 ? "+" : ""}${Math.abs(total).toFixed(2)}
                          </span>
                        </div>
                      </>
                    );
                  })()}
                </>
              ) : (
                <EmptyState icon={History} heading="No trades found" description="Start trading to see your history here" action={{ label: "Go to Dashboard", href: "/dashboard" }} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="performance" className="mt-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard icon={BarChart3} label="Total Trades" value={(performance?.total_trades as number) ?? 0} />
            <StatCard icon={TrendingUp} label="Win Rate"
              value={`${(((performance?.win_rate as number) ?? 0) * 100).toFixed(1)}%`}
              variant={((performance?.win_rate as number) ?? 0) > 0.5 ? "success" : "danger"} />
            <StatCard icon={DollarSign} label="Total Profit"
              value={`$${((performance?.total_profit as number) ?? 0).toFixed(2)}`}
              variant={((performance?.total_profit as number) ?? 0) > 0 ? "success" : "danger"} />
            <StatCard icon={Target} label="Avg Profit"
              value={`$${((performance?.avg_profit as number) ?? 0).toFixed(2)}`}
              variant={((performance?.avg_profit as number) ?? 0) > 0 ? "success" : "danger"} />
          </div>

          {trades.filter((t) => t.profit !== null).length > 0 && (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="text-sm font-bold">Cumulative P&L</CardTitle>
              </CardHeader>
              <CardContent>
                <ErrorBoundary>
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart
                    data={trades
                      .filter((t) => t.profit !== null && t.close_time)
                      .sort((a, b) => new Date(a.close_time!).getTime() - new Date(b.close_time!).getTime())
                      .reduce<{ date: string; pnl: number }[]>((acc, t) => {
                        const prev = acc.length > 0 ? acc[acc.length - 1].pnl : 0;
                        acc.push({ date: new Date(t.close_time!).toLocaleDateString("en-GB", { timeZone: "Asia/Bangkok" }), pnl: prev + (t.profit ?? 0) });
                        return acc;
                      }, [])}
                  >
                    <defs>
                      <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#9fe870" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#9fe870" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="date" className="fill-muted-foreground" fontSize={10} />
                    <YAxis className="fill-muted-foreground" fontSize={10} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "var(--popover)",
                        border: "1px solid var(--border)",
                        borderRadius: "12px",
                        color: "var(--foreground)",
                      }}
                      formatter={(value) => [`$${Number(value).toFixed(2)}`, "P&L"]}
                    />
                    <ReferenceLine y={0} className="stroke-muted-foreground" strokeDasharray="3 3" strokeOpacity={0.5} />
                    <Area type="monotone" dataKey="pnl" stroke="#9fe870" strokeWidth={2} fill="url(#pnlGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
                </ErrorBoundary>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
