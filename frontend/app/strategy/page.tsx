"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Save, FlaskConical, Check } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import { BarChart3, TrendingUp, Target, AlertTriangle } from "lucide-react";
import {
  getBotStatus, getAvailableStrategies, updateStrategy, updateSettings, runBacktest, getSymbols,
} from "@/lib/api";

type SymbolInfo = { symbol: string; display_name: string; state: string };

const strategyDescriptions: Record<string, string> = {
  ema_crossover: "Buy when fast EMA crosses above slow EMA, sell on cross below. Simple trend-following strategy.",
  rsi_filter: "EMA crossover with RSI filter gate. Avoids overbought buys and oversold sells.",
  breakout: "Buy when price breaks above N-period high channel, sell on break below. Filtered by ATR and volume.",
  ml_signal: "LightGBM ML model predicts BUY/SELL/HOLD from 38 technical features. Requires a trained model.",
};

export default function StrategyPage() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [activeSymbol, setActiveSymbol] = useState("GOLD");
  const [strategies, setStrategies] = useState<{ name: string }[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState("ema_crossover");
  const [params, setParams] = useState({
    fast_period: 20, slow_period: 50, rsi_period: 14, rsi_overbought: 70, rsi_oversold: 30,
    lookback: 20, atr_period: 14, atr_threshold: 0.5, volume_filter: true,
  });
  const [riskParams, setRiskParams] = useState({
    risk_per_trade: 1.0, max_daily_loss: 3.0, max_concurrent: 3, max_lot: 1.0,
  });
  const [aiSettings, setAiSettings] = useState({ use_ai_filter: true, confidence_threshold: 0.7 });
  const [backtestResult, setBacktestResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [stratRes, symbolsRes] = await Promise.all([
        getAvailableStrategies(),
        getSymbols().catch(() => null),
      ]);
      setStrategies(stratRes.data.strategies || []);
      if (symbolsRes?.data?.symbols) {
        setSymbols(symbolsRes.data.symbols);
      }
    } catch (e) { console.error(e); }
  }, []);

  // Load per-symbol settings when activeSymbol changes
  const loadSymbolSettings = useCallback(async (symbol: string) => {
    try {
      const statusRes = await getBotStatus(symbol);
      const data = statusRes.data;
      setSelectedStrategy(data.strategy || "ema_crossover");
      if (data.strategy_params) setParams((prev) => ({ ...prev, ...data.strategy_params }));
      setAiSettings({
        use_ai_filter: data.use_ai_filter ?? true,
        confidence_threshold: 0.7,
      });
      setRiskParams({
        risk_per_trade: data.max_risk_per_trade != null ? data.max_risk_per_trade * 100 : 1.0,
        max_daily_loss: data.max_daily_loss != null ? data.max_daily_loss * 100 : 3.0,
        max_concurrent: data.max_concurrent_trades ?? 3,
        max_lot: data.max_lot ?? 1.0,
      });
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { loadSymbolSettings(activeSymbol); }, [activeSymbol, loadSymbolSettings]);

  const getStrategyParams = () => {
    if (selectedStrategy === "ema_crossover") {
      return { fast_period: params.fast_period, slow_period: params.slow_period };
    }
    if (selectedStrategy === "breakout") {
      return {
        lookback: params.lookback, atr_period: params.atr_period,
        atr_threshold: params.atr_threshold, volume_filter: params.volume_filter,
      };
    }
    if (selectedStrategy === "ml_signal") {
      return { confidence_threshold: aiSettings.confidence_threshold };
    }
    return {
      ema_fast: params.fast_period, ema_slow: params.slow_period,
      rsi_period: params.rsi_period, rsi_overbought: params.rsi_overbought, rsi_oversold: params.rsi_oversold,
    };
  };

  const handleSave = async () => {
    try {
      await updateStrategy(selectedStrategy, getStrategyParams(), activeSymbol);
      await updateSettings({
        symbol: activeSymbol,
        use_ai_filter: aiSettings.use_ai_filter,
        ai_confidence_threshold: aiSettings.confidence_threshold,
        max_risk_per_trade: riskParams.risk_per_trade / 100,
        max_daily_loss: riskParams.max_daily_loss / 100,
        max_concurrent_trades: riskParams.max_concurrent,
        max_lot: riskParams.max_lot,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error("Save failed:", e);
      alert("Failed to save strategy. Check console for details.");
    }
  };

  const handleBacktest = async () => {
    setLoading(true);
    try {
      const res = await runBacktest({
        strategy: selectedStrategy, params: getStrategyParams(), symbol: activeSymbol, count: 5000,
        use_ai_filter: aiSettings.use_ai_filter, initial_balance: 10000,
      });
      setBacktestResult(res.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const riskLevel = Math.min(100, (riskParams.risk_per_trade / 5) * 50 + (riskParams.max_daily_loss / 10) * 50);
  const activeSymbolInfo = symbols.find((s) => s.symbol === activeSymbol);

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Strategy" subtitle="Configure trading strategy and risk per symbol" />

      {/* Symbol Tabs */}
      {symbols.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {symbols.map((s) => (
            <button
              key={s.symbol}
              type="button"
              onClick={() => { setActiveSymbol(s.symbol); setBacktestResult(null); }}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-semibold transition-all whitespace-nowrap ${
                s.symbol === activeSymbol
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-card text-foreground border-border hover:border-primary/50"
              }`}
            >
              <span>{s.display_name}</span>
              <span
                className={`size-1.5 rounded-full ${
                  s.state === "RUNNING" ? "bg-green-400" : "bg-muted-foreground/30"
                }`}
              />
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Strategy */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold">
              Trading Strategy — {activeSymbolInfo?.display_name || activeSymbol}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Select value={selectedStrategy} onValueChange={(v) => v && setSelectedStrategy(v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {strategies.map((s) => (
                    <SelectItem key={s.name} value={s.name}>
                      {s.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground leading-relaxed font-medium">
                {strategyDescriptions[selectedStrategy] || "Custom strategy"}
              </p>
            </div>

            <div className="space-y-4">
              {selectedStrategy === "ml_signal" && (
                <p className="text-xs text-muted-foreground font-medium py-2">
                  ML model uses 38 technical features automatically. Adjust confidence threshold in AI Settings.
                </p>
              )}
              {selectedStrategy !== "breakout" && selectedStrategy !== "ml_signal" && (
                <>
                  <ParamSlider label="Fast EMA" value={params.fast_period} min={5} max={50}
                    onChange={(v) => setParams({ ...params, fast_period: v })} />
                  <ParamSlider label="Slow EMA" value={params.slow_period} min={20} max={200}
                    onChange={(v) => setParams({ ...params, slow_period: v })} />
                </>
              )}
              {selectedStrategy === "rsi_filter" && (
                <>
                  <ParamSlider label="RSI Period" value={params.rsi_period} min={5} max={30}
                    onChange={(v) => setParams({ ...params, rsi_period: v })} />
                  <ParamSlider label="RSI Overbought" value={params.rsi_overbought} min={60} max={85}
                    onChange={(v) => setParams({ ...params, rsi_overbought: v })} />
                  <ParamSlider label="RSI Oversold" value={params.rsi_oversold} min={15} max={40}
                    onChange={(v) => setParams({ ...params, rsi_oversold: v })} />
                </>
              )}
              {selectedStrategy === "breakout" && (
                <>
                  <ParamSlider label="Channel Lookback" value={params.lookback} min={10} max={50}
                    onChange={(v) => setParams({ ...params, lookback: v })} />
                  <ParamSlider label="ATR Period" value={params.atr_period} min={7} max={30}
                    onChange={(v) => setParams({ ...params, atr_period: v })} />
                  <ParamSlider label="ATR Threshold" value={params.atr_threshold} min={0.1} max={2.0} step={0.1}
                    onChange={(v) => setParams({ ...params, atr_threshold: v })} />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground font-medium">Volume Filter</span>
                    <Switch
                      checked={params.volume_filter}
                      onCheckedChange={(v) => setParams({ ...params, volume_filter: v })}
                    />
                  </div>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          {/* Risk */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-bold">Risk Management</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ParamSlider label="Risk per Trade %" value={riskParams.risk_per_trade} min={0.1} max={5} step={0.1}
                onChange={(v) => setRiskParams({ ...riskParams, risk_per_trade: v })} />
              <ParamSlider label="Max Daily Loss %" value={riskParams.max_daily_loss} min={1} max={10} step={0.5}
                onChange={(v) => setRiskParams({ ...riskParams, max_daily_loss: v })} />
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground font-medium">Max Concurrent Trades</span>
                <Input
                  type="number"
                  value={riskParams.max_concurrent}
                  className="w-20"
                  onChange={(e) => setRiskParams({ ...riskParams, max_concurrent: parseInt(e.target.value) || 1 })}
                />
              </div>
              <div className="space-y-1.5 pt-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground font-medium">Risk Level</span>
                  <span className={`font-semibold ${riskLevel > 60 ? "text-destructive" : riskLevel > 30 ? "text-amber-600 dark:text-amber-400" : "text-success dark:text-green-400"}`}>
                    {riskLevel > 60 ? "Aggressive" : riskLevel > 30 ? "Moderate" : "Conservative"}
                  </span>
                </div>
                <Progress value={riskLevel} className="h-1.5" />
              </div>
            </CardContent>
          </Card>

          {/* AI */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-bold">AI Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground font-medium">Enable AI Sentiment Filter</span>
                <Switch
                  checked={aiSettings.use_ai_filter}
                  onCheckedChange={(v) => setAiSettings({ ...aiSettings, use_ai_filter: v })}
                />
              </div>
              <ParamSlider label="Confidence Threshold" value={aiSettings.confidence_threshold}
                min={0.5} max={0.9} step={0.05}
                onChange={(v) => setAiSettings({ ...aiSettings, confidence_threshold: v })} />
              <p className="text-xs text-muted-foreground font-medium">
                Only apply filter when AI confidence exceeds this threshold
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <Button
          onClick={handleSave}
          className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale"
        >
          {saved ? <Check className="size-4 mr-1.5" /> : <Save className="size-4 mr-1.5" />}
          {saved ? `Saved for ${activeSymbol}!` : `Save Strategy (${activeSymbol})`}
        </Button>
        <Button onClick={handleBacktest} variant="secondary" disabled={loading} className="rounded-full">
          <FlaskConical className="size-4 mr-1.5" />
          {loading ? "Running..." : "Quick Backtest"}
        </Button>
      </div>

      {/* Backtest Results */}
      {backtestResult && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard icon={BarChart3} label="Total Trades" value={backtestResult.total_trades as number} />
          <StatCard icon={TrendingUp} label="Win Rate"
            value={`${((backtestResult.win_rate as number) * 100).toFixed(1)}%`}
            variant={(backtestResult.win_rate as number) > 0.5 ? "success" : "danger"} />
          <StatCard icon={Target} label="Profit Factor"
            value={(backtestResult.profit_factor as number).toFixed(2)}
            variant={(backtestResult.profit_factor as number) > 1.5 ? "success" : "warning"} />
          <StatCard icon={AlertTriangle} label="Max Drawdown"
            value={`${((backtestResult.max_drawdown as number) * 100).toFixed(1)}%`}
            variant="danger" />
        </div>
      )}
    </div>
  );
}

function ParamSlider({
  label, value, min, max, step = 1, onChange,
}: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground font-medium">{label}</span>
        <span className="text-xs font-mono bg-accent text-accent-foreground px-2 py-0.5 rounded-lg font-bold">
          {value}
        </span>
      </div>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])} />
      <div className="flex justify-between text-[10px] text-muted-foreground/50 font-medium">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
