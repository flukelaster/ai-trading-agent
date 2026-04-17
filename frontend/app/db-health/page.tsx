"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Database,
} from "lucide-react";
import api from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { StatCard } from "@/components/ui/stat-card";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface PoolStats {
  size: number;
  checked_out: number;
  checked_in: number;
  overflow: number;
  total_capacity: number;
  utilization: number;
}

interface PoolSample extends PoolStats {
  ts: number;
}

interface SlowQuery {
  sql: string;
  duration_ms: number;
  timestamp: number;
}

interface LongHold {
  path: string;
  method: string;
  duration_ms: number;
  checkouts: number;
  timestamp: number;
}

interface PoolHealthResponse {
  pool: PoolStats;
  samples: PoolSample[];
  slow_queries: SlowQuery[];
  long_holds: LongHold[];
  thresholds: {
    alert_utilization: number;
    alert_sustained_seconds: number;
    slow_query_ms: number;
    request_warn_ms: number;
    request_error_ms: number;
  };
}

type Variant = "default" | "success" | "danger" | "warning" | "gold";

function fmtTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function utilizationVariant(u: number): Variant {
  if (u >= 0.85) return "danger";
  if (u >= 0.7) return "warning";
  if (u >= 0.5) return "warning";
  return "success";
}

export default function DbHealthPage() {
  const [data, setData] = useState<PoolHealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await api.get<PoolHealthResponse>("/health/pool");
        setData(res.data);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    };
    fetchHealth();
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") fetchHealth();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="DB Health" subtitle="PostgreSQL pool + slow queries" />
      <PageInstructions
        items={[
          "Live PostgreSQL connection-pool metrics, slow queries, and requests holding DB connections too long.",
          "Refreshes every 10s when tab is visible.",
          `Telegram alert fires when utilization ≥ ${data ? Math.round(data.thresholds.alert_utilization * 100) : 70}% sustained for ${data ? data.thresholds.alert_sustained_seconds : 60}s.`,
        ]}
      />

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5">
            <StatCard
              icon={Activity}
              label="Utilization"
              value={`${Math.round(data.pool.utilization * 100)}%`}
              variant={utilizationVariant(data.pool.utilization)}
            />
            <StatCard
              icon={ArrowUpFromLine}
              label="Checked out"
              value={`${data.pool.checked_out}/${data.pool.total_capacity}`}
            />
            <StatCard
              icon={ArrowDownToLine}
              label="Checked in"
              value={String(data.pool.checked_in)}
              variant="success"
            />
            <StatCard
              icon={AlertTriangle}
              label="Overflow"
              value={String(data.pool.overflow)}
              variant={data.pool.overflow > 0 ? "warning" : "default"}
            />
            <StatCard
              icon={Database}
              label="Pool size"
              value={String(data.pool.size)}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-bold">
                Utilization (last {data.samples.length} samples × 10s)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Sparkline
                samples={data.samples}
                threshold={data.thresholds.alert_utilization}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-bold">
                Top slow queries ({">"} {data.thresholds.slow_query_ms}ms)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.slow_queries.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No slow queries recorded.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Duration</TableHead>
                      <TableHead className="text-xs">When</TableHead>
                      <TableHead className="text-xs">SQL</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.slow_queries.map((q, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-xs font-mono text-destructive">
                          {q.duration_ms.toFixed(0)}ms
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {fmtTs(q.timestamp)}
                        </TableCell>
                        <TableCell className="text-xs font-mono whitespace-normal break-all">
                          {q.sql}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-bold">
                Long-hold requests ({">"} {data.thresholds.request_warn_ms}ms)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.long_holds.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No long-hold requests recorded.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Duration</TableHead>
                      <TableHead className="text-xs">Method</TableHead>
                      <TableHead className="text-xs">Path</TableHead>
                      <TableHead className="text-xs text-right">Checkouts</TableHead>
                      <TableHead className="text-xs">When</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.long_holds.map((h, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-xs font-mono text-amber-600 dark:text-amber-400">
                          {h.duration_ms.toFixed(0)}ms
                        </TableCell>
                        <TableCell className="text-xs font-mono">{h.method}</TableCell>
                        <TableCell className="text-xs font-mono">{h.path}</TableCell>
                        <TableCell className="text-xs text-right">{h.checkouts}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {fmtTs(h.timestamp)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function Sparkline({
  samples,
  threshold,
}: {
  samples: PoolSample[];
  threshold: number;
}) {
  if (samples.length === 0) {
    return <p className="text-sm text-muted-foreground">No samples yet.</p>;
  }
  const width = 600;
  const height = 80;
  const maxN = Math.max(samples.length, 1);
  const points = samples
    .map(
      (s, i) =>
        `${(i / maxN) * width},${height - Math.min(s.utilization, 1) * height}`,
    )
    .join(" ");
  const thresholdY = height - threshold * height;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="w-full h-24"
    >
      <line
        x1="0"
        y1={thresholdY}
        x2={width}
        y2={thresholdY}
        stroke="#f97316"
        strokeDasharray="4 4"
        strokeWidth="1"
      />
      <polyline
        fill="none"
        stroke="#3b82f6"
        strokeWidth="2"
        points={points}
      />
    </svg>
  );
}
