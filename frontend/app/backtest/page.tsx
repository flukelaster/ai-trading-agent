"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Play,
  BarChart3,
  TrendingUp,
  DollarSign,
  Target,
  AlertTriangle,
  Search,
  Settings2,
  Loader2,
  FlaskConical,
  Zap,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import {
  runBacktest,
  runOptimize,
  getCurrentStrategy,
  getDataStatus,
  getSymbols,
} from "@/lib/api";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function BacktestPage() {
  const [strategy, setStrategy] = useState("ema_crossover");
  const [symbol, setSymbol] = useState("GOLD");
  const [count, setCount] = useState(5000);
  const [timeframe, setTimeframe] = useState("M15");
  const [balance, setBalance] = useState(10000);
  const [source, setSource] = useState("mt5");
  const [fromDate, setFromDate] = useState("2025-04-01");
  const [toDate, setToDate] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasDbData, setHasDbData] = useState(false);
  const [availableSymbols, setAvailableSymbols] = useState<
    { symbol: string; display_name: string }[]
  >([]);

  const [optResult, setOptResult] = useState<Record<string, unknown> | null>(
    null
  );
  const [optimizing, setOptimizing] = useState(false);
  const [fastPeriods, setFastPeriods] = useState("10,15,20,25,30");
  const [slowPeriods, setSlowPeriods] = useState("40,50,60,80,100");

  useEffect(() => {
    getCurrentStrategy()
      .then((res) => {
        if (res.data?.name) setStrategy(res.data.name);
      })
      .catch(() => {});
    getDataStatus()
      .then((res) => {
        if (Array.isArray(res.data) && res.data.length > 0) setHasDbData(true);
      })
      .catch(() => {});
    getSymbols()
      .then((res) => {
        const syms = res.data?.symbols || res.data;
        if (Array.isArray(syms) && syms.length > 0)
          setAvailableSymbols(syms);
      })
      .catch(() => {});
  }, []);

  const handleRun = async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {
        strategy,
        symbol,
        timeframe,
        initial_balance: balance,
        source,
      };
      if (source === "db") {
        params.from_date = fromDate;
        params.to_date = toDate;
      } else {
        params.count = count;
      }
      const res = await runBacktest(
        params as Parameters<typeof runBacktest>[0]
      );
      setResult(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptResult(null);
    try {
      const parseList = (s: string) =>
        s
          .split(",")
          .map(Number)
          .filter((n) => !isNaN(n));
      const grid: Record<string, number[]> = {
        fast_period: parseList(fastPeriods),
        slow_period: parseList(slowPeriods),
      };
      const params: Record<string, unknown> = {
        strategy,
        symbol,
        param_grid: grid,
        timeframe,
        initial_balance: balance,
        source,
      };
      if (source === "db") {
        params.from_date = fromDate;
        params.to_date = toDate;
      }
      const res = await runOptimize(
        params as Parameters<typeof runOptimize>[0]
      );
      setOptResult(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setOptimizing(false);
    }
  };

  const equityCurve = (result?.equity_curve as number[] || []).map(
    (v, i) => ({ bar: i, equity: v })
  );

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      <PageHeader
        title="Backtester"
        subtitle="Test strategies against historical data"
      />

      <Tabs defaultValue="backtest" className="space-y-5">
        <TabsList className="grid w-full grid-cols-2 max-w-xs">
          <TabsTrigger value="backtest">
            <FlaskConical className="size-3.5 mr-1.5" />
            Backtest
          </TabsTrigger>
          <TabsTrigger value="optimize">
            <Zap className="size-3.5 mr-1.5" />
            Optimizer
          </TabsTrigger>
        </TabsList>

        {/* ── Backtest Tab ─────────────────────────────────────── */}
        <TabsContent value="backtest" className="space-y-5 mt-0">
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <Settings2 className="size-4 text-muted-foreground" />
                <CardTitle className="text-sm font-bold">
                  Configuration
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Row 1: Strategy & Market */}
              <div className="flex flex-wrap gap-4">
                <div className="space-y-1.5 w-44">
                  <label className="text-xs text-muted-foreground font-medium">
                    Strategy
                  </label>
                  <Select
                    value={strategy}
                    onValueChange={(v) => v && setStrategy(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ema_crossover">
                        EMA Crossover
                      </SelectItem>
                      <SelectItem value="rsi_filter">RSI Filter</SelectItem>
                      <SelectItem value="breakout">Breakout</SelectItem>
                      <SelectItem value="ml_signal">ML Signal</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5 w-40">
                  <label className="text-xs text-muted-foreground font-medium">
                    Symbol
                  </label>
                  <Select
                    value={symbol}
                    onValueChange={(v) => v && setSymbol(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableSymbols.length > 0 ? (
                        availableSymbols.map((s) => (
                          <SelectItem key={s.symbol} value={s.symbol}>
                            {s.display_name}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="GOLD">Gold (XAUUSD)</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5 w-28">
                  <label className="text-xs text-muted-foreground font-medium">
                    Timeframe
                  </label>
                  <Select
                    value={timeframe}
                    onValueChange={(v) => v && setTimeframe(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="M5">M5</SelectItem>
                      <SelectItem value="M15">M15</SelectItem>
                      <SelectItem value="H1">H1</SelectItem>
                      <SelectItem value="H4">H4</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-border" />

              {/* Row 2: Data Source & Related Fields */}
              <div className="flex flex-wrap gap-4">
                <div className="space-y-1.5 w-36">
                  <label className="text-xs text-muted-foreground font-medium">
                    Data Source
                  </label>
                  <Select
                    value={source}
                    onValueChange={(v) => v && setSource(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="mt5">MT5 Live</SelectItem>
                      <SelectItem value="db" disabled={!hasDbData}>
                        DB Historical {!hasDbData && "(no data)"}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {source === "mt5" && (
                  <div className="space-y-1.5 w-32">
                    <label className="text-xs text-muted-foreground font-medium">
                      Bars
                    </label>
                    <Input
                      type="number"
                      value={count}
                      onChange={(e) =>
                        setCount(parseInt(e.target.value) || 1000)
                      }
                    />
                  </div>
                )}
                {source === "db" && (
                  <>
                    <div className="space-y-1.5 w-40">
                      <label className="text-xs text-muted-foreground font-medium">
                        From
                      </label>
                      <Input
                        type="date"
                        value={fromDate}
                        onChange={(e) => setFromDate(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1.5 w-40">
                      <label className="text-xs text-muted-foreground font-medium">
                        To
                      </label>
                      <Input
                        type="date"
                        value={toDate}
                        onChange={(e) => setToDate(e.target.value)}
                      />
                    </div>
                  </>
                )}
                <div className="space-y-1.5 w-36">
                  <label className="text-xs text-muted-foreground font-medium">
                    Initial Balance
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground font-medium">
                      $
                    </span>
                    <Input
                      type="number"
                      value={balance}
                      onChange={(e) =>
                        setBalance(parseFloat(e.target.value) || 10000)
                      }
                      className="pl-7"
                    />
                  </div>
                </div>
              </div>

              {/* Run Button */}
              <div className="flex justify-end pt-1">
                <Button
                  onClick={handleRun}
                  disabled={loading}
                  size="lg"
                  className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale min-w-[160px]"
                >
                  {loading ? (
                    <Loader2 className="size-4 mr-1.5 animate-spin" />
                  ) : (
                    <Play className="size-4 mr-1.5" />
                  )}
                  {loading ? "Running..." : "Run Backtest"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Results */}
          {result && !result.error && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
                <StatCard
                  icon={BarChart3}
                  label="Total Trades"
                  value={result.total_trades as number}
                />
                <StatCard
                  icon={TrendingUp}
                  label="Win Rate"
                  value={`${((result.win_rate as number) * 100).toFixed(1)}%`}
                  variant={
                    (result.win_rate as number) > 0.5 ? "success" : "danger"
                  }
                />
                <StatCard
                  icon={DollarSign}
                  label="Total Profit"
                  value={`$${(result.total_profit as number).toFixed(2)}`}
                  variant={
                    (result.total_profit as number) > 0 ? "success" : "danger"
                  }
                />
                <StatCard
                  icon={Target}
                  label="Profit Factor"
                  value={(result.profit_factor as number).toFixed(2)}
                  variant={
                    (result.profit_factor as number) > 1.5
                      ? "success"
                      : "warning"
                  }
                />
                <StatCard
                  icon={AlertTriangle}
                  label="Max Drawdown"
                  value={`${((result.max_drawdown as number) * 100).toFixed(1)}%`}
                  variant="danger"
                />
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-bold">
                    Equity Curve
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart data={equityCurve}>
                      <defs>
                        <linearGradient
                          id="greenGradient"
                          x1="0"
                          y1="0"
                          x2="0"
                          y2="1"
                        >
                          <stop
                            offset="0%"
                            stopColor="#9fe870"
                            stopOpacity={0.3}
                          />
                          <stop
                            offset="100%"
                            stopColor="#9fe870"
                            stopOpacity={0}
                          />
                        </linearGradient>
                      </defs>
                      <CartesianGrid
                        strokeDasharray="3 3"
                        className="stroke-border"
                      />
                      <XAxis
                        dataKey="bar"
                        className="fill-muted-foreground"
                        fontSize={10}
                      />
                      <YAxis
                        className="fill-muted-foreground"
                        fontSize={10}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "var(--popover)",
                          border: "1px solid var(--border)",
                          borderRadius: "12px",
                          color: "var(--foreground)",
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="equity"
                        stroke="#9fe870"
                        strokeWidth={2}
                        fill="url(#greenGradient)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Empty state */}
          {!result && !loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-14 rounded-2xl bg-muted flex items-center justify-center mb-4">
                <FlaskConical className="size-7 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold text-foreground">
                No backtest results yet
              </p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Configure your strategy and parameters above, then click Run
                Backtest to see results.
              </p>
            </div>
          )}

          {result?.error ? (
            <Card className="border-destructive/50 bg-destructive/5">
              <CardContent className="py-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-destructive shrink-0" />
                  <p className="text-sm text-destructive font-medium">
                    {String(result.error)}
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        {/* ── Optimizer Tab ────────────────────────────────────── */}
        <TabsContent value="optimize" className="space-y-5 mt-0">
          {/* Config */}
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <Settings2 className="size-4 text-muted-foreground" />
                <CardTitle className="text-sm font-bold">
                  Configuration
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Row 1: Strategy & Market */}
              <div className="flex flex-wrap gap-4">
                <div className="space-y-1.5 w-44">
                  <label className="text-xs text-muted-foreground font-medium">
                    Strategy
                  </label>
                  <Select
                    value={strategy}
                    onValueChange={(v) => v && setStrategy(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ema_crossover">
                        EMA Crossover
                      </SelectItem>
                      <SelectItem value="rsi_filter">RSI Filter</SelectItem>
                      <SelectItem value="breakout">Breakout</SelectItem>
                      <SelectItem value="ml_signal">ML Signal</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5 w-40">
                  <label className="text-xs text-muted-foreground font-medium">
                    Symbol
                  </label>
                  <Select
                    value={symbol}
                    onValueChange={(v) => v && setSymbol(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableSymbols.length > 0 ? (
                        availableSymbols.map((s) => (
                          <SelectItem key={s.symbol} value={s.symbol}>
                            {s.display_name}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="GOLD">Gold (XAUUSD)</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5 w-28">
                  <label className="text-xs text-muted-foreground font-medium">
                    Timeframe
                  </label>
                  <Select
                    value={timeframe}
                    onValueChange={(v) => v && setTimeframe(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="M5">M5</SelectItem>
                      <SelectItem value="M15">M15</SelectItem>
                      <SelectItem value="H1">H1</SelectItem>
                      <SelectItem value="H4">H4</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-border" />

              {/* Row 2: Data Source & Balance */}
              <div className="flex flex-wrap gap-4">
                <div className="space-y-1.5 w-36">
                  <label className="text-xs text-muted-foreground font-medium">
                    Data Source
                  </label>
                  <Select
                    value={source}
                    onValueChange={(v) => v && setSource(v)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="mt5">MT5 Live</SelectItem>
                      <SelectItem value="db" disabled={!hasDbData}>
                        DB Historical {!hasDbData && "(no data)"}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {source === "db" && (
                  <>
                    <div className="space-y-1.5 w-40">
                      <label className="text-xs text-muted-foreground font-medium">
                        From
                      </label>
                      <Input
                        type="date"
                        value={fromDate}
                        onChange={(e) => setFromDate(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1.5 w-40">
                      <label className="text-xs text-muted-foreground font-medium">
                        To
                      </label>
                      <Input
                        type="date"
                        value={toDate}
                        onChange={(e) => setToDate(e.target.value)}
                      />
                    </div>
                  </>
                )}
                <div className="space-y-1.5 w-36">
                  <label className="text-xs text-muted-foreground font-medium">
                    Initial Balance
                  </label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground font-medium">
                      $
                    </span>
                    <Input
                      type="number"
                      value={balance}
                      onChange={(e) =>
                        setBalance(parseFloat(e.target.value) || 10000)
                      }
                      className="pl-7"
                    />
                  </div>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-border" />

              {/* Row 3: Parameter Grid */}
              <div>
                <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider mb-3">
                  Parameter Grid
                </p>
                <div className="flex flex-wrap gap-4">
                  <div className="space-y-1.5 w-52">
                    <label className="text-xs text-muted-foreground font-medium">
                      Fast EMA Periods
                    </label>
                    <Input
                      value={fastPeriods}
                      onChange={(e) => setFastPeriods(e.target.value)}
                      placeholder="10,15,20,25,30"
                    />
                    <p className="text-[10px] text-muted-foreground/70">
                      Comma-separated values
                    </p>
                  </div>
                  <div className="space-y-1.5 w-52">
                    <label className="text-xs text-muted-foreground font-medium">
                      Slow EMA Periods
                    </label>
                    <Input
                      value={slowPeriods}
                      onChange={(e) => setSlowPeriods(e.target.value)}
                      placeholder="40,50,60,80,100"
                    />
                    <p className="text-[10px] text-muted-foreground/70">
                      Comma-separated values
                    </p>
                  </div>
                </div>
              </div>

              {/* Run Button */}
              <div className="flex justify-end pt-1">
                <Button
                  onClick={handleOptimize}
                  disabled={optimizing}
                  size="lg"
                  className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale min-w-[160px]"
                >
                  {optimizing ? (
                    <Loader2 className="size-4 mr-1.5 animate-spin" />
                  ) : (
                    <Search className="size-4 mr-1.5" />
                  )}
                  {optimizing ? "Optimizing..." : "Run Grid Search"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Results */}
          {optResult && !optResult.error && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
                <StatCard
                  icon={Target}
                  label="Best Score"
                  value={(optResult.best_score as number).toFixed(4)}
                  variant="gold"
                />
                <StatCard
                  icon={BarChart3}
                  label="Combinations Tested"
                  value={`${optResult.tested_combinations}/${optResult.total_combinations}`}
                />
                <StatCard
                  icon={TrendingUp}
                  label="Best Win Rate"
                  value={`${(((optResult.best_metrics as Record<string, number>)?.win_rate || 0) * 100).toFixed(1)}%`}
                  variant="success"
                />
                <StatCard
                  icon={DollarSign}
                  label="Best Profit"
                  value={`$${((optResult.best_metrics as Record<string, number>)?.total_profit || 0).toFixed(2)}`}
                  variant="success"
                />
              </div>

              {optResult.best_params != null && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-bold">
                      Best Parameters
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(
                        optResult.best_params as Record<string, number>
                      ).map(([k, v]) => (
                        <Badge
                          key={k}
                          variant="outline"
                          className="text-sm py-1.5 px-4 rounded-full font-semibold"
                        >
                          {k}: <strong className="ml-1">{v}</strong>
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {(optResult.top_10 as Record<string, unknown>[])?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-bold">
                      Top 10 Results
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto -mx-6 px-6">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-muted-foreground border-b border-border">
                            <th className="text-left py-2.5 px-3 font-semibold">
                              #
                            </th>
                            <th className="text-left py-2.5 px-3 font-semibold">
                              Parameters
                            </th>
                            <th className="text-right py-2.5 px-3 font-semibold">
                              Score
                            </th>
                            <th className="text-right py-2.5 px-3 font-semibold">
                              Win Rate
                            </th>
                            <th className="text-right py-2.5 px-3 font-semibold">
                              Profit
                            </th>
                            <th className="text-right py-2.5 px-3 font-semibold">
                              Sharpe
                            </th>
                            <th className="text-right py-2.5 px-3 font-semibold">
                              Trades
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {(
                            optResult.top_10 as Record<string, unknown>[]
                          ).map((r, i) => (
                            <tr
                              key={i}
                              className={`border-b border-border/50 transition-colors hover:bg-accent/30 ${i === 0 ? "bg-accent/50" : ""}`}
                            >
                              <td className="py-2 px-3 font-semibold">
                                {i === 0 ? (
                                  <Badge
                                    variant="outline"
                                    className="rounded-full text-[10px] px-1.5 py-0 border-primary/50 text-primary"
                                  >
                                    1
                                  </Badge>
                                ) : (
                                  i + 1
                                )}
                              </td>
                              <td className="py-2 px-3 font-mono text-muted-foreground">
                                {Object.entries(
                                  r.params as Record<string, number>
                                )
                                  .map(([k, v]) => `${k}=${v}`)
                                  .join(", ")}
                              </td>
                              <td className="text-right py-2 px-3 font-mono font-bold">
                                {(r.score as number).toFixed(4)}
                              </td>
                              <td className="text-right py-2 px-3">
                                {((r.win_rate as number) * 100).toFixed(1)}%
                              </td>
                              <td
                                className={`text-right py-2 px-3 font-semibold ${(r.total_profit as number) > 0 ? "text-success dark:text-green-400" : "text-destructive"}`}
                              >
                                $
                                {(r.total_profit as number).toFixed(2)}
                              </td>
                              <td className="text-right py-2 px-3">
                                {(r.sharpe_ratio as number).toFixed(3)}
                              </td>
                              <td className="text-right py-2 px-3">
                                {r.total_trades as number}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {/* Empty state */}
          {!optResult && !optimizing && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-14 rounded-2xl bg-muted flex items-center justify-center mb-4">
                <Zap className="size-7 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold text-foreground">
                No optimization results yet
              </p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Define your parameter grid above and run a grid search to find
                optimal strategy parameters.
              </p>
            </div>
          )}

          {optResult?.error ? (
            <Card className="border-destructive/50 bg-destructive/5">
              <CardContent className="py-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-destructive shrink-0" />
                  <p className="text-sm text-destructive font-medium">
                    {String(optResult.error)}
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
