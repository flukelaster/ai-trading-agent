"use client";

import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Brain, Play, Zap, BarChart3, Target, TrendingUp, Database, CheckCircle2, XCircle, ChevronDown, ChevronUp } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { trainModel, getModelStatus, mlPredict, getDataStatus, collectData, getSymbols } from "@/lib/api";
import { SymbolTabs } from "@/components/ui/symbol-tabs";

type SymbolInfo = {
  symbol: string; display_name: string; state: string; timeframe?: string;
  ml_tp_pips?: number; ml_sl_pips?: number; ml_forward_bars?: number; ml_timeframe?: string;
};

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export default function MLPage() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [activeSymbol, setActiveSymbol] = useState("GOLD");
  const [modelStatus, setModelStatus] = useState<Record<string, unknown> | null>(null);
  const [dataStatus, setDataStatus] = useState<Record<string, unknown>[]>([]);
  const [prediction, setPrediction] = useState<Record<string, unknown> | null>(null);
  const [trainResult, setTrainResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [collectResult, setCollectResult] = useState<{ total_bars_fetched: number; new_bars_inserted: number } | null>(null);
  const [collectError, setCollectError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [collectTimeframe, setCollectTimeframe] = useState("M15");
  const [trainTimeframe, setTrainTimeframe] = useState("M15");
  const [trainFrom, setTrainFrom] = useState("2025-04-01");
  const [trainTo, setTrainTo] = useState(new Date().toISOString().split("T")[0]);
  const [forwardBars, setForwardBars] = useState(10);
  const [tpPips, setTpPips] = useState(5.0);
  const [slPips, setSlPips] = useState(5.0);
  const [collectFrom, setCollectFrom] = useState("2025-04-01");
  const [collectTo, setCollectTo] = useState(new Date().toISOString().split("T")[0]);

  useEffect(() => {
    getSymbols().then(res => {
      if (res.data?.symbols) setSymbols(res.data.symbols);
    }).catch(() => {});
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, dataRes] = await Promise.all([
        getModelStatus(activeSymbol).catch(() => null),
        getDataStatus(activeSymbol).catch(() => null),
      ]);
      if (statusRes) setModelStatus(statusRes.data);
      if (dataRes) setDataStatus(Array.isArray(dataRes.data) ? dataRes.data : []);
    } catch { /* handled */ }
    finally { setLoading(false); }
  }, [activeSymbol]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    setTrainResult(null);
    setPrediction(null);
    setCollectResult(null);
    setCollectError(null);
  }, [activeSymbol]);

  useEffect(() => {
    const info = symbols.find((s) => s.symbol === activeSymbol);
    if (info?.ml_tp_pips) setTpPips(info.ml_tp_pips);
    if (info?.ml_sl_pips) setSlPips(info.ml_sl_pips);
    if (info?.ml_forward_bars) setForwardBars(info.ml_forward_bars);

    const symbolData = dataStatus.filter((d) => (d.symbol as string) === activeSymbol);
    if (symbolData.length > 0) {
      const best = symbolData.reduce((a, b) =>
        (a.bar_count as number) > (b.bar_count as number) ? a : b
      );
      const dataTf = best.timeframe as string;
      setCollectTimeframe(dataTf);
      setTrainTimeframe(dataTf);
    } else if (info?.ml_timeframe) {
      setCollectTimeframe(info.ml_timeframe);
      setTrainTimeframe(info.ml_timeframe);
    } else if (info?.timeframe) {
      setCollectTimeframe(info.timeframe);
      setTrainTimeframe(info.timeframe);
    }
  }, [activeSymbol, symbols, dataStatus]);

  const handleCollect = async () => {
    setCollecting(true);
    setCollectResult(null);
    setCollectError(null);
    try {
      const res = await collectData({ symbol: activeSymbol, timeframe: collectTimeframe, from_date: collectFrom, to_date: collectTo });
      setCollectResult(res.data);
      await fetchData();
    } catch (e) {
      setCollectError((e as Error).message || "Collection failed");
    } finally { setCollecting(false); }
  };

  const handleTrain = async () => {
    setTraining(true);
    setTrainResult(null);
    try {
      const res = await trainModel({ symbol: activeSymbol, timeframe: trainTimeframe, from_date: trainFrom, to_date: trainTo, forward_bars: forwardBars, tp_pips: tpPips, sl_pips: slPips });
      setTrainResult(res.data);
      await fetchData();
    } catch (e: unknown) {
      let msg = "Training failed";
      if (e && typeof e === "object" && "response" in e) {
        const resp = (e as { response: { data?: { detail?: unknown }; status?: number } }).response;
        const detail = resp?.data?.detail;
        if (typeof detail === "string") msg = detail;
        else if (Array.isArray(detail)) msg = detail.map((d: { msg?: string; loc?: string[] }) => `${d.loc?.join(".")}: ${d.msg}`).join("; ");
        else msg = `Server error (${resp?.status || "unknown"})`;
      } else if (e instanceof Error) msg = e.message;
      setTrainResult({ error: msg });
    } finally { setTraining(false); }
  };

  const handlePredict = async () => {
    setPredicting(true);
    try {
      const res = await mlPredict(activeSymbol);
      setPrediction(res.data);
    } catch { /* handled */ }
    finally { setPredicting(false); }
  };

  if (loading) {
    return (
      <div className="p-4 lg:p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-60 rounded-xl" />
      </div>
    );
  }

  const hasModel = modelStatus?.status === "ready";
  const fi = (modelStatus?.feature_importance_top10 || {}) as Record<string, number>;
  const fiEntries = Object.entries(fi).sort(([, a], [, b]) => b - a);
  const fiMax = fiEntries.length > 0 ? fiEntries[0][1] : 1;
  const activeSymbolInfo = symbols.find((s) => s.symbol === activeSymbol);
  const totalBars = dataStatus.reduce((sum, d) => sum + (d.bar_count as number), 0);

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader title="ML Model" subtitle="Train and manage LightGBM signal model per symbol" />

      <PageInstructions
        pageId="ml"
        items={[
          "Step 1: Collect Data — Fetch historical bars from MT5 into the database for your chosen symbol and timeframe.",
          "Step 2: Train Model — Train a LightGBM classifier on collected data. Adjust TP/SL pips and forward bars in Advanced Parameters.",
          "Step 3: Predict — Run the trained model on latest market data to get a buy/sell/hold signal with confidence score.",
        ]}
      />

      <SymbolTabs symbols={symbols} active={activeSymbol} onSelect={setActiveSymbol} />

      {/* ─── Step 1: Data ──────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center size-7 rounded-full bg-primary/10 text-primary text-xs font-bold">1</div>
          <h2 className="text-sm font-bold">Collect Data</h2>
          {totalBars > 0 && (
            <span className="text-xs text-muted-foreground ml-auto">
              {totalBars.toLocaleString()} bars collected
            </span>
          )}
        </div>

        {/* Data summary chips */}
        {dataStatus.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {dataStatus.map((d, i) => (
              <div key={i} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs">
                <span className="font-semibold">{d.timeframe as string}</span>
                <span className="text-muted-foreground">{(d.bar_count as number).toLocaleString()} bars</span>
              </div>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-border bg-card p-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 items-end">
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">From</label>
              <Input type="date" value={collectFrom} onChange={(e) => setCollectFrom(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">To</label>
              <Input type="date" value={collectTo} onChange={(e) => setCollectTo(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">Timeframe</label>
              <Select value={collectTimeframe} onValueChange={(v) => v && setCollectTimeframe(v)}>
                <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIMEFRAMES.map(tf => <SelectItem key={tf} value={tf}>{tf}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleCollect} disabled={collecting} className="rounded-lg font-medium">
              <Database className="size-4 mr-1.5" />
              {collecting ? "Collecting..." : "Collect"}
            </Button>
          </div>

          {collectResult && (
            <div className="flex items-center gap-2 mt-3 text-xs text-green-400">
              <CheckCircle2 className="size-3.5" />
              {collectResult.total_bars_fetched.toLocaleString()} fetched, {collectResult.new_bars_inserted.toLocaleString()} new
            </div>
          )}
          {collectError && (
            <div className="flex items-center gap-2 mt-3 text-xs text-red-400">
              <XCircle className="size-3.5" />
              {collectError}
            </div>
          )}
        </div>
      </section>

      {/* ─── Step 2: Train ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center size-7 rounded-full bg-primary/10 text-primary text-xs font-bold">2</div>
          <h2 className="text-sm font-bold">Train Model</h2>
          {hasModel && (
            <Badge className="ml-auto bg-green-500/10 text-green-400 border-green-500/20 text-xs rounded-full">
              Model Ready
            </Badge>
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-4 space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 items-end">
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">Train From</label>
              <Input type="date" value={trainFrom} onChange={(e) => setTrainFrom(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">Train To</label>
              <Input type="date" value={trainTo} onChange={(e) => setTrainTo(e.target.value)} className="text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground font-medium">Timeframe</label>
              <Select value={trainTimeframe} onValueChange={(v) => v && setTrainTimeframe(v)}>
                <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIMEFRAMES.map(tf => <SelectItem key={tf} value={tf}>{tf}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Advanced params — collapsible */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {showAdvanced ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
            Advanced Parameters
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">Forward Bars</label>
                <Input type="number" value={forwardBars} onChange={(e) => setForwardBars(parseInt(e.target.value) || 10)} className="text-sm" />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">TP (pips)</label>
                <Input type="number" step="0.5" value={tpPips} onChange={(e) => setTpPips(parseFloat(e.target.value) || 5)} className="text-sm" />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">SL (pips)</label>
                <Input type="number" step="0.5" value={slPips} onChange={(e) => setSlPips(parseFloat(e.target.value) || 5)} className="text-sm" />
              </div>
            </div>
          )}

          <Button onClick={handleTrain} disabled={training || dataStatus.length === 0} className="w-full rounded-lg font-medium">
            <Play className="size-4 mr-1.5" />
            {training ? "Training..." : `Train ${activeSymbol} Model`}
          </Button>
          {dataStatus.length === 0 && (
            <p className="text-xs text-muted-foreground text-center">Collect data first (Step 1)</p>
          )}
        </div>

        {/* Train Result */}
        {trainResult && !("error" in trainResult) && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { icon: Target, label: "Accuracy", value: `${((trainResult.accuracy as number) * 100).toFixed(1)}%`, color: (trainResult.accuracy as number) > 0.4 ? "text-green-400" : "text-amber-400" },
              { icon: BarChart3, label: "Train Size", value: (trainResult.train_size as number).toLocaleString(), color: "text-blue-400" },
              { icon: TrendingUp, label: "Test Size", value: (trainResult.test_size as number).toLocaleString(), color: "text-purple-400" },
              { icon: Brain, label: "Top Feature", value: Object.keys((trainResult.feature_importance_top15 as Record<string, number>) || {})[0] || "N/A", color: "text-amber-400" },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-border bg-card p-3">
                <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                  <s.icon className="size-3.5" />
                  <span className="text-[11px] font-medium">{s.label}</span>
                </div>
                <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
              </div>
            ))}
          </div>
        )}
        {trainResult && "error" in trainResult && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 text-sm text-red-400">
            {String(trainResult.error)}
          </div>
        )}
      </section>

      {/* ─── Step 3: Model Status + Predict ───────────────────────── */}
      {hasModel && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center size-7 rounded-full bg-primary/10 text-primary text-xs font-bold">3</div>
            <h2 className="text-sm font-bold">Model & Predict</h2>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Feature Importance */}
            <div className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Top Features</h3>
                <span className="text-[11px] text-muted-foreground">
                  {modelStatus?.timeframe as string} | {modelStatus?.train_period as string}
                </span>
              </div>
              <div className="space-y-2">
                {fiEntries.slice(0, 8).map(([name, val]) => (
                  <div key={name} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-32 truncate font-mono">{name}</span>
                    <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${(val / fiMax) * 100}%` }} />
                    </div>
                    <span className="text-[10px] text-muted-foreground w-8 text-right">{(val * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Predict */}
            <div className="rounded-xl border border-border bg-card p-4 space-y-4">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Live Prediction</h3>

              <Button onClick={handlePredict} disabled={predicting} variant="outline" className="w-full rounded-lg">
                <Zap className="size-4 mr-1.5" />
                {predicting ? "Predicting..." : "Run Prediction"}
              </Button>

              {prediction && !prediction.error && (
                <div className="rounded-lg border border-border p-4 text-center space-y-2">
                  <Badge className={`text-base px-4 py-1 rounded-full ${
                    prediction.signal === "BUY" ? "bg-green-500/10 text-green-400 border-green-500/20" :
                    prediction.signal === "SELL" ? "bg-red-500/10 text-red-400 border-red-500/20" :
                    "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"
                  }`}>
                    {prediction.signal as string}
                  </Badge>
                  <p className="text-sm text-muted-foreground">
                    Confidence: <span className="font-bold text-foreground">{((prediction.confidence as number) * 100).toFixed(1)}%</span>
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {new Date(prediction.timestamp as string).toLocaleString("en-GB", { timeZone: "Asia/Bangkok" })}
                  </p>
                </div>
              )}
              {prediction && "error" in prediction && (
                <p className="text-sm text-red-400">{String(prediction.error)}</p>
              )}
              {!prediction && (
                <p className="text-xs text-muted-foreground text-center py-4">
                  Run a prediction to see the model&apos;s current signal
                </p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
