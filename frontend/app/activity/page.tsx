"use client";

import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import api from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface ActivityItem {
  id: string;
  timestamp: string;
  category: string;
  type: string;
  title: string;
  message: string;
  source: string;
  meta?: Record<string, unknown>;
}

interface Summary {
  total_events: number;
  sentiment_analyses: number;
  ai_trades: number;
  optimization_runs: number;
}

// ─── Constants ──────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; dot: string; bg: string }> = {
  trade:        { label: "Trade",        color: "text-green-400",  dot: "bg-green-400",  bg: "bg-green-500/10" },
  signal:       { label: "Signal",       color: "text-blue-400",   dot: "bg-blue-400",   bg: "bg-blue-500/10" },
  sentiment:    { label: "Sentiment",    color: "text-amber-400",  dot: "bg-amber-400",  bg: "bg-amber-500/10" },
  optimization: { label: "Optimization", color: "text-purple-400", dot: "bg-purple-400", bg: "bg-purple-500/10" },
  risk:         { label: "Risk",         color: "text-red-400",    dot: "bg-red-400",    bg: "bg-red-500/10" },
  error:        { label: "Error",        color: "text-red-400",    dot: "bg-red-400",    bg: "bg-red-500/10" },
  system:       { label: "System",       color: "text-zinc-400",   dot: "bg-zinc-400",   bg: "bg-zinc-500/10" },
};

const CATEGORIES = ["", "trade", "signal", "sentiment", "optimization", "risk", "error", "system"];

// ─── Helpers ────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function ActivityPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [category, setCategory] = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { days, limit: 200 };
      if (category) params.category = category;

      const [actRes, sumRes] = await Promise.all([
        api.get("/api/ai/activity", { params }),
        api.get("/api/ai/activity/summary", { params: { days } }),
      ]);
      setItems(actRes.data.items || []);
      setSummary(sumRes.data);
      setLastRefresh(new Date());
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [days, category]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Group items by date
  const grouped: Record<string, ActivityItem[]> = {};
  for (const item of items) {
    const dateKey = new Date(item.timestamp).toLocaleDateString("en-GB", {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
    (grouped[dateKey] ??= []).push(item);
  }

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader title="AI Activity" subtitle="Timeline of AI decisions, analyses, and actions">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            type="button"
            onClick={fetchData}
            disabled={loading}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </PageHeader>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Bot Events", value: summary.total_events, color: "text-blue-400" },
            { label: "Sentiment Runs", value: summary.sentiment_analyses, color: "text-amber-400" },
            { label: "AI Trades", value: summary.ai_trades, color: "text-green-400" },
            { label: "Optimizations", value: summary.optimization_runs, color: "text-purple-400" },
          ].map((s) => (
            <div key={s.label} className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className={`text-2xl font-bold mt-1 ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          <option value={1}>Last 24h</option>
          <option value={3}>Last 3 days</option>
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
        </select>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="">All categories</option>
          {CATEGORIES.filter(Boolean).map((c) => (
            <option key={c} value={c}>
              {CATEGORY_CONFIG[c]?.label || c}
            </option>
          ))}
        </select>

        <span className="text-xs text-muted-foreground self-center ml-auto">
          {items.length} events
        </span>
      </div>

      {/* Timeline */}
      {loading ? (
        <div className="text-center py-12 text-muted-foreground">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          No AI activity found for this period
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(grouped).map(([date, dateItems]) => (
            <div key={date}>
              <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground/60 mb-3 sticky top-0 bg-background py-1 z-10">
                {date}
              </h3>
              <div className="relative pl-6 border-l border-border/40 space-y-1">
                {dateItems.map((item) => {
                  const cfg = CATEGORY_CONFIG[item.category] || CATEGORY_CONFIG.system;
                  return (
                    <div key={item.id} className="relative group">
                      {/* Timeline dot */}
                      <div className={`absolute -left-[25px] top-3 size-2 rounded-full ${cfg.dot} ring-2 ring-background`} />

                      <div className="rounded-lg px-4 py-3 hover:bg-card/50 transition-colors">
                        <div className="flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.color}`}>
                                {cfg.label}
                              </span>
                              <span className="text-sm font-medium text-foreground">
                                {item.title}
                              </span>
                            </div>
                            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                              {item.message}
                            </p>
                          </div>
                          <div className="text-right shrink-0">
                            <p className="text-xs text-muted-foreground">{timeAgo(item.timestamp)}</p>
                            <p className="text-[10px] text-muted-foreground/50 mt-0.5">{formatTime(item.timestamp)}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
