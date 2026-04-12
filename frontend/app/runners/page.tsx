"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  listRunners,
  createRunner,
  deleteRunner,
  startRunner,
  stopRunner,
  restartRunner,
  killRunner,
  getRunnerLogs,
  getRunnerMetrics,
  getRunnerJobs,
  listJobs,
  cancelJob,
  retryJob,
  getWsToken,
  getRolloutMode,
  setRolloutMode,
  getDeployReadiness,
} from "@/lib/api";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ─── Types ──────────────────────────────────────────────────────────────────

interface RunnerItem {
  id: number;
  name: string;
  container_id: string | null;
  image: string;
  status: string;
  max_concurrent_jobs: number;
  tags: string[] | null;
  resource_limits: Record<string, string> | null;
  last_heartbeat_at: string | null;
  created_at: string;
  updated_at: string | null;
  current_jobs?: { id: number; job_type: string; started_at: string | null }[];
}

interface LogEntry {
  id: number;
  timestamp: string | null;
  level: string;
  message: string;
  metadata: Record<string, unknown> | null;
}

interface MetricEntry {
  id: number;
  timestamp: string | null;
  cpu_percent: number | null;
  memory_mb: number | null;
  memory_limit_mb: number | null;
  network_rx_bytes: number | null;
  network_tx_bytes: number | null;
}

interface JobItem {
  id: number;
  runner_id: number | null;
  job_type: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  online: "bg-green-500/20 text-green-400",
  starting: "bg-yellow-500/20 text-yellow-400",
  degraded: "bg-amber-500/20 text-amber-400",
  error: "bg-red-500/20 text-red-400",
  stopped: "bg-zinc-500/20 text-zinc-400",
};

const JOB_STATUS_STYLES: Record<string, string> = {
  completed: "text-green-400",
  failed: "text-red-400",
  running: "text-yellow-400",
  pending: "text-zinc-400",
  cancelled: "text-zinc-500",
};

const LOG_LEVEL_STYLES: Record<string, string> = {
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
  debug: "text-zinc-500",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function RunnersPage() {
  const [runners, setRunners] = useState<RunnerItem[]>([]);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  // Create dialog
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newImage, setNewImage] = useState("trading-agent:latest");
  const [newMaxJobs, setNewMaxJobs] = useState(3);
  const [creating, setCreating] = useState(false);

  // Rollout mode
  const [rolloutMode, setRolloutModeState] = useState("shadow");
  const [rolloutDescription, setRolloutDescription] = useState("");
  const [changingMode, setChangingMode] = useState(false);
  const [readiness, setReadiness] = useState<{ ready: boolean; errors: number; warnings: number; checks: { name: string; status: string; detail: string }[] } | null>(null);
  const [showReadiness, setShowReadiness] = useState(false);

  // Expanded panels
  const [expandedLogs, setExpandedLogs] = useState<number | null>(null);
  const [expandedMetrics, setExpandedMetrics] = useState<number | null>(null);

  // Logs state
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logLevel, setLogLevel] = useState<string>("");
  const [wsLogs, setWsLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Metrics state
  const [metrics, setMetrics] = useState<MetricEntry[]>([]);

  // ─── Fetch ──────────────────────────────────────────────────────────────

  const fetchRunners = useCallback(async () => {
    try {
      const [runnersRes, jobsRes] = await Promise.all([
        listRunners(),
        listJobs({ limit: 20 }),
      ]);
      setRunners(runnersRes.data);
      setJobs(jobsRes.data);
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch rollout mode once on mount (not on every poll)
  useEffect(() => {
    getRolloutMode().then((res) => {
      setRolloutModeState(res.data.mode);
      setRolloutDescription(res.data.description);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    fetchRunners();
    const interval = setInterval(fetchRunners, 10000);
    return () => clearInterval(interval);
  }, [fetchRunners]);

  // ─── Rollout Mode ───────────────────────────────────────────────────────

  const handleModeChange = async (mode: string) => {
    if (mode === "live" && !confirm("Switch to LIVE mode? This enables real trading with full risk.")) return;
    setChangingMode(true);
    try {
      const res = await setRolloutMode(mode);
      setRolloutModeState(res.data.mode);
      setRolloutDescription(res.data.description);
    } catch { /* handled */ } finally {
      setChangingMode(false);
    }
  };

  const handleCheckReadiness = async () => {
    setShowReadiness(true);
    try {
      const res = await getDeployReadiness();
      setReadiness(res.data);
    } catch {
      setReadiness(null);
    }
  };

  // ─── Runner Actions ─────────────────────────────────────────────────────

  const doAction = async (
    key: string,
    action: () => Promise<unknown>,
  ) => {
    setActionLoading((prev) => ({ ...prev, [key]: true }));
    try {
      await action();
      await fetchRunners();
    } catch {
      // handled by interceptor
    } finally {
      setActionLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createRunner({
        name: newName.trim(),
        image: newImage,
        max_concurrent_jobs: newMaxJobs,
      });
      setShowCreate(false);
      setNewName("");
      await fetchRunners();
    } catch {
      // handled
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (r: RunnerItem) => {
    if (!confirm(`Delete runner "${r.name}"? This will stop the runner and remove it.`)) return;
    await doAction(`delete-${r.id}`, () => deleteRunner(r.id));
  };

  const handleKill = async (r: RunnerItem) => {
    if (!confirm(`Force kill runner "${r.name}"?`)) return;
    await doAction(`kill-${r.id}`, () => killRunner(r.id));
  };

  // ─── Logs Panel ─────────────────────────────────────────────────────────

  const openLogs = async (runnerId: number) => {
    if (expandedLogs === runnerId) {
      closeLogs();
      return;
    }
    setExpandedLogs(runnerId);
    setExpandedMetrics(null);
    setLogs([]);
    setWsLogs([]);
    setPaused(false);

    // Fetch historical logs
    try {
      const res = await getRunnerLogs(runnerId, { limit: 100 });
      setLogs(res.data);
    } catch {
      // ignore
    }

    // Open WebSocket for live logs
    try {
      const tokenRes = await getWsToken();
      const token = tokenRes.data.token;
      const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${wsProto}//${window.location.host}/ws/runners/${runnerId}/logs?token=${token}`);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const entry: LogEntry = {
            id: Date.now(),
            timestamp: data.timestamp || new Date().toISOString(),
            level: data.level || "info",
            message: data.message || event.data,
            metadata: data.metadata || null,
          };
          setWsLogs((prev) => [...prev.slice(-500), entry]);
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => ws.close();
      wsRef.current = ws;
    } catch {
      // WS connection failed — still show historical logs
    }
  };

  const closeLogs = () => {
    setExpandedLogs(null);
    wsRef.current?.close();
    wsRef.current = null;
    setWsLogs([]);
  };

  // Auto-scroll logs
  useEffect(() => {
    if (!paused && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [wsLogs, paused]);

  // Cleanup WS on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  const allLogs = useMemo(
    () => [...logs, ...wsLogs].filter((l) => !logLevel || l.level === logLevel),
    [logs, wsLogs, logLevel],
  );

  // ─── Metrics Panel ──────────────────────────────────────────────────────

  const openMetrics = async (runnerId: number) => {
    if (expandedMetrics === runnerId) {
      setExpandedMetrics(null);
      return;
    }
    setExpandedMetrics(runnerId);
    setExpandedLogs(null);
    closeLogs();

    try {
      const res = await getRunnerMetrics(runnerId, { limit: 60 });
      setMetrics(res.data.reverse());
    } catch {
      setMetrics([]);
    }
  };

  // ─── Job Actions ────────────────────────────────────────────────────────

  const handleCancelJob = async (jobId: number) => {
    await doAction(`cancel-job-${jobId}`, () => cancelJob(jobId));
  };

  const handleRetryJob = async (jobId: number) => {
    await doAction(`retry-job-${jobId}`, () => retryJob(jobId));
  };

  // ─── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader
        title="Runners"
        subtitle="Manage Docker sandbox runners and agent jobs"
      />

      {/* Rollout Mode Banner */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium">Rollout Mode:</span>
              <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                rolloutMode === "live" ? "bg-green-500/20 text-green-400" :
                rolloutMode === "micro" ? "bg-blue-500/20 text-blue-400" :
                rolloutMode === "paper" ? "bg-purple-500/20 text-purple-400" :
                "bg-zinc-500/20 text-zinc-400"
              }`}>
                {rolloutMode.toUpperCase()}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{rolloutDescription}</p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={rolloutMode}
              onChange={(e) => handleModeChange(e.target.value)}
              disabled={changingMode}
              title="Rollout mode"
              className="text-xs rounded border border-border bg-background px-2 py-1.5 disabled:opacity-50"
            >
              <option value="shadow">Shadow</option>
              <option value="paper">Paper</option>
              <option value="micro">Micro-Live</option>
              <option value="live">Live</option>
            </select>
            <button
              onClick={handleCheckReadiness}
              className="text-xs px-3 py-1.5 rounded border border-border hover:bg-accent text-muted-foreground hover:text-foreground"
            >
              Check Readiness
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              + New Runner
            </button>
          </div>
        </div>
      </div>

      {/* Deploy Readiness Panel */}
      {showReadiness && readiness && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-medium">
              Deploy Readiness: {readiness.ready ? (
                <span className="text-green-400">Ready</span>
              ) : (
                <span className="text-red-400">Not Ready ({readiness.errors} errors)</span>
              )}
            </h4>
            <button onClick={() => setShowReadiness(false)} className="text-xs text-muted-foreground hover:text-foreground">Close</button>
          </div>
          <div className="space-y-1">
            {readiness.checks.map((c) => (
              <div key={c.name} className="flex items-center gap-2 text-xs">
                <span className={`w-3 h-3 rounded-full ${
                  c.status === "ok" ? "bg-green-500" : c.status === "warn" ? "bg-yellow-500" : "bg-red-500"
                }`} />
                <span className="font-mono w-40">{c.name}</span>
                <span className="text-muted-foreground">{c.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runner List */}
      {loading ? (
        <div className="text-center text-muted-foreground py-8">Loading runners...</div>
      ) : runners.length === 0 ? (
        <div className="text-center text-muted-foreground py-8">
          No runners registered yet. Click &quot;+ New Runner&quot; to get started.
        </div>
      ) : (
        <div className="space-y-3">
          {runners.map((r) => (
            <div key={r.id} className="rounded-lg border border-border bg-card">
              {/* Runner Header */}
              <div className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-semibold text-sm">{r.name}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLES[r.status] || STATUS_STYLES.stopped}`}>
                        {r.status}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                      <span>Image: {r.image}</span>
                      {r.container_id && (
                        <span>Container: {r.container_id.slice(0, 12)}</span>
                      )}
                      <span>Max jobs: {r.max_concurrent_jobs}</span>
                      <span>Heartbeat: {timeAgo(r.last_heartbeat_at)}</span>
                    </div>
                  </div>

                  {/* Control Buttons */}
                  <div className="flex items-center gap-1 shrink-0 flex-wrap">
                    {r.status === "stopped" || r.status === "error" ? (
                      <button
                        onClick={() => doAction(`start-${r.id}`, () => startRunner(r.id))}
                        disabled={!!actionLoading[`start-${r.id}`]}
                        className="text-xs px-2 py-1 rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 disabled:opacity-50"
                      >
                        {actionLoading[`start-${r.id}`] ? "..." : "Start"}
                      </button>
                    ) : (
                      <>
                        <button
                          onClick={() => doAction(`stop-${r.id}`, () => stopRunner(r.id))}
                          disabled={!!actionLoading[`stop-${r.id}`]}
                          className="text-xs px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-50"
                        >
                          {actionLoading[`stop-${r.id}`] ? "..." : "Stop"}
                        </button>
                        <button
                          onClick={() => doAction(`restart-${r.id}`, () => restartRunner(r.id))}
                          disabled={!!actionLoading[`restart-${r.id}`]}
                          className="text-xs px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground disabled:opacity-50"
                        >
                          {actionLoading[`restart-${r.id}`] ? "..." : "Restart"}
                        </button>
                        <button
                          onClick={() => handleKill(r)}
                          disabled={!!actionLoading[`kill-${r.id}`]}
                          className="text-xs px-2 py-1 rounded hover:bg-accent text-red-400 hover:text-red-300 disabled:opacity-50"
                        >
                          {actionLoading[`kill-${r.id}`] ? "..." : "Kill"}
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => openLogs(r.id)}
                      className={`text-xs px-2 py-1 rounded hover:bg-accent ${expandedLogs === r.id ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      Logs
                    </button>
                    <button
                      onClick={() => openMetrics(r.id)}
                      className={`text-xs px-2 py-1 rounded hover:bg-accent ${expandedMetrics === r.id ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      Metrics
                    </button>
                    <button
                      onClick={() => handleDelete(r)}
                      disabled={!!actionLoading[`delete-${r.id}`]}
                      className="text-xs px-2 py-1 rounded hover:bg-accent text-red-400 hover:text-red-300 disabled:opacity-50"
                    >
                      {actionLoading[`delete-${r.id}`] ? "..." : "Delete"}
                    </button>
                  </div>
                </div>
              </div>

              {/* Logs Panel */}
              {expandedLogs === r.id && (
                <div className="border-t border-border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium text-muted-foreground">
                      Live Logs
                      {wsRef.current?.readyState === WebSocket.OPEN && (
                        <span className="ml-2 text-green-400">connected</span>
                      )}
                    </h4>
                    <div className="flex items-center gap-2">
                      <select
                        value={logLevel}
                        onChange={(e) => setLogLevel(e.target.value)}
                        className="text-xs rounded border border-border bg-background px-2 py-1"
                      >
                        <option value="">All levels</option>
                        <option value="info">info</option>
                        <option value="warn">warn</option>
                        <option value="error">error</option>
                        <option value="debug">debug</option>
                      </select>
                      <button
                        onClick={() => setPaused(!paused)}
                        className={`text-xs px-2 py-1 rounded ${paused ? "bg-yellow-500/20 text-yellow-400" : "hover:bg-accent text-muted-foreground"}`}
                      >
                        {paused ? "Resume" : "Pause"}
                      </button>
                    </div>
                  </div>
                  <div className="bg-background rounded border border-border p-2 max-h-64 overflow-y-auto font-mono text-xs space-y-0.5">
                    {allLogs.length === 0 ? (
                      <div className="text-muted-foreground py-4 text-center">No logs yet.</div>
                    ) : (
                      allLogs.map((l) => (
                        <div key={l.id} className="flex gap-2">
                          <span className="text-muted-foreground shrink-0 w-20">
                            {formatTime(l.timestamp)}
                          </span>
                          <span className={`shrink-0 w-12 uppercase ${LOG_LEVEL_STYLES[l.level] || ""}`}>
                            {l.level}
                          </span>
                          <span className="break-all">{l.message}</span>
                        </div>
                      ))
                    )}
                    <div ref={logsEndRef} />
                  </div>
                </div>
              )}

              {/* Metrics Panel */}
              {expandedMetrics === r.id && (
                <div className="border-t border-border p-4">
                  <h4 className="text-xs font-medium text-muted-foreground mb-3">Resource Metrics</h4>
                  {metrics.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-4 text-center">
                      No metrics collected yet. Runner must be online.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* CPU Chart */}
                      <div>
                        <h5 className="text-xs text-muted-foreground mb-1">CPU Usage (%)</h5>
                        <ResponsiveContainer width="100%" height={120}>
                          <LineChart data={metrics}>
                            <XAxis
                              dataKey="timestamp"
                              tickFormatter={(v) => formatTime(v)}
                              tick={{ fontSize: 10 }}
                              stroke="#666"
                            />
                            <YAxis tick={{ fontSize: 10 }} stroke="#666" />
                            <Tooltip
                              contentStyle={{ backgroundColor: "#1a1a2e", border: "1px solid #333", fontSize: 11 }}
                              labelFormatter={(v) => formatTime(v as string)}
                            />
                            <Line
                              type="monotone"
                              dataKey="cpu_percent"
                              stroke="#3b82f6"
                              strokeWidth={1.5}
                              dot={false}
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      {/* Memory Chart */}
                      <div>
                        <h5 className="text-xs text-muted-foreground mb-1">Memory (MB)</h5>
                        <ResponsiveContainer width="100%" height={120}>
                          <LineChart data={metrics}>
                            <XAxis
                              dataKey="timestamp"
                              tickFormatter={(v) => formatTime(v)}
                              tick={{ fontSize: 10 }}
                              stroke="#666"
                            />
                            <YAxis tick={{ fontSize: 10 }} stroke="#666" />
                            <Tooltip
                              contentStyle={{ backgroundColor: "#1a1a2e", border: "1px solid #333", fontSize: 11 }}
                              labelFormatter={(v) => formatTime(v as string)}
                            />
                            <Line
                              type="monotone"
                              dataKey="memory_mb"
                              stroke="#a855f7"
                              strokeWidth={1.5}
                              dot={false}
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )}
                  {metrics.length > 0 && (
                    <div className="flex gap-6 mt-2 text-xs text-muted-foreground">
                      <span>
                        Avg CPU: {(metrics.reduce((s, m) => s + (m.cpu_percent || 0), 0) / metrics.length).toFixed(1)}%
                      </span>
                      <span>
                        Peak CPU: {Math.max(...metrics.map((m) => m.cpu_percent || 0)).toFixed(1)}%
                      </span>
                      <span>
                        Avg Memory: {(metrics.reduce((s, m) => s + (m.memory_mb || 0), 0) / metrics.length).toFixed(0)} MB
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Recent Jobs */}
      <div>
        <h3 className="text-sm font-semibold mb-3">Recent Jobs</h3>
        {jobs.length === 0 ? (
          <div className="text-xs text-muted-foreground py-4 text-center">No jobs yet.</div>
        ) : (
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left px-3 py-2 font-medium">Status</th>
                  <th className="text-left px-3 py-2 font-medium">Type</th>
                  <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">Runner</th>
                  <th className="text-left px-3 py-2 font-medium">Time</th>
                  <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">Duration</th>
                  <th className="text-left px-3 py-2 font-medium">Result</th>
                  <th className="text-right px-3 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => {
                  const runnerName = runners.find((r) => r.id === j.runner_id)?.name || "—";
                  return (
                    <tr key={j.id} className="border-b border-border last:border-0 hover:bg-accent/30">
                      <td className="px-3 py-2">
                        <span className={JOB_STATUS_STYLES[j.status] || ""}>
                          {j.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono">{j.job_type}</td>
                      <td className="px-3 py-2 hidden sm:table-cell">{runnerName}</td>
                      <td className="px-3 py-2 text-muted-foreground">{timeAgo(j.created_at)}</td>
                      <td className="px-3 py-2 text-muted-foreground hidden sm:table-cell">
                        {formatDuration(j.duration_ms)}
                      </td>
                      <td className="px-3 py-2 max-w-32 truncate">
                        {j.error ? (
                          <span className="text-red-400" title={j.error}>{j.error}</span>
                        ) : j.output ? (
                          <span className="text-muted-foreground" title={JSON.stringify(j.output)}>
                            {JSON.stringify(j.output).slice(0, 40)}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {(j.status === "pending" || j.status === "running") && (
                          <button
                            onClick={() => handleCancelJob(j.id)}
                            disabled={!!actionLoading[`cancel-job-${j.id}`]}
                            className="text-amber-400 hover:text-amber-300 disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        )}
                        {j.status === "failed" && (
                          <button
                            onClick={() => handleRetryJob(j.id)}
                            disabled={!!actionLoading[`retry-job-${j.id}`]}
                            className="text-blue-400 hover:text-blue-300 disabled:opacity-50"
                          >
                            Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Runner Dialog */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md mx-4 space-y-4">
            <h3 className="text-lg font-semibold">New Runner</h3>

            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                placeholder="e.g. trading-agent-gold"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Image</label>
              <input
                type="text"
                value={newImage}
                onChange={(e) => setNewImage(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Max Concurrent Jobs</label>
              <input
                type="number"
                min={1}
                max={10}
                value={newMaxJobs}
                onChange={(e) => setNewMaxJobs(parseInt(e.target.value) || 1)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-sm rounded-md hover:bg-accent"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
                className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
