"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkles, Brain, BarChart3, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { GoldGauge } from "@/components/ui/gold-gauge";
import SentimentBadge from "@/components/ai/SentimentBadge";
import OptimizationReport from "@/components/ai/OptimizationReport";
import { SymbolTabs } from "@/components/ui/symbol-tabs";
import { useBotStore } from "@/store/botStore";
import {
  getLatestSentiment, getSentimentHistory, getOptimizationReport,
  runOptimization, applyOptimization, getBotStatus,
} from "@/lib/api";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

export default function InsightsPage() {
  const { symbols } = useBotStore();
  const [activeSymbol, setActiveSymbol] = useState("GOLD");

  useEffect(() => {
    if (symbols.length > 0 && !symbols.some(s => s.symbol === activeSymbol)) {
      setActiveSymbol(symbols[0].symbol);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols]);
  const [sentiment, setSentiment] = useState<{
    label: string; score: number; confidence: number; key_factors: string[]; analyzed_at: string; symbol?: string;
  } | null>(null);
  const [history, setHistory] = useState<{ sentiment_score: number; created_at: string }[]>([]);
  const [optimization, setOptimization] = useState<Record<string, unknown> | null>(null);
  const [botRunning, setBotRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [sentRes, histRes, optRes, statusRes] = await Promise.all([
        getLatestSentiment(activeSymbol), getSentimentHistory(7), getOptimizationReport(), getBotStatus(),
      ]);
      setSentiment(sentRes.data);
      setHistory(histRes.data.history || []);
      setOptimization(optRes.data);
      setBotRunning(statusRes.data.state === "RUNNING");
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [activeSymbol]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRunOptimization = async () => {
    setOptimizing(true);
    setOptimizeError(null);
    try {
      const res = await runOptimization();
      setOptimization(res.data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Optimization failed";
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setOptimizeError(detail || msg);
    } finally {
      setOptimizing(false);
    }
  };
  const handleApply = async (logId: number) => {
    if (confirm("Apply suggested parameters?")) {
      try { await applyOptimization(logId); await fetchData(); } catch { /* handled by axios interceptor */ }
    }
  };

  const chartData = [...history].reverse().map((h) => ({
    time: new Date(h.created_at).toLocaleDateString("en-GB", { timeZone: "Asia/Bangkok", month: "short", day: "numeric", hour: "2-digit" }),
    score: h.sentiment_score,
  }));

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-80 rounded-2xl" />
          <Skeleton className="h-80 rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      <PageHeader title="AI Insights" subtitle="Sentiment analysis and strategy optimization" />

      <PageInstructions
        items={[
          "Select a symbol to view its AI sentiment analysis — from bearish to bullish with confidence score.",
          "Run Optimization lets AI suggest strategy parameter improvements based on recent trade performance.",
        ]}
      />

      <SymbolTabs symbols={symbols} active={activeSymbol} onSelect={setActiveSymbol} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Sentiment */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Brain className="size-4 text-primary-foreground dark:text-primary" />
              {activeSymbol} Sentiment
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {sentiment ? (
              <>
                <div className="flex justify-center pt-2">
                  <GoldGauge value={sentiment.score} label={sentiment.label} size={200} />
                </div>

                <div className="flex justify-center">
                  <SentimentBadge label={sentiment.label} score={sentiment.score} confidence={sentiment.confidence} size="lg" />
                </div>

                {sentiment.key_factors.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground font-semibold">Key Factors</p>
                    <div className="flex flex-wrap gap-2">
                      {sentiment.key_factors.map((f, i) => (
                        <span key={i} className="text-xs border border-border bg-card px-3 py-1.5 rounded-full text-foreground font-medium">
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <p className="text-[11px] text-muted-foreground/60 text-center font-medium">
                  Updated: {new Date(sentiment.analyzed_at).toLocaleString("en-GB", { timeZone: "Asia/Bangkok" })}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-12 font-medium">
                No sentiment data available
              </p>
            )}
          </CardContent>
        </Card>

        {/* History Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold">Sentiment History (7 days)</CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="sentimentGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#9fe870" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="#9fe870" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="time" className="fill-muted-foreground" fontSize={10} />
                  <YAxis domain={[-1, 1]} className="fill-muted-foreground" fontSize={10} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "var(--popover)",
                      border: "1px solid var(--border)",
                      borderRadius: "12px",
                      color: "var(--foreground)",
                    }}
                  />
                  <ReferenceLine y={0.3} stroke="#054d28" strokeDasharray="3 3" strokeOpacity={0.3} />
                  <ReferenceLine y={-0.3} stroke="#d03238" strokeDasharray="3 3" strokeOpacity={0.3} />
                  <ReferenceLine y={0} className="stroke-muted-foreground" strokeDasharray="3 3" strokeOpacity={0.5} />
                  <Area type="monotone" dataKey="score" stroke="#9fe870" strokeWidth={2} fill="url(#sentimentGradient)" dot={{ fill: "#9fe870", r: 2 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-20 font-medium">
                No history data
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Optimization */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          {optimization && optimization.suggested_params ? (
            <OptimizationReport
              assessment={(optimization.assessment as string) || (optimization.rationale as string) || ""}
              currentParams={(optimization.current_params as Record<string, number>) || {}}
              suggestedParams={(optimization.suggested_params as Record<string, number>) || {}}
              confidence={(optimization.confidence as number) || 0}
              reasoning={(optimization.reasoning as string) || (optimization.rationale as string) || ""}
              logId={(optimization.log_id as number) || (optimization.id as number) || null}
              applied={(optimization.applied as boolean) || false}
              botRunning={botRunning}
              onApply={handleApply}
            />
          ) : (
            <Card>
              <CardContent className="py-12 text-center space-y-4">
                <Sparkles className="size-10 text-muted-foreground/40 mx-auto" />
                <p className="text-sm text-muted-foreground font-medium">
                  {optimizing ? "AI is analyzing your recent trades..." : "No optimization runs yet"}
                </p>
                <Button
                  onClick={handleRunOptimization}
                  disabled={optimizing}
                  className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale"
                >
                  {optimizing ? (
                    <Loader2 className="size-4 mr-1.5 animate-spin" />
                  ) : (
                    <Sparkles className="size-4 mr-1.5" />
                  )}
                  {optimizing ? "Optimizing..." : "Run Optimization"}
                </Button>
                {optimizeError && (
                  <p className="text-xs text-red-400 font-medium">{optimizeError}</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <BarChart3 className="size-4 text-primary-foreground dark:text-primary" />
              AI Performance Attribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 space-y-3">
              <BarChart3 className="size-10 text-muted-foreground/20" />
              <p className="text-sm text-muted-foreground text-center max-w-xs font-medium">
                Performance attribution will appear after enough trades with AI filter enabled
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
