"use client";

import { useState, useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import type { LucideIcon } from "lucide-react";
import {
  Play, BarChart3, TrendingUp, DollarSign, Target,
  AlertTriangle, Search, Loader2, FlaskConical, Zap, Footprints,
  CheckCircle, XCircle, Dice5,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import { showSuccess, showError } from "@/lib/toast";
import { TIMEFRAMES } from "@/components/ui/timeframe-selector";
import {
  runBacktest, runOptimize, runWalkForward, runMonteCarlo, runCointegration, runPermutationTest, runOverfittingScore, getCurrentStrategy, getDataStatus, getSymbols,
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
  { value: "dca", label: "DCA (ถัวเฉลี่ย)" },
  { value: "grid", label: "Grid Trading" },
  { value: "risk_parity", label: "Risk Parity" },
  { value: "momentum_rank", label: "Momentum Rank" },
  { value: "pair_spread", label: "Pair Spread" },
];


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
  dca: [
    { key: "interval_bars", label: "Interval (bars)", defaults: [10, 15, 20, 30, 50] },
  ],
  grid: [
    { key: "grid_spacing_pips", label: "Grid Spacing (pips)", defaults: [3, 5, 8, 10] },
    { key: "grid_levels", label: "Grid Levels", defaults: [3, 5, 7, 10] },
    { key: "sma_period", label: "SMA Period", defaults: [15, 20, 30] },
  ],
  risk_parity: [
    { key: "ema_fast", label: "EMA Fast", defaults: [15, 20, 25] },
    { key: "ema_slow", label: "EMA Slow", defaults: [40, 50, 60] },
    { key: "vol_lookback", label: "Vol Lookback", defaults: [30, 50, 80] },
  ],
  momentum_rank: [
    { key: "lookback", label: "Momentum Lookback", defaults: [10, 15, 20, 30] },
  ],
  pair_spread: [
    { key: "z_entry", label: "Z-Score Entry", defaults: [1.5, 2.0, 2.5, 3.0] },
    { key: "z_exit", label: "Z-Score Exit", defaults: [0.3, 0.5, 0.8] },
    { key: "lookback", label: "Lookback", defaults: [30, 50, 80] },
  ],
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

  // Walk-Forward state
  const [wfResult, setWfResult] = useState<Record<string, unknown> | null>(null);
  const [wfRunning, setWfRunning] = useState(false);
  const [wfSplits, setWfSplits] = useState(5);
  const [wfTrainPct, setWfTrainPct] = useState(70);
  // Monte Carlo state
  const [mcResult, setMcResult] = useState<Record<string, unknown> | null>(null);
  const [mcRunning, setMcRunning] = useState(false);
  // Significance state
  const [cointResult, setCointResult] = useState<Record<string, unknown> | null>(null);
  const [cointRunning, setCointRunning] = useState(false);
  const [permResult, setPermResult] = useState<Record<string, unknown> | null>(null);
  const [permRunning, setPermRunning] = useState(false);
  // Overfitting score state
  const [ofResult, setOfResult] = useState<Record<string, unknown> | null>(null);
  const [ofRunning, setOfRunning] = useState(false);
  const [ofHistory, setOfHistory] = useState<Record<string, unknown>[]>([]);
  // Active tab
  const [activeTab, setActiveTab] = useState("backtest");

  const currentParams: ParamDef[] = STRATEGY_PARAMS[strategy] ?? [];

  const handleStrategyChange = (v: string) => {
    setStrategy(v);
    setParamGridInputs(buildDefaultGridInputs(v));
  };

  useEffect(() => {
    getCurrentStrategy().then((res) => { if (res.data?.name) handleStrategyChange(res.data.name); }).catch(() => {});
    getDataStatus().then((res) => { if (Array.isArray(res.data) && res.data.length > 0) setHasDbData(true); }).catch(() => {});
    getSymbols().then((res) => {
      const syms = res.data?.symbols || res.data;
      if (Array.isArray(syms) && syms.length > 0) {
        setAvailableSymbols(syms);
        if (!syms.some((s: { symbol: string }) => s.symbol === symbol)) {
          setSymbol(syms[0].symbol);
        }
      }
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
      showSuccess("Backtest completed");
    } catch { showError("Backtest failed"); } finally { setLoading(false); }
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
      showSuccess("Optimization completed");
    } catch { showError("Optimization failed"); } finally { setOptimizing(false); }
  };

  const handleWalkForward = async () => {
    setWfRunning(true);
    setWfResult(null);
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
        n_splits: wfSplits,
        train_pct: wfTrainPct / 100,
      };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      else { params.count = count; }
      const res = await runWalkForward(params as Parameters<typeof runWalkForward>[0]);
      setWfResult(res.data);
      showSuccess("Walk-forward completed");
    } catch { showError("Walk-forward failed"); } finally { setWfRunning(false); }
  };

  const handleMonteCarlo = async () => {
    setMcRunning(true);
    setMcResult(null);
    try {
      const params: Record<string, unknown> = {
        strategy, symbol, timeframe, initial_balance: balance, source,
      };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      else { params.count = count; }
      const res = await runMonteCarlo(params as Parameters<typeof runMonteCarlo>[0]);
      setMcResult(res.data);
      showSuccess("Monte Carlo completed");
    } catch { showError("Monte Carlo failed"); } finally { setMcRunning(false); }
  };

  const handleCointegration = async () => {
    setCointRunning(true);
    setCointResult(null);
    try {
      const pairMap: Record<string, string> = { GOLD: "USDJPY", USDJPY: "GOLD", XAUUSD: "USDJPY" };
      const fallback = availableSymbols.find(s => s.symbol !== symbol)?.symbol;
      const symbolB = pairMap[symbol] || fallback || symbol;
      const res = await runCointegration({ symbol_a: symbol, symbol_b: symbolB, timeframe, source });
      setCointResult(res.data);
      showSuccess("Cointegration test completed");
    } catch { showError("Cointegration test failed"); } finally { setCointRunning(false); }
  };

  const handlePermutation = async () => {
    setPermRunning(true);
    setPermResult(null);
    try {
      const params: Record<string, unknown> = {
        strategy, symbol, timeframe, source, n_permutations: 500, include_costs: true,
      };
      if (source === "db") { params.from_date = fromDate; params.to_date = toDate; }
      else { params.count = count; }
      const res = await runPermutationTest(params as Parameters<typeof runPermutationTest>[0]);
      setPermResult(res.data);
      showSuccess("Permutation test completed");
    } catch { showError("Permutation test failed"); } finally { setPermRunning(false); }
  };

  const equityCurve = (result?.equity_curve as number[] || []).map((v, i) => ({ bar: i, equity: v }));

  // ─── Shared Config Form ─────────────────────────────────────────
  const configForm = (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4">
      {/* Row 1: Strategy + Symbol + Timeframe */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="space-y-1">
          <label className="text-[11px] text-muted-foreground font-medium">Strategy</label>
          <Select value={strategy} onValueChange={(v) => v && handleStrategyChange(v)}>
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
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
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
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="Backtester" subtitle="Test strategies against historical data" />

      <PageInstructions

        items={[
          "Select a strategy, symbol, and timeframe. Use MT5 for live data or DB for historical (requires data collection from ML page).",
          "Backtest tab runs a single test. Optimizer tab searches parameter combinations to find the best settings.",
          "ML Signal strategy requires a trained model — train one on the ML page first.",
        ]}
      />

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-5">
        <div className="flex gap-2 overflow-x-auto pb-1">
          {([
            { value: "backtest", label: "Backtest", icon: FlaskConical },
            { value: "optimize", label: "Optimizer", icon: Zap },
            { value: "walk-forward", label: "Walk Forward", icon: Footprints },
            { value: "monte-carlo", label: "Monte Carlo", icon: Dice5 },
            { value: "significance", label: "Significance", icon: CheckCircle },
            { value: "overfitting", label: "Overfitting", icon: AlertTriangle },
          ] as { value: string; label: string; icon: LucideIcon }[]).map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                onClick={() => setActiveTab(tab.value)}
                className={`flex items-center gap-2 min-h-11 px-4 py-2.5 rounded-xl border-2 text-xs font-semibold transition-all whitespace-nowrap ${
                  isActive
                    ? "bg-card text-primary border-primary"
                    : "bg-card text-foreground border-border hover:border-primary/50"
                }`}
              >
                <Icon className="size-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

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

        {/* ── Walk Forward Tab ────────────────────────────────── */}
        <TabsContent value="walk-forward" className="space-y-4 mt-0">
          {configForm}

          {/* Parameter Grid (reuse same inputs) */}
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
              <p className="text-xs text-muted-foreground py-2">No optimizable parameters for this strategy.</p>
            )}
          </div>

          {/* Walk Forward Settings */}
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">Walk Forward Settings</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">Splits (windows)</label>
                <Input type="number" value={wfSplits} onChange={(e) => setWfSplits(Math.max(2, Math.min(20, parseInt(e.target.value) || 5)))} className="text-sm" />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">Train % per window</label>
                <Input type="number" value={wfTrainPct} onChange={(e) => setWfTrainPct(Math.max(50, Math.min(90, parseInt(e.target.value) || 70)))} className="text-sm" />
              </div>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Each window: optimize on {wfTrainPct}% train data, validate on {100 - wfTrainPct}% out-of-sample. Detects overfitting.
            </p>
          </div>

          <div className="flex justify-end">
            <Button onClick={handleWalkForward} disabled={wfRunning} className="rounded-lg font-medium min-w-35">
              {wfRunning ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Footprints className="size-4 mr-1.5" />}
              {wfRunning ? "Running..." : "Run Walk Forward"}
            </Button>
          </div>

          {wfResult && !wfResult.error && (
            <div className="space-y-4">
              {/* Summary Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard icon={BarChart3} label="OOS Sharpe" value={(wfResult.aggregate_oos_sharpe as number).toFixed(3)} variant={(wfResult.aggregate_oos_sharpe as number) > 0.5 ? "success" : "warning"} />
                <StatCard icon={TrendingUp} label="OOS Win Rate" value={`${((wfResult.aggregate_oos_win_rate as number) * 100).toFixed(1)}%`} variant={(wfResult.aggregate_oos_win_rate as number) > 0.5 ? "success" : "danger"} />
                <StatCard icon={Target} label="Overfit Ratio" value={(wfResult.overfitting_ratio as number).toFixed(3)} variant={(wfResult.overfitting_ratio as number) >= 0.5 ? "success" : "danger"} />
                <StatCard icon={BarChart3} label="OOS Trades" value={wfResult.aggregate_oos_total_trades as number} />
              </div>

              {/* Overfitting Verdict */}
              <div className={`rounded-xl border p-4 flex items-center gap-3 ${
                wfResult.likely_overfit
                  ? "border-red-500/30 bg-red-500/5"
                  : "border-green-500/30 bg-green-500/5"
              }`}>
                {wfResult.likely_overfit
                  ? <XCircle className="size-5 text-red-400 shrink-0" />
                  : <CheckCircle className="size-5 text-green-400 shrink-0" />}
                <div>
                  <p className={`text-sm font-semibold ${wfResult.likely_overfit ? "text-red-400" : "text-green-400"}`}>
                    {wfResult.likely_overfit ? "Likely Overfit" : "Robust Strategy"}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    IS Sharpe: {(wfResult.in_sample_avg_sharpe as number).toFixed(3)} → OOS Sharpe: {(wfResult.aggregate_oos_sharpe as number).toFixed(3)} (ratio: {(wfResult.overfitting_ratio as number).toFixed(2)})
                    {(wfResult.overfitting_ratio as number) < 0.5 ? " — large performance drop out-of-sample" : " — performance holds out-of-sample"}
                    {(wfResult.oos_sharpe_ci as number[]) && (
                      <> | 95% CI: [{(wfResult.oos_sharpe_ci as number[])[0].toFixed(3)}, {(wfResult.oos_sharpe_ci as number[])[1].toFixed(3)}]</>
                    )}
                    {wfResult.param_stability_score != null && (
                      <> | Param Stability: {(wfResult.param_stability_score as number).toFixed(3)} ({(wfResult.param_stability_score as number) < 0.3 ? "stable" : (wfResult.param_stability_score as number) < 0.6 ? "moderate" : "unstable"})</>
                    )}
                  </p>
                </div>
              </div>

              {/* Window-by-window breakdown */}
              {(wfResult.windows as Record<string, unknown>[])?.length > 0 && (
                <div className="rounded-xl border border-border bg-card overflow-hidden">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-4 pt-4 pb-2">Window Breakdown</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-muted-foreground border-b border-border">
                          <th className="text-left py-2 px-4 font-semibold">Split</th>
                          <th className="text-right py-2 px-4 font-semibold">Train</th>
                          <th className="text-right py-2 px-4 font-semibold">Test</th>
                          <th className="text-left py-2 px-4 font-semibold">Best Params</th>
                          <th className="text-right py-2 px-4 font-semibold">IS Sharpe</th>
                          <th className="text-right py-2 px-4 font-semibold">OOS Sharpe</th>
                          <th className="text-right py-2 px-4 font-semibold">OOS Win%</th>
                          <th className="text-right py-2 px-4 font-semibold">OOS P&L</th>
                          <th className="text-right py-2 px-4 font-semibold">Trades</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(wfResult.windows as Record<string, unknown>[]).map((w) => (
                          <tr key={w.split as number} className="border-b border-border/50 hover:bg-accent/30">
                            <td className="py-2 px-4 font-semibold">{w.split as number}</td>
                            <td className="text-right py-2 px-4 text-muted-foreground">{w.train_bars as number}</td>
                            <td className="text-right py-2 px-4 text-muted-foreground">{w.test_bars as number}</td>
                            <td className="py-2 px-4 font-mono text-muted-foreground">
                              {Object.entries(w.best_params as Record<string, number>).map(([k, v]) => `${k}=${v}`).join(", ")}
                            </td>
                            <td className="text-right py-2 px-4 font-mono">{(w.in_sample_sharpe as number).toFixed(3)}</td>
                            <td className={`text-right py-2 px-4 font-mono font-semibold ${(w.oos_sharpe as number) > 0 ? "text-green-400" : "text-red-400"}`}>
                              {(w.oos_sharpe as number).toFixed(3)}
                            </td>
                            <td className="text-right py-2 px-4">{((w.oos_win_rate as number) * 100).toFixed(1)}%</td>
                            <td className={`text-right py-2 px-4 font-semibold ${(w.oos_total_profit as number) >= 0 ? "text-green-400" : "text-red-400"}`}>
                              ${(w.oos_total_profit as number).toFixed(2)}
                            </td>
                            <td className="text-right py-2 px-4">{w.oos_total_trades as number}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Parameter Stability */}
              {(wfResult.best_params_stability as Record<string, number>[])?.length > 1 && (
                <div className="rounded-xl border border-border bg-card p-4">
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Parameter Stability</h3>
                  <p className="text-[11px] text-muted-foreground mb-2">
                    Consistent parameters across windows indicate a robust strategy. Large variations suggest overfitting.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.keys((wfResult.best_params_stability as Record<string, number>[])[0]).map((key) => {
                      const values = (wfResult.best_params_stability as Record<string, number>[]).map((p) => p[key]);
                      const unique = [...new Set(values)];
                      const stable = unique.length === 1;
                      return (
                        <Badge key={key} variant="outline" className={`text-xs py-1 px-3 rounded-full ${stable ? "border-green-500/50 text-green-400" : "border-amber-500/50 text-amber-400"}`}>
                          {key}: {unique.length === 1 ? String(unique[0]) : unique.join(" → ")}
                        </Badge>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {!wfResult && !wfRunning && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-12 rounded-xl bg-muted flex items-center justify-center mb-3">
                <Footprints className="size-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold">No walk-forward results yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Walk Forward tests parameters on unseen data to detect overfitting.
                Define parameter grid above and run.
              </p>
            </div>
          )}

          {wfResult && "error" in wfResult && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 flex items-center gap-2">
              <AlertTriangle className="size-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400">{String(wfResult.error)}</p>
            </div>
          )}
        </TabsContent>

        {/* ── Monte Carlo Tab ────────────────────────────────── */}
        <TabsContent value="monte-carlo" className="space-y-4 mt-0">
          {configForm}

          <div className="flex justify-end">
            <Button onClick={handleMonteCarlo} disabled={mcRunning} className="rounded-lg font-medium min-w-35">
              {mcRunning ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Dice5 className="size-4 mr-1.5" />}
              {mcRunning ? "Simulating..." : "Run Monte Carlo"}
            </Button>
          </div>

          {mcResult && !mcResult.error && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                <StatCard
                  icon={Target}
                  label="P(Profit)"
                  value={`${((mcResult.probability_of_profit as number) * 100).toFixed(1)}%`}
                  variant={(mcResult.probability_of_profit as number) > 0.5 ? "success" : "danger"}
                />
                <StatCard
                  icon={AlertTriangle}
                  label="P(Ruin)"
                  value={`${((mcResult.probability_of_ruin as number) * 100).toFixed(1)}%`}
                  variant={(mcResult.probability_of_ruin as number) < 0.1 ? "success" : "danger"}
                />
                <StatCard
                  icon={DollarSign}
                  label="Median Balance"
                  value={`$${(mcResult.median_final_balance as number).toFixed(0)}`}
                  variant={(mcResult.median_final_balance as number) > (balance || 10000) ? "success" : "warning"}
                />
                <StatCard
                  icon={TrendingUp}
                  label="P95 Drawdown"
                  value={`${((mcResult.p95_max_drawdown as number) * 100).toFixed(1)}%`}
                  variant={(mcResult.p95_max_drawdown as number) < 0.3 ? "success" : "danger"}
                />
                <StatCard
                  icon={BarChart3}
                  label="Simulations"
                  value={mcResult.n_simulations as number}
                />
              </div>

              {/* Balance range */}
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Balance Distribution (1,000 simulations)</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <div>
                    <p className="text-[11px] text-muted-foreground">Pessimistic (P5)</p>
                    <p className="font-bold font-mono text-red-400">${(mcResult.p5_final_balance as number).toFixed(0)}</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-muted-foreground">Median (P50)</p>
                    <p className="font-bold font-mono">${(mcResult.median_final_balance as number).toFixed(0)}</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-muted-foreground">Mean</p>
                    <p className="font-bold font-mono">${(mcResult.mean_final_balance as number).toFixed(0)}</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-muted-foreground">Optimistic (P95)</p>
                    <p className="font-bold font-mono text-green-400">${(mcResult.p95_final_balance as number).toFixed(0)}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {!mcResult && !mcRunning && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="size-12 rounded-xl bg-muted flex items-center justify-center mb-3">
                <Dice5 className="size-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-semibold">No Monte Carlo results yet</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Monte Carlo shuffles trade order 1,000 times to test if profits depend on lucky sequence or real edge.
              </p>
            </div>
          )}

          {mcResult && "error" in mcResult && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 flex items-center gap-2">
              <AlertTriangle className="size-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400">{String(mcResult.error)}</p>
            </div>
          )}
        </TabsContent>

        {/* ── Significance Tab ───────────────────────────────── */}
        <TabsContent value="significance" className="space-y-4 mt-0">
          {configForm}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Cointegration Test */}
            <div className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Cointegration (ADF)</h3>
                <Button onClick={handleCointegration} disabled={cointRunning} variant="outline" size="sm" className="h-7 text-xs rounded-lg">
                  {cointRunning ? <Loader2 className="size-3 mr-1 animate-spin" /> : <Search className="size-3 mr-1" />}
                  {cointRunning ? "Testing..." : "Test Pair"}
                </Button>
              </div>

              {cointResult && !cointResult.error && (
                <div className={`rounded-lg border p-3 ${
                  cointResult.is_cointegrated
                    ? "border-green-500/30 bg-green-500/5"
                    : "border-red-500/30 bg-red-500/5"
                }`}>
                  <p className={`text-sm font-bold ${cointResult.is_cointegrated ? "text-green-400" : "text-red-400"}`}>
                    {cointResult.verdict as string}
                  </p>
                  <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-muted-foreground">
                    <span>p-value: <strong className="text-foreground">{(cointResult.p_value as number).toFixed(4)}</strong></span>
                    <span>Hedge ratio: <strong className="text-foreground">{(cointResult.hedge_ratio as number).toFixed(4)}</strong></span>
                    <span>Test stat: {(cointResult.test_statistic as number).toFixed(4)}</span>
                    <span>Observations: {cointResult.n_observations as number}</span>
                  </div>
                </div>
              )}
              {cointResult && Boolean(cointResult.error) && (
                <p className="text-xs text-red-400">{String(cointResult.error)}</p>
              )}
              {!cointResult && (
                <p className="text-xs text-muted-foreground text-center py-4">
                  Tests if {symbol} and its pair are cointegrated (p &lt; 0.05 = valid for pair spread)
                </p>
              )}
            </div>

            {/* Permutation Test */}
            <div className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Permutation Test</h3>
                <Button onClick={handlePermutation} disabled={permRunning} variant="outline" size="sm" className="h-7 text-xs rounded-lg">
                  {permRunning ? <Loader2 className="size-3 mr-1 animate-spin" /> : <Zap className="size-3 mr-1" />}
                  {permRunning ? "Testing..." : "Test Significance"}
                </Button>
              </div>

              {permResult && !permResult.error && (
                <div className={`rounded-lg border p-3 ${
                  permResult.is_significant
                    ? "border-green-500/30 bg-green-500/5"
                    : "border-red-500/30 bg-red-500/5"
                }`}>
                  <p className={`text-sm font-bold ${permResult.is_significant ? "text-green-400" : "text-red-400"}`}>
                    {permResult.verdict as string}
                  </p>
                  <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-muted-foreground">
                    <span>p-value: <strong className="text-foreground">{(permResult.p_value as number).toFixed(4)}</strong></span>
                    <span>Real Sharpe: <strong className="text-foreground">{(permResult.real_sharpe as number).toFixed(4)}</strong></span>
                    <span>Shuffled mean: {(permResult.shuffled_mean as number).toFixed(4)}</span>
                    <span>Shuffled std: {(permResult.shuffled_std as number).toFixed(4)}</span>
                  </div>
                </div>
              )}
              {permResult && Boolean(permResult.error) && (
                <p className="text-xs text-red-400">{String(permResult.error)}</p>
              )}
              {!permResult && (
                <p className="text-xs text-muted-foreground text-center py-4">
                  Shuffles signals 500 times to test if strategy beats random (p &lt; 0.05 = real edge)
                </p>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ── Overfitting Score Tab ──────────────────────────────── */}
        <TabsContent value="overfitting" className="space-y-4 mt-0">
          <div className="border border-border rounded-lg p-4 bg-card space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">Composite Overfitting Score</h3>
              <Button
                onClick={async () => {
                  setOfRunning(true);
                  setOfResult(null);
                  try {
                    const res = await runOverfittingScore({
                      strategy, symbol, timeframe,
                      source, count,
                    });
                    const data = res.data as Record<string, unknown>;
                    setOfResult(data);
                    // Add to comparison history
                    setOfHistory((prev) => {
                      const filtered = prev.filter(
                        (h) => !(h.strategy === data.strategy && h.symbol === data.symbol)
                      );
                      return [...filtered, data];
                    });
                    showSuccess(`Overfitting score: ${data.overfitting_pct}% (${data.grade})`);
                  } catch {
                    showError("Overfitting score computation failed");
                  } finally {
                    setOfRunning(false);
                  }
                }}
                disabled={ofRunning}
                size="sm"
              >
                {ofRunning ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <Search className="size-3.5 mr-1.5" />}
                {ofRunning ? "Computing..." : "Compute Score"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Runs walk-forward, permutation test, and monte carlo analysis concurrently. Auto-generates parameter grid from strategy profiles.
            </p>
          </div>

          {ofResult && !("error" in ofResult) && (
            <>
              {/* Score Display */}
              <div className={`border rounded-lg p-6 flex flex-col items-center gap-3 ${
                (ofResult.grade === "healthy") ? "border-green-500/30 bg-green-500/5" :
                (ofResult.grade === "moderate") ? "border-amber-500/30 bg-amber-500/5" :
                "border-red-500/30 bg-red-500/5"
              }`}>
                <div className="flex items-center gap-3">
                  {ofResult.grade === "healthy" ? <CheckCircle className="size-8 text-green-400" /> :
                   ofResult.grade === "moderate" ? <AlertTriangle className="size-8 text-amber-400" /> :
                   <XCircle className="size-8 text-red-400" />}
                  <span className={`text-5xl font-bold tabular-nums ${
                    (ofResult.grade === "healthy") ? "text-green-400" :
                    (ofResult.grade === "moderate") ? "text-amber-400" :
                    "text-red-400"
                  }`}>
                    {String(ofResult.overfitting_pct)}%
                  </span>
                </div>
                <Badge variant={
                  ofResult.grade === "healthy" ? "default" :
                  ofResult.grade === "moderate" ? "secondary" :
                  "destructive"
                }>
                  {String(ofResult.grade).toUpperCase()}
                </Badge>
                <p className="text-xs text-muted-foreground">
                  {String(ofResult.strategy)} on {String(ofResult.symbol)}
                  {Boolean(ofResult.partial) && (
                    <span className="ml-2 text-amber-400">
                      (partial — skipped: {(ofResult.skipped_tests as string[]).join(", ")})
                    </span>
                  )}
                </p>
                {/* Progress bar */}
                <div className="w-full max-w-md h-3 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (ofResult.grade === "healthy") ? "bg-green-500" :
                      (ofResult.grade === "moderate") ? "bg-amber-500" :
                      "bg-red-500"
                    }`}
                    style={{ width: `${Math.min(100, Number(ofResult.overfitting_pct))}%` }}
                  />
                </div>
              </div>

              {/* Component Breakdown */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(ofResult.components as Record<string, number>).map(([key, value]) => (
                  <StatCard
                    key={key}
                    icon={
                      key === "walk_forward" ? Footprints :
                      key === "permutation" ? Dice5 :
                      key === "param_stability" ? Target :
                      BarChart3
                    }
                    label={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    value={`${value}%`}
                    variant={value < 30 ? "success" : value < 60 ? "warning" : "danger"}
                  />
                ))}
              </div>

              {/* Walk-Forward Detail */}
              {ofResult.walk_forward && (
                <div className="border border-border rounded-lg p-4 bg-card space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Walk-Forward Detail</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                    <div><span className="text-muted-foreground">IS Sharpe:</span> {String((ofResult.walk_forward as Record<string, unknown>).is_sharpe)}</div>
                    <div><span className="text-muted-foreground">OOS Sharpe:</span> {String((ofResult.walk_forward as Record<string, unknown>).oos_sharpe)}</div>
                    <div><span className="text-muted-foreground">Ratio:</span> {String((ofResult.walk_forward as Record<string, unknown>).overfitting_ratio)}</div>
                    <div><span className="text-muted-foreground">Param CV:</span> {String((ofResult.walk_forward as Record<string, unknown>).param_stability_score ?? "N/A")}</div>
                  </div>
                </div>
              )}

              {/* Permutation Detail */}
              {ofResult.permutation && (
                <div className="border border-border rounded-lg p-4 bg-card space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Permutation Test Detail</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                    <div><span className="text-muted-foreground">Real Sharpe:</span> {String((ofResult.permutation as Record<string, unknown>).real_sharpe)}</div>
                    <div><span className="text-muted-foreground">p-value:</span> {String((ofResult.permutation as Record<string, unknown>).p_value)}</div>
                    <div><span className="text-muted-foreground">Significant:</span> {(ofResult.permutation as Record<string, unknown>).is_significant ? "Yes" : "No"}</div>
                    <div><span className="text-muted-foreground">Shuffled Mean:</span> {String((ofResult.permutation as Record<string, unknown>).shuffled_mean)}</div>
                  </div>
                </div>
              )}

              {/* Monte Carlo Detail */}
              {ofResult.monte_carlo && (
                <div className="border border-border rounded-lg p-4 bg-card space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Monte Carlo Detail</h4>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                    <div><span className="text-muted-foreground">Ruin Prob:</span> {String((ofResult.monte_carlo as Record<string, unknown>).probability_of_ruin)}</div>
                    <div><span className="text-muted-foreground">Profit Prob:</span> {String((ofResult.monte_carlo as Record<string, unknown>).probability_of_profit)}</div>
                    <div><span className="text-muted-foreground">p95 DD:</span> {String((ofResult.monte_carlo as Record<string, unknown>).p95_max_drawdown)}</div>
                    <div><span className="text-muted-foreground">Median Balance:</span> {String((ofResult.monte_carlo as Record<string, unknown>).median_final_balance)}</div>
                  </div>
                </div>
              )}
            </>
          )}

          {ofResult && "error" in ofResult && (
            <div className="border border-red-500/30 bg-red-500/5 rounded-lg p-4 text-red-400 text-sm">
              {String(ofResult.error)}
            </div>
          )}

          {/* Comparison History */}
          {ofHistory.length > 1 && (
            <div className="border border-border rounded-lg p-4 bg-card space-y-3">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Strategy Comparison</h4>
              <div className="space-y-2">
                {ofHistory.map((h, i) => {
                  const pct = Number(h.overfitting_pct);
                  const grade = String(h.grade);
                  return (
                    <div key={`${String(h.strategy)}-${String(h.symbol)}`} className="flex items-center gap-3">
                      <span className="text-sm w-32 truncate">{String(h.strategy)}</span>
                      <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            grade === "healthy" ? "bg-green-500" :
                            grade === "moderate" ? "bg-amber-500" :
                            "bg-red-500"
                          }`}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                      <span className={`text-sm font-mono w-14 text-right ${
                        grade === "healthy" ? "text-green-400" :
                        grade === "moderate" ? "text-amber-400" :
                        "text-red-400"
                      }`}>{pct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!ofResult && !ofRunning && (
            <p className="text-xs text-muted-foreground text-center py-4">
              Combines walk-forward ratio (40%), permutation p-value (25%), param stability (20%), and monte carlo ruin probability (15%) into a single overfitting score
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
