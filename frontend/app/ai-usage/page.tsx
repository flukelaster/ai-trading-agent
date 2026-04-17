"use client";

import { useEffect, useState, useCallback } from "react";
import Image from "next/image";
import { Zap, Activity, DollarSign, Database, TrendingUp, Cpu } from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from "recharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import {
  getAIUsageSummary,
  getAIUsageTimeseries,
  getAIUsageBreakdown,
  getAIUsageRecent,
} from "@/lib/api";
import { showError } from "@/lib/toast";

interface Summary {
  total_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_write: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_cost_per_call: number;
  success_rate: number;
  models: Record<string, { calls: number; tokens: number; cost_usd: number }>;
  agents: Record<string, { calls: number; tokens: number; cost_usd: number }>;
  period_days: number;
}

interface TimeseriesBucket {
  date: string;
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_write: number;
  cost_usd: number;
  calls: number;
}

interface BreakdownRow {
  agent_id: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_write: number;
  cost_usd: number;
  avg_duration_ms: number;
  tool_calls: number;
  success_rate: number;
}

interface RecentRow {
  id: number;
  timestamp: string;
  agent_id: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_write: number;
  total_tokens: number;
  cost_usd: number;
  duration_ms: number;
  turns: number;
  tool_calls_count: number;
  success: boolean;
}

const AGENT_CHARACTER: Record<string, string> = {
  orchestrator: "/agent-characters/Orchestrator.png",
  technical_analyst: "/agent-characters/Technical Analyst.png",
  fundamental_analyst: "/agent-characters/Fundamental Analyst.png",
  risk_analyst: "/agent-characters/Risk Analyst.png",
  reflector: "/agent-characters/Reflector.png",
  sentiment: "/agent-characters/Sentiment Analyzer.png",
  optimization: "/agent-characters/Strategy Optimizer.png",
  single_agent: "/agent-characters/Single Agent Agent.png",
};

const MODEL_LABEL: Record<string, string> = {
  "claude-sonnet-4-20250514": "Sonnet",
  "claude-haiku-4-5-20251001": "Haiku",
};

const MODEL_COLOR: Record<string, string> = {
  "claude-sonnet-4-20250514": "text-blue-400 border-blue-500/40 bg-blue-500/10",
  "claude-haiku-4-5-20251001": "text-amber-400 border-amber-500/40 bg-amber-500/10",
};

const DAYS_OPTIONS = [1, 7, 30, 90];

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

function formatCost(n: number): string {
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function AIUsagePage() {
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [series, setSeries] = useState<TimeseriesBucket[]>([]);
  const [breakdown, setBreakdown] = useState<BreakdownRow[]>([]);
  const [recent, setRecent] = useState<RecentRow[]>([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, tsRes, bdRes, rcRes] = await Promise.all([
        getAIUsageSummary(days),
        getAIUsageTimeseries(days, "day"),
        getAIUsageBreakdown(days),
        getAIUsageRecent(50),
      ]);
      setSummary(sumRes.data);
      setSeries(tsRes.data.series || []);
      setBreakdown(bdRes.data.items || []);
      setRecent(rcRes.data.items || []);
    } catch {
      showError("Failed to load AI usage data");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="AI Usage" subtitle="Token consumption and equivalent API cost per agent">
        <div className="flex gap-1">
          {DAYS_OPTIONS.map((d) => (
            <Button
              key={d}
              variant={days === d ? "default" : "outline"}
              size="sm"
              onClick={() => setDays(d)}
              className="text-xs"
            >
              {d === 1 ? "24h" : `${d}d`}
            </Button>
          ))}
        </div>
      </PageHeader>

      <PageInstructions
        items={[
          "Cost shown is the equivalent Anthropic API cost — actual billing uses the Max subscription flat rate.",
          "Agents using Sonnet cost 3x more than Haiku for the same tokens. Heavy agents are candidates for Haiku.",
          "Logs older than 90 days are auto-deleted daily at 03:00 UTC.",
        ]}
      />

      {/* Stats Cards */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            icon={Activity}
            label="Total Calls"
            value={summary?.total_calls.toLocaleString() ?? "0"}
            subtitle={`${Math.round((summary?.success_rate ?? 0) * 100)}% success`}
          />
          <StatCard
            icon={Database}
            label="Total Tokens"
            value={formatNumber(summary?.total_tokens ?? 0)}
            subtitle={`I:${formatNumber(summary?.input_tokens ?? 0)} O:${formatNumber(summary?.output_tokens ?? 0)} CR:${formatNumber(summary?.cache_read ?? 0)} CW:${formatNumber(summary?.cache_write ?? 0)}`}
          />
          <StatCard
            icon={DollarSign}
            label="Total Cost (USD)"
            value={formatCost(summary?.total_cost_usd ?? 0)}
            subtitle={`${days}d equivalent API cost`}
            variant="gold"
          />
          <StatCard
            icon={TrendingUp}
            label="Avg Cost / Call"
            value={formatCost(summary?.avg_cost_per_call ?? 0)}
            subtitle={`${summary?.total_calls ?? 0} calls`}
          />
        </div>
      )}

      {/* Charts */}
      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      ) : series.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <EmptyState
            icon={Zap}
            heading="No AI activity yet"
            description="Agent calls will appear here after the next analysis."
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3">Tokens by day</h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#a1a1aa" />
                <YAxis tick={{ fontSize: 10 }} stroke="#a1a1aa" tickFormatter={formatNumber} />
                <Tooltip
                  contentStyle={{
                    background: "rgba(10,10,10,0.95)",
                    border: "1px solid #27272a",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  formatter={(v) => formatNumber(Number(v))}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="input_tokens" stackId="a" fill="#3b82f6" name="Input" />
                <Bar dataKey="output_tokens" stackId="a" fill="#9fe870" name="Output" />
                <Bar dataKey="cache_read" stackId="a" fill="#f59e0b" name="Cache Read" />
                <Bar dataKey="cache_write" stackId="a" fill="#a855f7" name="Cache Write" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="rounded-xl border border-border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3">Cost by day (USD)</h3>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#a1a1aa" />
                <YAxis tick={{ fontSize: 10 }} stroke="#a1a1aa" tickFormatter={(v) => `$${v.toFixed(2)}`} />
                <Tooltip
                  contentStyle={{
                    background: "rgba(10,10,10,0.95)",
                    border: "1px solid #27272a",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  formatter={(v) => formatCost(Number(v))}
                />
                <Line type="monotone" dataKey="cost_usd" stroke="#9fe870" strokeWidth={2} dot={{ r: 3 }} name="Cost" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Agent breakdown */}
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Cpu className="size-4" />
          Breakdown by agent
        </h3>
        {loading ? (
          <Skeleton className="h-40" />
        ) : breakdown.length === 0 ? (
          <p className="text-xs text-muted-foreground py-4 text-center">No agent activity yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2 px-2 font-medium">Agent</th>
                  <th className="text-left py-2 px-2 font-medium">Model</th>
                  <th className="text-right py-2 px-2 font-medium">Calls</th>
                  <th className="text-right py-2 px-2 font-medium">Input</th>
                  <th className="text-right py-2 px-2 font-medium">Output</th>
                  <th className="text-right py-2 px-2 font-medium">Cache R/W</th>
                  <th className="text-right py-2 px-2 font-medium">Tools</th>
                  <th className="text-right py-2 px-2 font-medium">Avg ms</th>
                  <th className="text-right py-2 px-2 font-medium">Cost (USD)</th>
                </tr>
              </thead>
              <tbody>
                {breakdown.map((b, i) => (
                  <tr key={`${b.agent_id}-${b.model}-${i}`} className="border-b border-border/50 hover:bg-muted/20">
                    <td className="py-2 px-2">
                      <div className="flex items-center gap-2">
                        {AGENT_CHARACTER[b.agent_id] && (
                          <div className="relative size-8 shrink-0 rounded-sm overflow-hidden bg-muted/30">
                            <Image
                              src={AGENT_CHARACTER[b.agent_id]}
                              alt={b.agent_id}
                              fill
                              sizes="32px"
                              className="object-contain p-0.5"
                            />
                          </div>
                        )}
                        <span className="font-mono">{b.agent_id}</span>
                      </div>
                    </td>
                    <td className="py-2 px-2">
                      <Badge variant="outline" className={`text-[9px] ${MODEL_COLOR[b.model] ?? ""}`}>
                        {MODEL_LABEL[b.model] ?? b.model}
                      </Badge>
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">{b.calls}</td>
                    <td className="py-2 px-2 text-right tabular-nums">{formatNumber(b.input_tokens)}</td>
                    <td className="py-2 px-2 text-right tabular-nums">{formatNumber(b.output_tokens)}</td>
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">
                      {formatNumber(b.cache_read)} / {formatNumber(b.cache_write)}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">{b.tool_calls}</td>
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">{b.avg_duration_ms}</td>
                    <td className="py-2 px-2 text-right tabular-nums font-semibold text-amber-400">
                      {formatCost(b.cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent calls */}
      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-semibold mb-3">Recent calls (latest 50)</h3>
        {loading ? (
          <Skeleton className="h-40" />
        ) : recent.length === 0 ? (
          <p className="text-xs text-muted-foreground py-4 text-center">No recent calls.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2 px-2 font-medium">Time</th>
                  <th className="text-left py-2 px-2 font-medium">Agent</th>
                  <th className="text-left py-2 px-2 font-medium">Model</th>
                  <th className="text-right py-2 px-2 font-medium">Tokens</th>
                  <th className="text-right py-2 px-2 font-medium">Turns</th>
                  <th className="text-right py-2 px-2 font-medium">ms</th>
                  <th className="text-right py-2 px-2 font-medium">Cost</th>
                  <th className="text-center py-2 px-2 font-medium">OK</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id} className="border-b border-border/50 hover:bg-muted/20">
                    <td className="py-2 px-2 font-mono text-muted-foreground">{formatTime(r.timestamp)}</td>
                    <td className="py-2 px-2 font-mono">{r.agent_id}</td>
                    <td className="py-2 px-2">
                      <Badge variant="outline" className={`text-[9px] ${MODEL_COLOR[r.model] ?? ""}`}>
                        {MODEL_LABEL[r.model] ?? r.model}
                      </Badge>
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">{formatNumber(r.total_tokens)}</td>
                    <td className="py-2 px-2 text-right tabular-nums">{r.turns}</td>
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">{r.duration_ms}</td>
                    <td className="py-2 px-2 text-right tabular-nums font-semibold text-amber-400">
                      {formatCost(r.cost_usd)}
                    </td>
                    <td className="py-2 px-2 text-center">
                      <span className={`inline-block size-2 rounded-full ${r.success ? "bg-green-400" : "bg-red-400"}`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
