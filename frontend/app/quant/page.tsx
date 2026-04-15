"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { SymbolTabs } from "@/components/ui/symbol-tabs";
import { StatCard } from "@/components/ui/stat-card";
import { RegimeBadge } from "@/components/quant/RegimeBadge";
import { CorrelationHeatmap } from "@/components/quant/CorrelationHeatmap";
import { SignalConfidenceBar } from "@/components/quant/SignalConfidenceBar";
import { useBotStore } from "@/store/botStore";
import {
  getQuantVaR, getQuantRegime, getQuantCorrelation,
  getQuantVolatility, getQuantSignals, getQuantPortfolio,
  runStressTest,
} from "@/lib/api";
import { showSuccess, showError } from "@/lib/toast";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Shield, TrendingUp, Activity, GitBranch, PieChart, Zap,
  AlertTriangle, Loader2, BarChart3,
} from "lucide-react";

function MultiTFDisplay({ data }: { data: Record<string, string | number> }) {
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <p>M15: {String(data.m15)}</p>
      <p>H1: {String(data.h1)}</p>
      <p>H4: {String(data.h4)}</p>
      <p className="font-semibold">Agreement: {String(data.agreement)}</p>
    </div>
  );
}

export default function QuantPage() {
  const { symbols } = useBotStore();
  const [activeSymbol, setActiveSymbol] = useState("GOLD");

  useEffect(() => {
    if (symbols.length > 0 && !symbols.some(s => s.symbol === activeSymbol)) {
      setActiveSymbol(symbols[0].symbol);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols]);
  const [loading, setLoading] = useState(true);
  const [var_, setVar] = useState<Record<string, Record<string, unknown>>>({});
  const [regime, setRegime] = useState<Record<string, Record<string, unknown>>>({});
  const [correlation, setCorrelation] = useState<Record<string, number>>({});
  const [volatility, setVolatility] = useState<Record<string, Record<string, unknown>>>({});
  const [signals, setSignals] = useState<Record<string, Record<string, unknown>>>({});
  const [portfolio, setPortfolio] = useState<Record<string, unknown> | null>(null);
  const [stressResults, setStressResults] = useState<Record<string, unknown>[] | null>(null);
  const [stressLoading, setStressLoading] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [varRes, regRes, corrRes, volRes, sigRes, portRes] = await Promise.all([
        getQuantVaR(), getQuantRegime(), getQuantCorrelation(),
        getQuantVolatility(), getQuantSignals(), getQuantPortfolio(),
      ]);
      setVar(varRes.data.symbols || {});
      setRegime(regRes.data.symbols || {});
      setCorrelation(corrRes.data.matrix || {});
      setVolatility(volRes.data.symbols || {});
      setSignals(sigRes.data.symbols || {});
      setPortfolio(portRes.data);
    } catch (e) {
      console.error("Quant data fetch failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const [stressError, setStressError] = useState<string | null>(null);

  const handleStressTest = async () => {
    setStressLoading(true);
    setStressError(null);
    try {
      const res = await runStressTest("all");
      const results = res.data.results || [];
      if (results.length === 0) {
        setStressError("No results — bot must be running with market data available");
      } else {
        showSuccess("Stress test completed");
      }
      setStressResults(results.length > 0 ? results : null);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setStressError(msg || "Stress test failed — check backend logs");
      showError("Stress test failed");
      setStressResults(null);
    } finally {
      setStressLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-48 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  const symVar = var_[activeSymbol] || {};
  const symRegime = regime[activeSymbol] || {};
  const symVol = volatility[activeSymbol] || {};
  const symSignals = signals[activeSymbol] || {};
  const sharpeAlloc = (portfolio as Record<string, Record<string, unknown>>)?.max_sharpe || {};
  const parityAlloc = (portfolio as Record<string, Record<string, unknown>>)?.risk_parity || {};

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="Quant Analytics" subtitle="Quantitative risk, signals, and portfolio analysis" />

      <PageInstructions
        items={[
          "VaR/CVaR shows potential loss at 95% and 99% confidence levels.",
          "Regime detection uses HMM to identify trending vs ranging markets.",
          "Correlation monitor tracks cross-symbol relationships in real-time.",
        ]}
      />

      <SymbolTabs symbols={symbols} active={activeSymbol} onSelect={setActiveSymbol} />

      {/* Row 1: Risk Overview */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard icon={Shield} label="VaR 95%" value={symVar.var_95 ? `${((symVar.var_95 as number) * 100).toFixed(2)}%` : "--"} variant={symVar.var_95 && (symVar.var_95 as number) > 0.03 ? "danger" : "success"} />
        <StatCard icon={Shield} label="CVaR 95%" value={symVar.cvar_95 ? `${((symVar.cvar_95 as number) * 100).toFixed(2)}%` : "--"} variant="warning" />
        <StatCard icon={Activity} label="Ann. Vol" value={symVar.annualized_vol ? `${((symVar.annualized_vol as number) * 100).toFixed(1)}%` : "--"} />
        <StatCard icon={TrendingUp} label="GARCH Vol" value={symVol.current_vol ? `${((symVol.current_vol as number) * 100).toFixed(1)}%` : "--"} variant="gold" />
        <StatCard icon={TrendingUp} label="Forecast 1-step" value={symVol.forecast_1 ? `${((symVol.forecast_1 as number) * 100).toFixed(1)}%` : "--"} />
        <StatCard icon={Activity} label="GARCH Method" value={(symVol.method as string) || "--"} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Regime */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <TrendingUp className="size-4 text-primary-foreground dark:text-primary" />
              Market Regime
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2">
              <RegimeBadge regime={(symRegime.current as string) || "normal"} size="md" />
            </div>
            {symRegime.multi_tf != null && (
              <MultiTFDisplay data={symRegime.multi_tf as Record<string, string | number>} />
            )}
          </CardContent>
        </Card>

        {/* Correlation */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <GitBranch className="size-4 text-primary-foreground dark:text-primary" />
              Correlation Matrix
            </CardTitle>
          </CardHeader>
          <CardContent>
            <CorrelationHeatmap matrix={correlation} />
          </CardContent>
        </Card>

        {/* Quant Signals */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Zap className="size-4 text-primary-foreground dark:text-primary" />
              {activeSymbol} Signals
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {[
              { label: "Z-Score", value: symSignals.z_score, fmt: (v: number) => v?.toFixed(2) },
              { label: "Hurst", value: symSignals.hurst, fmt: (v: number) => `${v?.toFixed(3)} (${v > 0.55 ? "trending" : v < 0.45 ? "mean-rev" : "neutral"})` },
              { label: "Rolling Sharpe", value: symSignals.rolling_sharpe, fmt: (v: number) => v?.toFixed(2) },
              { label: "Momentum", value: symSignals.momentum_factor, fmt: (v: number) => v?.toFixed(3) },
              { label: "Half-life", value: symSignals.half_life, fmt: (v: number) => v === Infinity ? "∞" : `${v?.toFixed(0)} bars` },
            ].map(({ label, value, fmt }) => (
              <div key={label} className="flex justify-between text-xs">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-mono font-bold">{value !== undefined ? fmt(value as number) : "--"}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Row 3: Portfolio + Stress Test */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Portfolio Allocation */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <PieChart className="size-4 text-primary-foreground dark:text-primary" />
              Portfolio Allocation
            </CardTitle>
          </CardHeader>
          <CardContent>
            {sharpeAlloc.weights ? (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground font-medium">Max Sharpe ({((sharpeAlloc.sharpe_ratio as number) || 0).toFixed(2)})</p>
                {Object.entries(sharpeAlloc.weights as Record<string, number>).map(([sym, w]) => (
                  <div key={sym} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-medium">{sym}</span>
                      <span className="font-mono font-bold">{(w * 100).toFixed(1)}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${w * 100}%` }} />
                    </div>
                  </div>
                ))}
                {parityAlloc.weights != null && (
                  <>
                    <hr className="border-border" />
                    <p className="text-xs text-muted-foreground font-medium">Risk Parity</p>
                    {Object.entries(parityAlloc.weights as Record<string, number>).map(([sym, w]) => (
                      <div key={sym} className="flex justify-between text-xs">
                        <span>{sym}</span>
                        <span className="font-mono font-bold">{(w * 100).toFixed(1)}%</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            ) : (
              <EmptyState icon={PieChart} heading="No portfolio data" description="Portfolio allocation will appear when data is available" />
            )}
          </CardContent>
        </Card>

        {/* Stress Test */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <AlertTriangle className="size-4 text-primary-foreground dark:text-primary" />
              Stress Testing
            </CardTitle>
          </CardHeader>
          <CardContent>
            {stressResults ? (
              <div className="space-y-2">
                {stressResults.map((r: Record<string, unknown>, i: number) => (
                  <div key={i} className="flex justify-between items-center text-xs border-b border-border pb-2 last:border-0">
                    <div>
                      <p className="font-medium">{String(r.scenario)}</p>
                      <p className="text-muted-foreground">Worst: {String(r.worst_symbol)}</p>
                    </div>
                    <div className="text-right">
                      <p className={`font-mono font-bold ${(r.portfolio_impact as number) < 0 ? "text-red-400" : "text-green-400"}`}>
                        {((r.portfolio_impact as number) * 100).toFixed(1)}%
                      </p>
                      {Boolean(r.var_breach) && <span className="text-[10px] text-red-400 font-semibold">VaR BREACH</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-8">
                <BarChart3 className="size-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">Run stress scenarios to evaluate portfolio resilience</p>
                <Button
                  onClick={handleStressTest}
                  disabled={stressLoading}
                  className="rounded-full bg-primary text-primary-foreground font-semibold"
                >
                  {stressLoading ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <AlertTriangle className="size-4 mr-1.5" />}
                  {stressLoading ? "Running..." : "Run Stress Tests"}
                </Button>
                {stressError && (
                  <p className="text-xs text-red-400 font-medium">{stressError}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
