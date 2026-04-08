"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Download, BarChart3, TrendingUp, DollarSign, Target } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import SentimentBadge from "@/components/ai/SentimentBadge";
import { getTradeHistory, getPerformance } from "@/lib/api";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

type Trade = {
  id: number; ticket: number; symbol: string; type: string; lot: number;
  open_price: number; close_price: number | null; sl: number; tp: number;
  open_time: string; close_time: string | null; profit: number | null;
  strategy_name: string; ai_sentiment_label: string | null; ai_sentiment_score: number | null;
};

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [performance, setPerformance] = useState<Record<string, unknown> | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [tradeRes, perfRes] = await Promise.all([
        getTradeHistory({ days, limit: 200 }),
        getPerformance(days),
      ]);
      setTrades(tradeRes.data.trades || []);
      setPerformance(perfRes.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleExportCSV = () => {
    const headers = "Ticket,Type,Lot,Open Price,Close Price,SL,TP,Profit,Strategy,Sentiment\n";
    const rows = trades
      .map((t) =>
        `${t.ticket},${t.type},${t.lot},${t.open_price},${t.close_price ?? ""},${t.sl},${t.tp},${t.profit ?? ""},${t.strategy_name},${t.ai_sentiment_label ?? ""}`
      )
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `trades_${days}d.csv`;
    a.click();
  };

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Trade History" subtitle="Review past trades and performance">
        <div className="flex gap-1 glass glass-border rounded-lg p-1">
          {[7, 30, 90].map((d) => (
            <Button
              key={d}
              variant={days === d ? "default" : "ghost"}
              size="sm"
              onClick={() => setDays(d)}
              className={days === d ? "gold-gradient text-gold-foreground" : "text-muted-foreground"}
            >
              {d}d
            </Button>
          ))}
        </div>
      </PageHeader>

      <Tabs defaultValue="trades">
        <TabsList>
          <TabsTrigger value="trades">Trades</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
        </TabsList>

        <TabsContent value="trades" className="mt-4">
          <Card className="bg-card border-border">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-sm">
                Trades <span className="text-muted-foreground font-normal">({trades.length})</span>
              </CardTitle>
              <Button variant="outline" size="sm" onClick={handleExportCSV}>
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
                <ScrollArea className="h-[500px]">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-border hover:bg-transparent">
                        <TableHead className="text-muted-foreground">Time</TableHead>
                        <TableHead className="text-muted-foreground">Type</TableHead>
                        <TableHead className="text-right text-muted-foreground">Lot</TableHead>
                        <TableHead className="text-right text-muted-foreground">Open</TableHead>
                        <TableHead className="text-right text-muted-foreground">Close</TableHead>
                        <TableHead className="text-right text-muted-foreground">P&L</TableHead>
                        <TableHead className="text-muted-foreground">Strategy</TableHead>
                        <TableHead className="text-center text-muted-foreground">AI</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {trades.map((t) => (
                        <TableRow key={t.id} className="border-border/50">
                          <TableCell className="text-muted-foreground text-xs">
                            {new Date(t.open_time).toLocaleDateString()}
                          </TableCell>
                          <TableCell
                            className={`font-medium ${t.type === "BUY" ? "text-green-400" : "text-red-400"}`}
                          >
                            {t.type}
                          </TableCell>
                          <TableCell className="text-right font-mono">{t.lot}</TableCell>
                          <TableCell className="text-right font-mono">{t.open_price.toFixed(2)}</TableCell>
                          <TableCell className="text-right font-mono">
                            {t.close_price?.toFixed(2) ?? "—"}
                          </TableCell>
                          <TableCell
                            className={`text-right font-mono font-medium ${(t.profit ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}
                          >
                            {t.profit !== null
                              ? `${t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}`
                              : "—"}
                          </TableCell>
                          <TableCell className="text-muted-foreground">{t.strategy_name}</TableCell>
                          <TableCell className="text-center">
                            {t.ai_sentiment_label ? (
                              <SentimentBadge
                                label={t.ai_sentiment_label}
                                score={t.ai_sentiment_score || 0}
                                size="sm"
                              />
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </ScrollArea>
              ) : (
                <p className="text-muted-foreground text-center py-12">No trades found</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="performance" className="mt-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={BarChart3}
              label="Total Trades"
              value={(performance?.total_trades as number) ?? 0}
            />
            <StatCard
              icon={TrendingUp}
              label="Win Rate"
              value={`${(((performance?.win_rate as number) ?? 0) * 100).toFixed(1)}%`}
              variant={((performance?.win_rate as number) ?? 0) > 0.5 ? "success" : "danger"}
            />
            <StatCard
              icon={DollarSign}
              label="Total Profit"
              value={`$${((performance?.total_profit as number) ?? 0).toFixed(2)}`}
              variant={((performance?.total_profit as number) ?? 0) > 0 ? "success" : "danger"}
            />
            <StatCard
              icon={Target}
              label="Avg Profit"
              value={`$${((performance?.avg_profit as number) ?? 0).toFixed(2)}`}
              variant={((performance?.avg_profit as number) ?? 0) > 0 ? "success" : "danger"}
            />
          </div>

          {/* Cumulative P&L Chart */}
          {trades.filter((t) => t.profit !== null).length > 0 && (
            <Card className="bg-card border-border mt-4">
              <CardHeader>
                <CardTitle className="text-sm">Cumulative P&L</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart
                    data={trades
                      .filter((t) => t.profit !== null && t.close_time)
                      .sort((a, b) => new Date(a.close_time!).getTime() - new Date(b.close_time!).getTime())
                      .reduce<{ date: string; pnl: number }[]>((acc, t) => {
                        const prev = acc.length > 0 ? acc[acc.length - 1].pnl : 0;
                        acc.push({
                          date: new Date(t.close_time!).toLocaleDateString(),
                          pnl: prev + (t.profit ?? 0),
                        });
                        return acc;
                      }, [])}
                  >
                    <defs>
                      <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#d4af37" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#d4af37" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" stroke="#8a8fa0" fontSize={10} />
                    <YAxis stroke="#8a8fa0" fontSize={10} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "rgba(20,20,30,0.9)",
                        border: "1px solid rgba(255,255,255,0.08)",
                        borderRadius: "8px",
                      }}
                      labelStyle={{ color: "#8a8fa0" }}
                      formatter={(value) => [`$${Number(value).toFixed(2)}`, "P&L"]}
                    />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeDasharray="3 3" />
                    <Area
                      type="monotone"
                      dataKey="pnl"
                      stroke="#d4af37"
                      strokeWidth={2}
                      fill="url(#pnlGradient)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
