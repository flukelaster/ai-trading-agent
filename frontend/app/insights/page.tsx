"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkles, Brain, BarChart3 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { GoldGauge } from "@/components/ui/gold-gauge";
import SentimentBadge from "@/components/ai/SentimentBadge";
import OptimizationReport from "@/components/ai/OptimizationReport";
import {
  getLatestSentiment,
  getSentimentHistory,
  getOptimizationReport,
  runOptimization,
  applyOptimization,
  getBotStatus,
} from "@/lib/api";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

export default function InsightsPage() {
  const [sentiment, setSentiment] = useState<{
    label: string; score: number; confidence: number; key_factors: string[]; analyzed_at: string;
  } | null>(null);
  const [history, setHistory] = useState<{ sentiment_score: number; created_at: string }[]>([]);
  const [optimization, setOptimization] = useState<Record<string, unknown> | null>(null);
  const [botRunning, setBotRunning] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [sentRes, histRes, optRes, statusRes] = await Promise.all([
        getLatestSentiment(), getSentimentHistory(7), getOptimizationReport(), getBotStatus(),
      ]);
      setSentiment(sentRes.data);
      setHistory(histRes.data.history || []);
      setOptimization(optRes.data);
      setBotRunning(statusRes.data.state === "RUNNING");
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRunOptimization = async () => {
    try { const res = await runOptimization(); setOptimization(res.data); } catch (e) { console.error(e); }
  };
  const handleApply = async (logId: number) => {
    if (confirm("Apply suggested parameters?")) {
      await applyOptimization(logId);
      fetchData();
    }
  };

  const chartData = [...history].reverse().map((h) => ({
    time: new Date(h.created_at).toLocaleDateString("en", { month: "short", day: "numeric", hour: "2-digit" }),
    score: h.sentiment_score,
  }));

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="AI Insights" subtitle="Sentiment analysis and strategy optimization" />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Sentiment */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Brain className="size-4 text-primary" />
              Current Sentiment
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {sentiment ? (
              <>
                <div className="flex justify-center pt-2">
                  <GoldGauge
                    value={sentiment.score}
                    label={sentiment.label}
                    size={200}
                  />
                </div>

                <div className="flex justify-center">
                  <SentimentBadge
                    label={sentiment.label}
                    score={sentiment.score}
                    confidence={sentiment.confidence}
                    size="lg"
                  />
                </div>

                {sentiment.key_factors.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">Key Factors</p>
                    <div className="flex flex-wrap gap-2">
                      {sentiment.key_factors.map((f, i) => (
                        <span
                          key={i}
                          className="text-xs glass glass-border px-3 py-1.5 rounded-full text-foreground"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <p className="text-[11px] text-muted-foreground/60 text-center">
                  Updated: {new Date(sentiment.analyzed_at).toLocaleString()}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-12">
                No sentiment data available
              </p>
            )}
          </CardContent>
        </Card>

        {/* History Chart */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm">Sentiment History (7 days)</CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="sentimentGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="oklch(0.80 0.15 85)" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="oklch(0.80 0.15 85)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 6%)" />
                  <XAxis dataKey="time" stroke="oklch(0.60 0.01 250)" fontSize={10} />
                  <YAxis domain={[-1, 1]} stroke="oklch(0.60 0.01 250)" fontSize={10} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.16 0.008 250 / 90%)",
                      border: "1px solid oklch(1 0 0 / 8%)",
                      borderRadius: "8px",
                      backdropFilter: "blur(12px)",
                    }}
                    labelStyle={{ color: "oklch(0.60 0.01 250)" }}
                    itemStyle={{ color: "oklch(0.93 0.01 80)" }}
                  />
                  <ReferenceLine y={0.3} stroke="#4ade80" strokeDasharray="3 3" strokeOpacity={0.3} />
                  <ReferenceLine y={-0.3} stroke="#f87171" strokeDasharray="3 3" strokeOpacity={0.3} />
                  <ReferenceLine y={0} stroke="oklch(0.60 0.01 250)" strokeDasharray="3 3" strokeOpacity={0.5} />
                  <Area
                    type="monotone"
                    dataKey="score"
                    stroke="oklch(0.80 0.15 85)"
                    strokeWidth={2}
                    fill="url(#sentimentGradient)"
                    dot={{ fill: "oklch(0.80 0.15 85)", r: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-20">
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
              assessment={(optimization.rationale as string) || ""}
              currentParams={(optimization.current_params as Record<string, number>) || {}}
              suggestedParams={(optimization.suggested_params as Record<string, number>) || {}}
              confidence={(optimization.confidence as number) || 0}
              reasoning={(optimization.rationale as string) || ""}
              logId={(optimization.id as number) || null}
              applied={(optimization.applied as boolean) || false}
              botRunning={botRunning}
              onApply={handleApply}
            />
          ) : (
            <Card className="bg-card border-border">
              <CardContent className="py-12 text-center space-y-4">
                <Sparkles className="size-10 text-primary/40 mx-auto" />
                <p className="text-sm text-muted-foreground">No optimization runs yet</p>
                <Button
                  onClick={handleRunOptimization}
                  className="gold-gradient text-gold-foreground font-semibold hover:opacity-90"
                >
                  <Sparkles className="size-4 mr-1.5" />
                  Run Optimization
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart3 className="size-4 text-primary" />
              AI Performance Attribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 space-y-3">
              <BarChart3 className="size-10 text-muted-foreground/20" />
              <p className="text-sm text-muted-foreground text-center max-w-xs">
                Performance attribution will appear after enough trades with AI filter enabled
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
