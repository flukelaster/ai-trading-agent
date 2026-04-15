"use client";

import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import api from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface ToolInfo { name: string; description: string; }
interface IntegrationConfig {
  id: string; name: string; description: string; status: string;
  config: Record<string, string>; tools: ToolInfo[];
}
interface TestResult { name: string; status: string; latency_ms: number; detail: string; }

// ─── SVG Logos ───────────────────────────────────────────────────────────────

function ClaudeLogo() {
  return (
    <svg className="size-7" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243.832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315.833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03.049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079.485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662.401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z" fill="#D97757" fillRule="nonzero"/>
    </svg>
  );
}

function BinanceLogo() {
  return (
    <svg className="size-7" viewBox="0 0 511.97 511.97"><path fill="#f3ba2f" d="M156.56,215.14,256,115.71l99.47,99.47,57.86-57.85L256,0,98.71,157.28l57.85,57.85M0,256l57.86-57.87L115.71,256,57.85,313.83Zm156.56,40.85L256,396.27l99.47-99.47,57.89,57.82,0,0L256,512,98.71,354.7l-.08-.09,57.93-57.77M396.27,256l57.85-57.85L512,256l-57.85,57.85Z"/><path fill="#f3ba2f" d="M314.66,256h0L256,197.25,212.6,240.63h0l-5,5L197.33,255.9l-.08.08.08.08L256,314.72l58.7-58.7,0,0-.05,0"/></svg>
  );
}

function TelegramLogo() {
  return (
    <svg className="size-7" viewBox="0 0 512 512"><defs><linearGradient id="tg" x1="256" y1="3.84" x2="256" y2="512" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#2AABEE"/><stop offset="1" stopColor="#229ED9"/></linearGradient></defs><circle fill="url(#tg)" cx="256" cy="256" r="256"/><path fill="#fff" d="M115.88 253.3c74.63-32.52 124.39-53.95 149.29-64.31 71.1-29.57 85.87-34.71 95.5-34.88 2.12-.03 6.85.49 9.92 2.98 2.59 2.1 3.3 4.94 3.64 6.93.34 2 .77 6.53.43 10.08-3.85 40.48-20.52 138.71-29 184.05-3.59 19.19-10.66 25.62-17.5 26.25-14.86 1.37-26.15-9.83-40.55-19.27-22.53-14.76-35.26-23.96-57.13-38.37-25.28-16.66-8.89-25.81 5.51-40.77 3.77-3.92 69.27-63.5 70.54-68.9.16-.68.31-3.2-1.19-4.53s-3.71-.87-5.3-.51c-2.26.51-38.25 24.3-107.98 71.37-10.22 7.02-19.48 10.43-27.77 10.26-9.14-.2-26.72-5.17-39.79-9.42-16.03-5.21-28.77-7.97-27.66-16.82.57-4.61 6.92-9.32 19.04-14.14z"/></svg>
  );
}

function MT5Logo() {
  return (
    <svg className="size-7" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2">
      <path d="M3 3v18h18" strokeLinecap="round"/><path d="M7 14l4-4 3 3 7-7" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function D2Logo() {
  return (
    <svg className="size-7" viewBox="0 0 180 180" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path fillRule="evenodd" clipRule="evenodd" d="M115.055 72.5C115.055 79.8638 109.086 85.8333 101.722 85.8333C94.3583 85.8333 88.3888 79.8638 88.3888 72.5C88.3888 65.1362 94.3583 59.1667 101.722 59.1667C109.086 59.1667 115.055 65.1362 115.055 72.5ZM81.9999 59.7778H28.6667L28.6665 86.4444H55.3332V125.556H81.9999V59.7778ZM128.755 59.7778H159.333L131.778 125.556H101.111L128.755 59.7778Z" fill="currentColor"/>
    </svg>
  );
}

const LOGOS: Record<string, () => React.ReactElement> = {
  anthropic: ClaudeLogo, mt5: MT5Logo, telegram: TelegramLogo,
  economic_calendar: D2Logo, tradingview: D2Logo,
};

// ─── Page ───────────────────────────────────────────────────────────────────

export default function IntegrationPage() {
  const [integrations, setIntegrations] = useState<IntegrationConfig[]>([]);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [modalId, setModalId] = useState<string | null>(null);
  const [showTools, setShowTools] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await api.get("/api/integration/config");
      setIntegrations(res.data.integrations);
    } catch { /* handled */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const testService = async (id: string) => {
    setTesting(id);
    try {
      const res = await api.get(`/api/integration/test/${id}`);
      setTestResults((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setTestResults((prev) => ({ ...prev, [id]: { name: id, status: "error", latency_ms: 0, detail: "Failed" } }));
    } finally { setTesting(null); }
  };

  const testAll = async () => {
    setTesting("all");
    try {
      const res = await api.get("/api/integration/status");
      const results: Record<string, TestResult> = {};
      const keyMap: Record<string, string> = { "Claude AI (Max)": "anthropic", "Anthropic API": "anthropic", "MT5 Bridge": "mt5", "Telegram": "telegram", "Economic Calendar": "economic_calendar", "TradingView": "tradingview" };
      for (const s of res.data.services) results[keyMap[s.name] || s.name] = s;
      setTestResults(results);
    } catch { /* handled */ } finally { setTesting(null); }
  };

  const openModal = (id: string) => {
    setModalId(id);
    setShowTools(false);
    setEditValues({});
  };

  const handleSave = async () => {
    if (!modalId) return;
    const nonEmpty = Object.fromEntries(Object.entries(editValues).filter(([, v]) => v.trim()));
    if (Object.keys(nonEmpty).length === 0) return;
    setSaving(true);
    try {
      await api.put("/api/integration/config", { integration_id: modalId, config: nonEmpty });
      setEditValues({});
      await fetchConfig();
    } catch { /* handled */ } finally { setSaving(false); }
  };

  const modalIntg = integrations.find((i) => i.id === modalId);
  const modalResult = modalId ? testResults[modalId] : null;
  const hasEdits = Object.values(editValues).some((v) => v.trim());

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      <PageHeader title="Integration" subtitle="Connect external services to enable agent capabilities">
        <button type="button" onClick={testAll} disabled={testing === "all"}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          {testing === "all" ? "Testing..." : "Test All"}
        </button>
      </PageHeader>

      <PageInstructions

        items={[
          "Connect external services here. Click Configure to add API keys, then Test Connection to verify.",
          "MT5 requires a running MetaTrader 5 terminal. Claude AI uses Max Subscription (OAuth). Telegram needs a bot token from @BotFather.",
        ]}
      />

      {loading ? (
        <div className="text-center text-muted-foreground py-8">Loading...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {integrations.map((intg) => {
            const result = testResults[intg.id];
            const isTestedConnected = result?.status === "connected";
            const isConfigured = intg.status === "configured";
            const showConnected = isTestedConnected || isConfigured;
            const LogoComp = LOGOS[intg.id];
            return (
              <button key={intg.id} type="button" onClick={() => openModal(intg.id)}
                className="rounded-xl border border-border bg-card p-4 text-left hover:border-primary/40 transition-all group">
                <div className="flex items-center gap-3">
                  <div className="size-10 rounded-xl bg-muted/50 flex items-center justify-center group-hover:bg-muted transition-colors">
                    {LogoComp ? <LogoComp /> : null}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-sm">{intg.name}</h3>
                      {showConnected && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-green-500 bg-green-500/10 border border-green-500/20 rounded-full px-2 py-0.5">
                          <span className="size-1.5 rounded-full bg-green-500" />
                          Connected
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{intg.description}</p>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-border/50">
                  {!showConnected && (
                    <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                      result?.status === "error" ? "bg-red-500/10 text-red-500" :
                      "bg-amber-500/10 text-amber-500"
                    }`}>
                      {result?.status === "error" ? "Error" : "Not configured"}
                    </span>
                  )}
                  {isTestedConnected && <span className="text-xs text-muted-foreground">{result.latency_ms}ms</span>}
                  <span className="text-xs text-muted-foreground ml-auto">{intg.tools.length} tools</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* ─── Modal ──────────────────────────────────────────────────── */}
      {modalIntg && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] bg-black/50 overflow-y-auto" onClick={() => setModalId(null)}>
          <div className="bg-card border border-border rounded-2xl w-full max-w-lg mx-4 mb-10 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between p-6 pb-3">
              <div className="flex items-center gap-3">
                {LOGOS[modalIntg.id] && (() => { const L = LOGOS[modalIntg.id]; return <L />; })()}
                <h2 className="text-lg font-bold">{modalIntg.name}</h2>
              </div>
              <button type="button" onClick={() => setModalId(null)} className="text-muted-foreground hover:text-foreground text-2xl leading-none px-1">&times;</button>
            </div>
            <p className="px-6 text-sm text-muted-foreground">{modalIntg.description}</p>

            {/* Config fields (editable) */}
            <div className="px-6 pt-5 space-y-4">
              {Object.entries(modalIntg.config).map(([key, maskedValue]) => {
                const isSecret = key.toLowerCase().includes("key") || key.toLowerCase().includes("token");
                return (
                  <div key={key}>
                    <label className="block text-xs font-medium text-muted-foreground mb-1">
                      {key}{isSecret && " *"}
                    </label>
                    <input
                      type={isSecret ? "password" : "text"}
                      placeholder={maskedValue || "Not set"}
                      value={editValues[key] || ""}
                      onChange={(e) => setEditValues((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary placeholder:text-muted-foreground/50"
                    />
                    {isSecret && maskedValue && !editValues[key] && (
                      <p className="text-xs text-muted-foreground mt-1">Current: {maskedValue}</p>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Test Result */}
            {modalResult && (
              <div className={`mx-6 mt-4 rounded-lg p-3 flex items-center gap-2 text-sm ${
                modalResult.status === "connected"
                  ? "bg-green-500/5 border border-green-500/20 text-green-400"
                  : "bg-red-500/5 border border-red-500/20 text-red-400"
              }`}>
                <span>{modalResult.status === "connected" ? "✓" : "✗"}</span>
                <span className="flex-1">{modalResult.detail}</span>
                {modalResult.latency_ms > 0 && <span className="text-xs text-muted-foreground">{modalResult.latency_ms}ms</span>}
              </div>
            )}

            {/* Buttons */}
            <div className="px-6 pt-4 flex gap-2">
              <button type="button" onClick={() => testService(modalIntg.id)} disabled={testing === modalIntg.id}
                className="flex-1 rounded-lg border border-border px-4 py-2.5 text-sm font-medium hover:bg-accent disabled:opacity-50">
                {testing === modalIntg.id ? "Testing..." : "Test Connection"}
              </button>
              {hasEdits && (
                <button type="button" onClick={handleSave} disabled={saving}
                  className="flex-1 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                  {saving ? "Saving..." : "Save"}
                </button>
              )}
            </div>

            {/* Tools */}
            {modalIntg.tools.length > 0 && (
              <div className="px-6 pt-5 pb-6">
                <button type="button" onClick={() => setShowTools(!showTools)}
                  className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase hover:text-foreground w-full">
                  <span>Available Tools ({modalIntg.tools.length})</span>
                  <span>{showTools ? "▴" : "▾"}</span>
                </button>
                {showTools && (
                  <div className="mt-3 space-y-2 max-h-48 overflow-y-auto">
                    {modalIntg.tools.map((t) => (
                      <div key={t.name} className="flex items-start gap-2">
                        <code className="text-xs font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded shrink-0">{t.name}</code>
                        <span className="text-xs text-muted-foreground">{t.description}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
