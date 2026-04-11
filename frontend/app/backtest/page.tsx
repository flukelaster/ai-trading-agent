"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Play, BarChart3, TrendingUp, DollarSign, Target, AlertTriangle, Search, Database } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import { runBacktest, runOptimize, getCurrentStrategy, getDataStatus } from "@/lib/api";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

export default function BacktestPage() {
  const [strategy, setStrategy] = useState("ema_crossover");
  const [symbol, setSymbol] = useState("GOLD");
  const [count, setCount] = useState(5000);
  const [timeframe, setTimeframe] = useState("M15");
  const [balance, setBalance] = useState(10000);
  const [source, setSource] = useState("mt5");
  const [fromDate, setFromDate] = useState("2025-04-01");
  const [toDate, setToDate] = useState(new Date().toISOString().split("T")[0]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasDbData, setHasDbData] = useState(false);

  const [optResult, setOptResult] = useState<Record<string, unknown> | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [fastPeriods, setFastPeriods] = useState("10,15,20,25,30");
  const [slowPeriods, setSlowPeriods] = useState("40,50,60,80,100");

  useEffect(() => {
    getCurrentStrategy().then((res) => {
      if (res.data?.name) setStrategy(res.data.name);
    }).catch(() => {});
    getDataStatus().then((res) => {
      if (Array.isArray(res.data) && res.data.length > 0) setHasDbData(true);
    }).catch(() => {});
  }, []);

  const handleRun = async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { strategy, symbol, timeframe, initial_balance: balance, source };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      else { params.count = count; }
      const res = await runBacktest(params as Parameters<typeof runBacktest>[0]);
      setResult(res.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptResult(null);
    try {
      const parseList = (s: string) => s.split(",").map(Number).filter(n => !isNaN(n));
      const grid: Record<string, number[]> = { fast_period: parseList(fastPeriods), slow_period: parseList(slowPeriods) };
      const params: Record<string, unknown> = { strategy, symbol, param_grid: grid, timeframe, initial_balance: balance, source };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      const res = await runOptimize(params as Parameters<typeof runOptimize>[0]);
      setOptResult(res.data);
    } catch (e) { console.error(e); }
    finally { setOptimizing(false); }
  };

  const equityCurve = (result?.equity_curve as number[] || []).map((v, i) => ({ bar: i, equity: v }));

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Backtester" subtitle="Test strategies against historical data" />

      <Tabs defaultValue="backtest">
        <TabsList className="grid w-full grid-cols-2 max-w-sm">
          <TabsTrigger value="backtest">
            <Play className="size-3.5 mr-1.5" />Backtest
          </TabsTrigger>
          <TabsTrigger value="optimize">
            <Search className="size-3.5 mr-1.5" />Optimizer
          </TabsTrigger>
        </TabsList>

        {/* Shared Config */}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm font-bold">Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-4">
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium">Strategy</label>
                <Select value={strategy} onValueChange={(v) => v && setStrategy(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ema_crossover">EMA Crossover</SelectItem>
                    <SelectItem value="rsi_filter">RSI Filter</SelectItem>
                    <SelectItem value="breakout">Breakout</SelectItem>
                    <SelectItem value="ml_signal">ML Signal</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium">Symbol</label>
                <Select value={symbol} onValueChange={(v) => v && setSymbol(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="GOLD">Gold (XAUUSD)</SelectItem>
                    <SelectItem value="OILCash">WTI Oil</SelectItem>
                    <SelectItem value="BTCUSD">Bitcoin</SelectItem>
                    <SelectItem value="USDJPY">USD/JPY</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium">Timeframe</label>
                <Select value={timeframe} onValueChange={(v) => v && setTimeframe(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="M5">M5</SelectItem>
                    <SelectItem value="M15">M15</SelectItem>
                    <SelectItem value="H1">H1</SelectItem>
                    <SelectItem value="H4">H4</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium">Data Source</label>
                <Select value={source} onValueChange={(v) => v && setSource(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mt5">MT5 Live</SelectItem>
                    <SelectItem value="db" disabled={!hasDbData}>
                      DB Historical {!hasDbData && "(no data)"}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground font-medium">Initial Balance ($)</label>
                <Input type="number" value={balance} onChange={(e) => setBalance(parseFloat(e.target.value) || 10000)} />
              </div>
              {source === "db" && (
                <>
                  <div className="space-y-2">
                    <label className="text-xs text-muted-foreground font-medium">From Date</label>
                    <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs text-muted-foreground font-medium">To Date</label>
                    <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
                  </div>
                </>
              )}
              {source === "mt5" && (
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground font-medium">Bars</label>
                  <Input type="number" value={count} onChange={(e) => setCount(parseInt(e.target.value) || 1000)} />
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Backtest Tab */}
        <TabsContent value="backtest" className="space-y-4 mt-0">
          <Button onClick={handleRun} disabled={loading} className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale">
            <Play className="size-4 mr-1.5" />
            {loading ? "Running..." : "Run Backtest"}
          </Button>

          {result && !result.error && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
                <StatCard icon={BarChart3} label="Total Trades" value={result.total_trades as number} />
                <StatCard icon={TrendingUp} label="Win Rate" value={`${((result.win_rate as number) * 100).toFixed(1)}%`} variant={(result.win_rate as number) > 0.5 ? "success" : "danger"} />
                <StatCard icon={DollarSign} label="Total Profit" value={`$${(result.total_profit as number).toFixed(2)}`} variant={(result.total_profit as number) > 0 ? "success" : "danger"} />
                <StatCard icon={Target} label="Profit Factor" value={(result.profit_factor as number).toFixed(2)} variant={(result.profit_factor as number) > 1.5 ? "success" : "warning"} />
                <StatCard icon={AlertTriangle} label="Max Drawdown" value={`${((result.max_drawdown as number) * 100).toFixed(1)}%`} variant="danger" />
              </div>

              <Card>
                <CardHeader><CardTitle className="text-sm font-bold">Equity Curve</CardTitle></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart data={equityCurve}>
                      <defs>
                        <linearGradient id="greenGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#9fe870" stopOpacity={0.3} />
                          <stop offset="100%" stopColor="#9fe870" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                      <XAxis dataKey="bar" className="fill-muted-foreground" fontSize={10} />
                      <YAxis className="fill-muted-foreground" fontSize={10} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "var(--popover)",
                          border: "1px solid var(--border)",
                          borderRadius: "12px",
                          color: "var(--foreground)",
                        }}
                      />
                      <Area type="monotone" dataKey="equity" stroke="#9fe870" strokeWidth={2} fill="url(#greenGradient)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </>
          )}
          {result?.error ? <p className="text-sm text-destructive font-medium">{String(result.error)}</p> : null}
        </TabsContent>

        {/* Optimizer Tab */}
        <TabsContent value="optimize" className="space-y-4 mt-0">
          <Card>
            <CardHeader><CardTitle className="text-sm font-bold">Parameter Grid</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground font-medium">Fast EMA Periods (comma-separated)</label>
                  <Input value={fastPeriods} onChange={(e) => setFastPeriods(e.target.value)} placeholder="10,15,20,25,30" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground font-medium">Slow EMA Periods (comma-separated)</label>
                  <Input value={slowPeriods} onChange={(e) => setSlowPeriods(e.target.value)} placeholder="40,50,60,80,100" />
                </div>
              </div>
              <Button onClick={handleOptimize} disabled={optimizing} className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale">
                <Search className="size-4 mr-1.5" />
                {optimizing ? "Optimizing..." : "Run Grid Search"}
              </Button>
            </CardContent>
          </Card>

          {optResult && !optResult.error && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <StatCard icon={Target} label="Best Score" value={(optResult.best_score as number).toFixed(4)} variant="gold" />
                <StatCard icon={BarChart3} label="Tested" value={`${optResult.tested_combinations}/${optResult.total_combinations}`} />
                <StatCard icon={TrendingUp} label="Best Win Rate" value={`${(((optResult.best_metrics as Record<string, number>)?.win_rate || 0) * 100).toFixed(1)}%`} variant="success" />
                <StatCard icon={DollarSign} label="Best Profit" value={`$${((optResult.best_metrics as Record<string, number>)?.total_profit || 0).toFixed(2)}`} variant="success" />
              </div>

              {optResult.best_params && (
                <Card>
                  <CardHeader><CardTitle className="text-sm font-bold">Best Parameters</CardTitle></CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(optResult.best_params as Record<string, number>).map(([k, v]) => (
                        <Badge key={k} variant="outline" className="text-sm py-1 px-3 rounded-full font-semibold">
                          {k}: <strong className="ml-1">{v}</strong>
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {(optResult.top_10 as Record<string, unknown>[])?.length > 0 && (
                <Card>
                  <CardHeader><CardTitle className="text-sm font-bold">Top 10 Results</CardTitle></CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-muted-foreground border-b border-border">
                            <th className="text-left py-2 px-2 font-semibold">#</th>
                            <th className="text-left py-2 px-2 font-semibold">Params</th>
                            <th className="text-right py-2 px-2 font-semibold">Score</th>
                            <th className="text-right py-2 px-2 font-semibold">Win Rate</th>
                            <th className="text-right py-2 px-2 font-semibold">Profit</th>
                            <th className="text-right py-2 px-2 font-semibold">Sharpe</th>
                            <th className="text-right py-2 px-2 font-semibold">Trades</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(optResult.top_10 as Record<string, unknown>[]).map((r, i) => (
                            <tr key={i} className={`border-b border-border/50 ${i === 0 ? "bg-accent/50" : ""}`}>
                              <td className="py-1.5 px-2 font-semibold">{i + 1}</td>
                              <td className="py-1.5 px-2 font-mono">
                                {Object.entries(r.params as Record<string, number>).map(([k, v]) => `${k}=${v}`).join(", ")}
                              </td>
                              <td className="text-right py-1.5 px-2 font-mono font-bold">{(r.score as number).toFixed(4)}</td>
                              <td className="text-right py-1.5 px-2">{((r.win_rate as number) * 100).toFixed(1)}%</td>
                              <td className={`text-right py-1.5 px-2 font-semibold ${(r.total_profit as number) > 0 ? "text-success dark:text-green-400" : "text-destructive"}`}>
                                ${(r.total_profit as number).toFixed(2)}
                              </td>
                              <td className="text-right py-1.5 px-2">{(r.sharpe_ratio as number).toFixed(3)}</td>
                              <td className="text-right py-1.5 px-2">{r.total_trades as number}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
          {optResult?.error ? <p className="text-sm text-destructive font-medium">{String(optResult.error)}</p> : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
