"use client";

import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import api from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface IntegrationConfig {
  id: string;
  name: string;
  description: string;
  logo: string;
  status: string;
  tools_count: number;
  config: Record<string, string>;
}

interface TestResult {
  name: string;
  status: string;
  latency_ms: number;
  detail: string;
}

// ─── Logos (SVG inline) ─────────────────────────────────────────────────────

function Logo({ name, className = "size-8" }: { name: string; className?: string }) {
  switch (name) {
    case "anthropic":
      return (
        <div className={`${className} rounded-lg bg-[#d4a27f]/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="#d4a27f">
            <path d="M17.304 3.541h-3.672l6.696 16.918h3.672l-6.696-16.918zm-10.608 0l-6.696 16.918h3.78l1.404-3.672h7.056l1.404 3.672h3.78l-6.696-16.918h-4.032zm-.456 10.08l2.472-6.384 2.472 6.384h-4.944z"/>
          </svg>
        </div>
      );
    case "mt5":
      return (
        <div className={`${className} rounded-lg bg-blue-500/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="#3b82f6" strokeWidth="2">
            <path d="M3 3v18h18" strokeLinecap="round"/>
            <path d="M7 14l4-4 3 3 7-7" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      );
    case "redis":
      return (
        <div className={`${className} rounded-lg bg-red-500/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="#dc2626">
            <path d="M10.5 2.661l-8.5 3.452v7.779l8.5 3.447 8.5-3.447v-7.779l-8.5-3.452zm6.624 3.17l-6.624 2.686-6.624-2.686 6.624-2.689 6.624 2.689zm-14.124 3.065l6.5 2.637v5.86l-6.5-2.637v-5.86zm8.5 8.497v-5.86l6.5-2.637v5.86l-6.5 2.637z"/>
          </svg>
        </div>
      );
    case "postgresql":
      return (
        <div className={`${className} rounded-lg bg-blue-600/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="#2563eb">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9v-2h2v2zm0-4H9V7h2v5zm4 4h-2v-2h2v2zm0-4h-2V7h2v5z"/>
          </svg>
        </div>
      );
    case "binance":
      return (
        <div className={`${className} rounded-lg bg-yellow-500/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="#f3ba2f">
            <path d="M12 2L7.5 6.5 9.62 8.62 12 6.24l2.38 2.38L16.5 6.5zM2 12l2.12-2.12L6.24 12l-2.12 2.12zm10 0l2.12-2.12L16.24 12l-2.12 2.12zm-4.5 0L9.62 9.88 12 12.26l2.38-2.38L16.5 12 12 16.5zM18 12l2.12-2.12L22.24 12l-2.12 2.12z"/>
          </svg>
        </div>
      );
    case "telegram":
      return (
        <div className={`${className} rounded-lg bg-sky-500/10 flex items-center justify-center`}>
          <svg viewBox="0 0 24 24" className="size-5" fill="#0ea5e9">
            <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
          </svg>
        </div>
      );
    default:
      return <div className={`${className} rounded-lg bg-zinc-500/10 flex items-center justify-center text-lg`}>🔌</div>;
  }
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function IntegrationPage() {
  const [integrations, setIntegrations] = useState<IntegrationConfig[]>([]);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await api.get("/api/integration/config");
      setIntegrations(res.data.integrations);
    } catch {
      // handled
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const testService = async (id: string) => {
    setTesting(id);
    try {
      const res = await api.get(`/api/integration/test/${id}`);
      setTestResults((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [id]: { name: id, status: "error", latency_ms: 0, detail: "Request failed" },
      }));
    } finally {
      setTesting(null);
    }
  };

  const testAll = async () => {
    setTesting("all");
    try {
      const res = await api.get("/api/integration/status");
      const results: Record<string, TestResult> = {};
      for (const s of res.data.services) {
        const id = s.name.toLowerCase().replace(/\s+/g, "").replace("api", "");
        const keyMap: Record<string, string> = {
          "anthropic": "anthropic", "mt5bridge": "mt5",
          "redis": "redis", "postgresql": "db", "binance": "binance",
        };
        results[keyMap[id] || id] = s;
      }
      setTestResults(results);
    } catch {
      // handled
    } finally {
      setTesting(null);
    }
  };

  const connectedCount = Object.values(testResults).filter((r) => r.status === "connected").length;
  const totalCount = integrations.length;

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <PageHeader
        title="Integration"
        subtitle={`Connect external services to enable agent capabilities`}
      >
        <button
          onClick={testAll}
          disabled={testing === "all"}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {testing === "all" ? "Testing..." : "Test All Connections"}
        </button>
      </PageHeader>

      {loading ? (
        <div className="text-center text-muted-foreground py-8">Loading integrations...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {integrations.map((intg) => {
            const result = testResults[intg.id];
            const isConnected = result?.status === "connected";
            const isError = result?.status === "error";
            const isExpanded = expandedId === intg.id;

            return (
              <div
                key={intg.id}
                className={`rounded-xl border bg-card transition-all ${
                  isExpanded ? "col-span-1 md:col-span-2 lg:col-span-3" : ""
                } ${
                  isConnected ? "border-green-500/30" :
                  isError ? "border-red-500/30" :
                  "border-border"
                }`}
              >
                {/* Card Header */}
                <button
                  type="button"
                  onClick={() => setExpandedId(isExpanded ? null : intg.id)}
                  className="w-full p-5 text-left"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <Logo name={intg.logo} />
                      <div>
                        <h3 className="font-semibold text-sm">{intg.name}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">{intg.description}</p>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between mt-4">
                    {result ? (
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${
                        isConnected ? "bg-green-500/10 text-green-500" :
                        isError ? "bg-red-500/10 text-red-500" :
                        "bg-zinc-500/10 text-zinc-400"
                      }`}>
                        {isConnected ? "Connected" : isError ? "Error" : result.status}
                        {result.latency_ms > 0 && ` · ${result.latency_ms}ms`}
                      </span>
                    ) : (
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${
                        intg.status === "configured" ? "bg-zinc-500/10 text-zinc-400" : "bg-amber-500/10 text-amber-500"
                      }`}>
                        {intg.status === "configured" ? "Not tested" : "Not configured"}
                      </span>
                    )}
                    {intg.tools_count > 0 && (
                      <span className="text-xs text-muted-foreground">
                        🔧 {intg.tools_count} tools
                      </span>
                    )}
                  </div>
                </button>

                {/* Expanded Config Panel */}
                {isExpanded && (
                  <div className="border-t border-border p-5 space-y-4">
                    <h4 className="text-xs font-semibold text-muted-foreground uppercase">Configuration</h4>
                    <div className="space-y-3">
                      {Object.entries(intg.config).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between">
                          <label className="text-xs font-medium text-muted-foreground capitalize">
                            {key.replace(/_/g, " ")}
                          </label>
                          <span className="text-xs font-mono bg-background border border-border rounded px-2 py-1 max-w-64 truncate">
                            {value || "—"}
                          </span>
                        </div>
                      ))}
                    </div>

                    {result?.detail && (
                      <div className={`text-xs rounded-lg p-3 ${
                        isConnected ? "bg-green-500/5 text-green-400" : "bg-red-500/5 text-red-400"
                      }`}>
                        {result.detail}
                      </div>
                    )}

                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); testService(intg.id); }}
                      disabled={testing === intg.id}
                      className="w-full text-xs px-4 py-2 rounded-lg border border-border hover:bg-accent disabled:opacity-50 font-medium"
                    >
                      {testing === intg.id ? "Testing..." : "Test Connection"}
                    </button>

                    <p className="text-xs text-muted-foreground">
                      Configure via Railway environment variables.
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
