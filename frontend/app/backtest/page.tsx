"use client";

import { useState, useEffect, useMemo } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Play, BarChart3, TrendingUp, DollarSign, Target,
  AlertTriangle, Search, Loader2, FlaskConical, Zap,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import {
  runBacktest, runOptimize, getCurrentStrategy, getDataStatus, getSymbols,
} from "@/lib/api";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

// ─── Constants ────────────────────────────────────────────────────

const STRATEGIES = [
  { value: "ema_crossover", label: "EMA Crossover" },
  { value: "rsi_filter", label: "RSI Filter" },
  { value: "breakout", label: "Breakout" },
  { value: "mean_reversion", label: "Mean Reversion" },
  { value: "ml_signal", label: "ML Signal" },
];

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"];

interface ParamDef {
  key: string;
  label: string;
  defaults: number[];
}

const STRATEGY_PARAMS: Record<string, ParamDef[]> = {
  ema_crossover: [
    { key: "fast_period", label: "Fast EMA Period", defaults: [10, 15, 20, 25, 30] },
    { key: "slow_period", label: "Slow EMA Period", defaults: [40, 50, 60, 80, 100] },
  ],
  rsi_filter: [
    { key: "ema_fast", label: "EMA Fast", defaults: [10, 15, 20, 25] },
    { key: "ema_slow", label: "EMA Slow", defaults: [40, 50, 60] },
    { key: "rsi_period", label: "RSI Period", defaults: [10, 14, 20] },
    { key: "rsi_overbought", label: "RSI Overbought", defaults: [65, 70, 75, 80] },
    { key: "rsi_oversold", label: "RSI Oversold", defaults: [20, 25, 30, 35] },
  ],
  breakout: [
    { key: "lookback", label: "Lookback Period", defaults: [10, 15, 20, 30] },
    { key: "atr_period", label: "ATR Period", defaults: [10, 14, 20] },
    { key: "atr_threshold", label: "ATR Threshold", defaults: [0.3, 0.5, 0.8, 1.0] },
  ],
  mean_reversion: [
    { key: "bb_period", label: "BB Period", defaults: [15, 20, 25] },
    { key: "bb_std", label: "BB Std Dev", defaults: [1.5, 2.0, 2.5] },
    { key: "rsi_period", label: "RSI Period", defaults: [10, 14, 20] },
    { key: "rsi_overbought", label: "RSI Overbought", defaults: [65, 70, 75] },
    { key: "rsi_oversold", label: "RSI Oversold", defaults: [25, 30, 35] },
    { key: "min_bandwidth", label: "Min Bandwidth", defaults: [0.003, 0.005, 0.01] },
  ],
  ml_signal: [],
};

function buildDefaultGridInputs(strat: string): Record<string, string> {
  const params = STRATEGY_PARAMS[strat] || [];
  const result: Record<string, string> = {};
  for (const p of params) {
    result[p.key] = p.defaults.join(",");
  }
  return result;
}

// ─── Page ─────────────────────────────────────────────────────────

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
  const [availableSymbols, setAvailableSymbols] = useState<{ symbol: string; display_name: string }[]>([]);

  const [optResult, setOptResult] = useState<Record<string, unknown> | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [paramGridInputs, setParamGridInputs] = useState<Record<string, string>>(
    () => buildDefaultGridInputs("ema_crossover")
  );

  const currentParams = useMemo(() => STRATEGY_PARAMS[strategy] || [], [strategy]);

  // Reset param grid when strategy changes
  useEffect(() => {
    setParamGridInputs(buildDefaultGridInputs(strategy));
  }, [strategy]);

  useEffect(() => {
    getCurrentStrategy().then((res) => { if (res.data?.name) setStrategy(res.data.name); }).catch(() => {});
    getDataStatus().then((res) => { if (Array.isArray(res.data) && res.data.length > 0) setHasDbData(true); }).catch(() => {});
    getSymbols().then((res) => { const syms = res.data?.symbols || res.data; if (Array.isArray(syms) && syms.length > 0) setAvailableSymbols(syms); }).catch(() => {});
  }, []);

  const handleRun = async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { strategy, symbol, timeframe, initial_balance: balance, source };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      else { params.count = count; }
      const res = await runBacktest(params as Parameters<typeof runBacktest>[0]);
      setResult(res.data);
    } catch { /* handled */ } finally { setLoading(false); }
  };

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptResult(null);
    try {
      const parseList = (s: string) => s.split(",").map(Number).filter((n) => !isNaN(n));
      const paramGrid: Record<string, number[]> = {};
      for (const [key, value] of Object.entries(paramGridInputs)) {
        const parsed = parseList(value);
        if (parsed.length > 0) paramGrid[key] = parsed;
      }
      const params: Record<string, unknown> = {
        strategy, symbol, timeframe, initial_balance: balance, source,
        param_grid: paramGrid,
      };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      const res = await runOptimize(params as Parameters<typeof runOptimize>[0]);
      setOptResult(res.data);
    } catch { /* handled */ } finally { setOptimizing(false); }
  };

  const equityCurve = (result?.equity_curve as number[] || []).map((v, i) => ({ bar: i, equity: v }));

  // ─── Shared Config Form ─────────────────────────────────────────
  const configForm = (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4">
      {/* Row 1: Strategy + Symbol + Timeframe */}
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Strategy</label>
          <Select value={strategy} onValueChange={(v) => v && setStrategy(v)}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {STRATEGIES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Symbol</label>
          <Select value={symbol} onValueChange={(v) => v && setSymbol(v)}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {availableSymbols.length > 0
                ? availableSymbols.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.display_name}</SelectItem>)
                : <SelectItem value="GOLD">Gold (XAUUSD)</SelectItem>}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Timeframe</label>
          <Select value={timeframe} onValueChange={(v) => v && setTimeframe(v)}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {TIMEFRAMES.map((tf) => <SelectItem key={tf} value={tf}>{tf}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Row 2: Source + Date/Bars + Balance */}
      <div className="grid grid-cols-3 gap-3 items-end">
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Data Source</label>
          <Select value={source} onValueChange={(v) => v && setSource(v)}>
            <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="mt5">MT5 Live</SelectItem>
              <SelectItem value="db" disabled={!hasDbData}>DB Historical{!hasDbData && " (no data)"}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {source === "mt5" ? (
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground font-medium">Bars</label>
            <Input type="number" value={count} onChange={(e) => setCount(parseInt(e.target.value) || 1000)} className="text-sm" />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">From</label>
              <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">To</label>
              <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="text-sm" />
            </div>
          </div>
        )}
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Initial Balance</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">$</span>
            <Input type="number" value={balance} onChange={(e) => setBalance(parseFloat(e.target.value) || 10000)} className="pl-7 text-sm" />
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader title="Backtester" subtitle="Test strategies against historical data" />

      <PageInstructions
        pageId="backtest"
        items={[
          "Select a strategy, symbol, and timeframe. Use MT5 for live data or DB for historical (requires data collection from ML page).",
          "Backtest tab runs a single test. Optimizer tab searches parameter combinations to find the best settings.",
          "ML Signal strategy requires a trained model — train one on the ML page first.",
        ]}
      />

      <Tabs defaultValue="backtest" className="space-y-5">
        <TabsList className="grid w-full grid-cols-2 max-w-xs">
          <TabsTrigger value="backtest"><FlaskConical className="size-3.5 mr-1.5" />Backtest</TabsTrigger>
          <TabsTrigger value="optimize"><Zap className="size-3.5 mr-1.5" />Optimizer</TabsTrigger>
        </TabsList>

        {/* ── Backtest Tab ─────────────────────────────────────── */}
        <TabsContent value="backtest" className="space-y-4 mt-0">
          {configForm}

          <div className="flex justify-end">
            <Button onClick={handleRun} disabled={loading} className="rounded-lg font-medium min-w-35">
              {loading ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Play className="size-4 mr-1.5" />}
              {loading ? "Running..." : "Run Backtest"}
            </Button>
          </div>

          {result && !result.error && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                <StatCard icon={BarChart3} label="Total Trades" value={result.total_trades as number} />
                <StatCard icon={TrendingUp} label="Win Rate" value={`${((result.win_rate as number) * 100).toFixed(1)}%`} variant={(result.win_rate as number) > 0.5 ? "success" : "danger"} />
                <StatCard icon={DollarSign} label="Total Profit" value={`$${(result.total_profit as number).toFixed(2)}`} variant={(result.total_profit as number) > 0 ? "success" : "danger"} />
                <StatCard icon={Target} label="Profit Factor" value={(result.profit_factor as number).toFixed(2)} variant={(result.profit_factor as number) > 1.5 ? "success" : "warning"} />
                <StatCard icon={AlertTriangle} label="Max Drawdown" value={`${((result.max_drawdown as number) * 100).toFixed(1)}%`} variant="danger" />
              </div>

              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Equity Curve</h3>
                <ResponsiveContainer width="100%" height={280}>
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
                    <Tooltip contentStyle={{ backgroundColor: "var(--popover)", border: "1px solid var(--border)", borderRadius: "12px", color: "var(--foreground)" }} />
                    <Area type="monotone" dataKey="equity" stroke="#9fe870" strokeWidth={2} fill="url(#greenGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {!result && !loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-12 rounded-xl bg-muted flex items-center justify-center mb-3">
                <FlaskConical className="size-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold">No backtest results yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">Configure your strategy above and click Run Backtest.</p>
            </div>
          )}

          {result && "error" in result && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 flex items-center gap-2">
              <AlertTriangle className="size-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400">{String(result.error)}</p>
            </div>
          )}
        </TabsContent>

        {/* ── Optimizer Tab ────────────────────────────────────── */}
        <TabsContent value="optimize" className="space-y-4 mt-0">
          {configForm}

          {/* Dynamic Parameter Grid */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">Parameter Grid</h3>
            {currentParams.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {currentParams.map((p) => (
                  <div key={p.key} className="space-y-1">
                    <label className="text-[11px] text-muted-foreground font-medium">{p.label}</label>
                    <Input
                      value={paramGridInputs[p.key] || ""}
                      onChange={(e) => setParamGridInputs((prev) => ({ ...prev, [p.key]: e.target.value }))}
                      placeholder={p.defaults.join(",")}
                      className="text-sm font-mono"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground py-2">
                {strategy === "ml_signal"
                  ? "ML Signal does not support parameter optimization. Train models on the ML page instead."
                  : "No optimizable parameters for this strategy."}
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <Button onClick={handleOptimize} disabled={optimizing || currentParams.length === 0} className="rounded-lg font-medium min-w-35">
              {optimizing ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Search className="size-4 mr-1.5" />}
              {optimizing ? "Optimizing..." : "Run Grid Search"}
            </Button>
          </div>

          {optResult && !optResult.error && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard icon={Target} label="Best Score" value={(optResult.best_score as number).toFixed(4)} variant="gold" />
                <StatCard icon={BarChart3} label="Combinations" value={`${optResult.tested_combinations}/${optResult.total_combinations}`} />
                <StatCard icon={TrendingUp} label="Best Win Rate" value={`${(((optResult.best_metrics as Record<string, number>)?.win_rate || 0) * 100).toFixed(1)}%`} variant="success" />
                <StatCard icon={DollarSign} label="Best Profit" value={`$${((optResult.best_metrics as Record<string, number>)?.total_profit || 0).toFixed(2)}`} variant="success" />
              </div>

              {optResult.best_params != null && (
                <div className="rounded-xl border border-border bg-card p-4">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Best Parameters</h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(optResult.best_params as Record<string, number>).map(([k, v]) => (
                      <Badge key={k} variant="outline" className="text-sm py-1.5 px-4 rounded-full font-semibold">
                        {k}: <strong className="ml-1">{v}</strong>
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {(optResult.top_10 as Record<string, unknown>[])?.length > 0 && (
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-4 pt-4 pb-2">Top 10 Results</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-muted-foreground border-b border-border">
                          <th className="text-left py-2 px-4 font-semibold">#</th>
                          <th className="text-left py-2 px-4 font-semibold">Parameters</th>
                          <th className="text-right py-2 px-4 font-semibold">Score</th>
                          <th className="text-right py-2 px-4 font-semibold">Win Rate</th>
                          <th className="text-right py-2 px-4 font-semibold">Profit</th>
                          <th className="text-right py-2 px-4 font-semibold">Sharpe</th>
                          <th className="text-right py-2 px-4 font-semibold">Trades</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(optResult.top_10 as Record<string, unknown>[]).map((r, i) => (
                          <tr key={i} className={`border-b border-border/50 hover:bg-accent/30 ${i === 0 ? "bg-accent/50" : ""}`}>
                            <td className="py-2 px-4 font-semibold">{i + 1}</td>
                            <td className="py-2 px-4 font-mono text-muted-foreground">
                              {Object.entries(r.params as Record<string, number>).map(([k, v]) => `${k}=${v}`).join(", ")}
                            </td>
                            <td className="text-right py-2 px-4 font-mono font-bold">{(r.score as number).toFixed(4)}</td>
                            <td className="text-right py-2 px-4">{((r.win_rate as number) * 100).toFixed(1)}%</td>
                            <td className={`text-right py-2 px-4 font-semibold ${(r.total_profit as number) > 0 ? "text-green-400" : "text-red-400"}`}>
                              ${(r.total_profit as number).toFixed(2)}
                            </td>
                            <td className="text-right py-2 px-4">{(r.sharpe_ratio as number).toFixed(3)}</td>
                            <td className="text-right py-2 px-4">{r.total_trades as number}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {!optResult && !optimizing && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-12 rounded-xl bg-muted flex items-center justify-center mb-3">
                <Zap className="size-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold">No optimization results yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">Define parameter grid above and run grid search.</p>
            </div>
          )}

          {optResult && "error" in optResult && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 flex items-center gap-2">
              <AlertTriangle className="size-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400">{String(optResult.error)}</p>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
