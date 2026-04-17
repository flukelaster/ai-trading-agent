"use client";

import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Save, RotateCcw, RefreshCw } from "lucide-react";
import { getAgentPrompts, updateAgentPrompt, resetAgentPrompt } from "@/lib/api";
import { showSuccess, showError } from "@/lib/toast";

interface AgentPrompt {
  id: string;
  name: string;
  model: string;
  description: string;
  default_prompt: string;
  active_prompt: string;
  is_customized: boolean;
}

const MODEL_BADGE: Record<string, { label: string; color: string }> = {
  "claude-sonnet-4-20250514": { label: "Sonnet", color: "text-blue-400 border-blue-500/40 bg-blue-500/10" },
  "claude-haiku-4-5-20251001": { label: "Haiku", color: "text-amber-400 border-amber-500/40 bg-amber-500/10" },
};

// Agent desk configs — emoji avatar, desk position flavour, role color
const AGENT_CONFIG: Record<string, {
  avatar: string;
  role: string;
  deskColor: string;
  glowColor: string;
  floorArea: string;
}> = {
  orchestrator: {
    avatar: "🧑‍💼",
    role: "Head Trader",
    deskColor: "border-blue-500/50 bg-blue-500/5",
    glowColor: "shadow-blue-500/20",
    floorArea: "Trading Floor — Center",
  },
  technical: {
    avatar: "📊",
    role: "Chart Analyst",
    deskColor: "border-green-500/50 bg-green-500/5",
    glowColor: "shadow-green-500/20",
    floorArea: "Analysis Room — Left",
  },
  fundamental: {
    avatar: "📰",
    role: "Market Researcher",
    deskColor: "border-purple-500/50 bg-purple-500/5",
    glowColor: "shadow-purple-500/20",
    floorArea: "Analysis Room — Center",
  },
  risk: {
    avatar: "🛡️",
    role: "Risk Manager",
    deskColor: "border-red-500/50 bg-red-500/5",
    glowColor: "shadow-red-500/20",
    floorArea: "Analysis Room — Right",
  },
  reflector: {
    avatar: "🔍",
    role: "Trade Reviewer",
    deskColor: "border-amber-500/50 bg-amber-500/5",
    glowColor: "shadow-amber-500/20",
    floorArea: "Review Office",
  },
  single_agent: {
    avatar: "🤖",
    role: "Solo Trader",
    deskColor: "border-zinc-500/50 bg-zinc-500/5",
    glowColor: "shadow-zinc-500/20",
    floorArea: "Backup Desk",
  },
};

// Pixel-art style monitor SVG for desk decoration
function Monitor({ active }: { active?: boolean }) {
  return (
    <svg width="28" height="24" viewBox="0 0 28 24" className="opacity-60">
      <rect x="2" y="0" width="24" height="17" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="4" y="2" width="20" height="13" fill={active ? "#22c55e22" : "#ffffff08"} />
      {active && (
        <>
          <line x1="5" y1="6" x2="23" y2="6" stroke="#22c55e" strokeWidth="0.8" opacity="0.6" />
          <line x1="5" y1="9" x2="18" y2="9" stroke="#22c55e" strokeWidth="0.8" opacity="0.4" />
          <line x1="5" y1="12" x2="20" y2="12" stroke="#22c55e" strokeWidth="0.8" opacity="0.4" />
        </>
      )}
      <rect x="12" y="17" width="4" height="4" fill="currentColor" opacity="0.4" />
      <rect x="8" y="21" width="12" height="2" rx="1" fill="currentColor" opacity="0.3" />
    </svg>
  );
}

// Ticker tape at top of trading floor
function TickerTape() {
  const tickers = [
    "GOLD ▲ 3,342.10", "BTC ▲ 84,250", "OIL ▼ 63.42",
    "USDJPY ▲ 142.88", "SP500 ▲ 5,218", "VIX ▼ 18.2",
    "GOLD ▲ 3,342.10", "BTC ▲ 84,250", "OIL ▼ 63.42",
  ];
  return (
    <div className="overflow-hidden border-b border-green-500/20 bg-black/40 py-1.5">
      <div className="flex gap-8 animate-[ticker_20s_linear_infinite] whitespace-nowrap">
        {tickers.map((t, i) => (
          <span key={i} className={`text-[11px] font-mono font-bold ${t.includes("▲") ? "text-green-400" : "text-red-400"}`}>
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

function AgentDesk({
  agent,
  onClick,
  isActive,
}: {
  agent: AgentPrompt;
  onClick: () => void;
  isActive: boolean;
}) {
  const cfg = AGENT_CONFIG[agent.id] ?? {
    avatar: "🤖", role: agent.name, deskColor: "border-zinc-500/50 bg-zinc-500/5",
    glowColor: "shadow-zinc-500/20", floorArea: "—",
  };
  const badge = MODEL_BADGE[agent.model] ?? { label: agent.model, color: "text-muted-foreground border-border bg-muted" };

  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        relative group text-left w-full rounded-none border-2 p-4
        transition-all duration-200 cursor-pointer
        ${cfg.deskColor}
        hover:scale-[1.02] hover:shadow-lg hover:${cfg.glowColor}
        active:scale-[0.98]
        ${isActive ? "ring-2 ring-primary/60" : ""}
      `}
    >
      {/* Floor label */}
      <p className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest mb-2 opacity-70">
        {cfg.floorArea}
      </p>

      {/* Desk surface */}
      <div className="flex items-start gap-3">
        {/* Character + monitor */}
        <div className="flex flex-col items-center gap-1 shrink-0">
          <span className="text-3xl leading-none">{cfg.avatar}</span>
          <div className="text-muted-foreground">
            <Monitor active />
          </div>
        </div>

        {/* Name plate */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-sm font-bold text-foreground">{agent.name}</span>
            <Badge variant="outline" className={`text-[9px] px-1.5 py-0 ${badge.color}`}>
              {badge.label}
            </Badge>
            {agent.is_customized && (
              <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-primary/10 text-primary border-primary/30">
                ✎ Custom
              </Badge>
            )}
          </div>
          <p className="text-[11px] text-primary/80 font-mono mt-0.5">{cfg.role}</p>
          <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2">{agent.description}</p>
        </div>
      </div>

      {/* Status bar */}
      <div className="mt-3 flex items-center gap-2">
        <span className="size-1.5 rounded-full bg-green-400 animate-pulse" />
        <span className="text-[10px] font-mono text-green-400">ONLINE</span>
        <span className="text-[10px] text-muted-foreground ml-auto">Click to configure →</span>
      </div>
    </button>
  );
}

export default function AgentPromptsPage() {
  const [agents, setAgents] = useState<AgentPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<AgentPrompt | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await getAgentPrompts();
      setAgents(res.data.agents || []);
    } catch {
      showError("Failed to load agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openDesk = (agent: AgentPrompt) => {
    setSelected(agent);
    setEditValue(agent.active_prompt);
  };

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await updateAgentPrompt(selected.id, editValue);
      await fetchData();
      showSuccess("Prompt saved");
      setSelected(s => s ? { ...s, active_prompt: editValue, is_customized: true } : null);
    } catch { showError("Failed to save prompt"); }
    finally { setSaving(false); }
  };

  const handleReset = async () => {
    if (!selected) return;
    if (!confirm("Reset to default prompt?")) return;
    setResetting(true);
    try {
      await resetAgentPrompt(selected.id);
      await fetchData();
      showSuccess("Prompt reset");
      setSelected(s => s ? { ...s, active_prompt: s.default_prompt, is_customized: false } : null);
      setEditValue(selected.default_prompt);
    } catch { showError("Failed to reset"); }
    finally { setResetting(false); }
  };

  const isDirty = selected && editValue !== selected.active_prompt;

  // Split into floor sections: orchestrator top, 3 analysts middle, rest bottom
  const orchestrator = agents.filter(a => a.id === "orchestrator");
  const analysts = agents.filter(a => ["technical", "fundamental", "risk"].includes(a.id));
  const others = agents.filter(a => !["orchestrator", "technical", "fundamental", "risk"].includes(a.id));

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-3 gap-2">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-40 rounded-none" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-0 page-enter">
      {/* Floor header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight font-mono">
            🏢 AI Trading Floor
          </h1>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">
            {agents.length} agents online — click desk to configure system prompt
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchData}
          className="text-xs rounded-none font-mono gap-1.5"
        >
          <RefreshCw className="size-3" />
          Refresh
        </Button>
      </div>

      {/* Ticker tape */}
      <TickerTape />

      {/* Trading floor grid */}
      <div className="border-2 border-border trading-floor-grid p-0">
        {/* Floor label */}
        <div className="border-b border-green-500/20 bg-green-500/5 px-4 py-1.5">
          <p className="text-[10px] font-mono text-green-500/70 uppercase tracking-widest">◉ TRADING FLOOR — ACTIVE</p>
        </div>

        {/* Orchestrator — full width top */}
        {orchestrator.length > 0 && (
          <div className="border-b-2 border-border">
            <div className="px-2 py-1 bg-blue-500/5 border-b border-blue-500/20">
              <p className="text-[9px] font-mono text-blue-400/70 uppercase tracking-widest">⬛ Head Office</p>
            </div>
            <div className="p-2">
              {orchestrator.map(a => (
                <AgentDesk key={a.id} agent={a} onClick={() => openDesk(a)} isActive={selected?.id === a.id} />
              ))}
            </div>
          </div>
        )}

        {/* Analysts — 3 columns */}
        {analysts.length > 0 && (
          <div className="border-b-2 border-border">
            <div className="px-2 py-1 bg-muted/30 border-b border-border">
              <p className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">⬛ Analysis Room</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 divide-x-2 divide-border p-0">
              {analysts.map(a => (
                <div key={a.id} className="p-2">
                  <AgentDesk agent={a} onClick={() => openDesk(a)} isActive={selected?.id === a.id} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Others — reflector + single agent */}
        {others.length > 0 && (
          <div>
            <div className="px-2 py-1 bg-muted/20 border-b border-border">
              <p className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">⬛ Support Desks</p>
            </div>
            <div className={`grid grid-cols-1 sm:grid-cols-${Math.min(others.length, 3)} divide-x-2 divide-border p-0`}>
              {others.map(a => (
                <div key={a.id} className="p-2">
                  <AgentDesk agent={a} onClick={() => openDesk(a)} isActive={selected?.id === a.id} />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Bottom status bar */}
      <div className="border-2 border-t-0 border-border bg-black/60 px-4 py-2 flex items-center gap-4 font-mono text-[10px]">
        <span className="text-green-400">● SYSTEM ONLINE</span>
        <span className="text-muted-foreground">|</span>
        <span className="text-muted-foreground">
          {agents.filter(a => a.is_customized).length} custom prompts active
        </span>
        <span className="text-muted-foreground ml-auto">
          Changes apply on next agent invocation
        </span>
      </div>

      {/* Prompt editor dialog */}
      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null); }}>
        <DialogContent className="max-w-2xl rounded-none border-2">
          {selected && (() => {
            const cfg = AGENT_CONFIG[selected.id];
            const badge = MODEL_BADGE[selected.model] ?? { label: selected.model, color: "text-muted-foreground" };
            return (
              <>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2 font-mono">
                    <span className="text-2xl">{cfg?.avatar ?? "🤖"}</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span>{selected.name}</span>
                        <Badge variant="outline" className={`text-[9px] ${badge.color}`}>{badge.label}</Badge>
                        {selected.is_customized && (
                          <Badge variant="outline" className="text-[9px] bg-primary/10 text-primary border-primary/30">✎ Custom</Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground font-normal mt-0.5">{selected.description}</p>
                    </div>
                  </DialogTitle>
                  <DialogDescription className="text-[10px] font-mono text-muted-foreground">
                    {cfg?.floorArea} · {cfg?.role}
                  </DialogDescription>
                </DialogHeader>

                <textarea
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className="w-full h-72 border border-border bg-black/60 p-3 text-xs font-mono leading-relaxed resize-y focus:outline-none focus:ring-2 focus:ring-primary/50 rounded-none"
                  spellCheck={false}
                  aria-label={`System prompt for ${selected.name}`}
                />

                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono text-muted-foreground">
                    {editValue.length.toLocaleString()} chars
                    {isDirty && <span className="text-amber-400 ml-2">● unsaved</span>}
                  </span>
                  <div className="flex gap-2">
                    {selected.is_customized && (
                      <Button variant="outline" size="sm" onClick={handleReset} disabled={resetting} className="rounded-none text-xs font-mono">
                        <RotateCcw className="size-3 mr-1" />
                        {resetting ? "Resetting..." : "Reset Default"}
                      </Button>
                    )}
                    <Button size="sm" onClick={handleSave} disabled={!isDirty || saving || editValue.length < 10} className="rounded-none text-xs font-mono">
                      <Save className="size-3 mr-1" />
                      {saving ? "Saving..." : "Save Prompt"}
                    </Button>
                  </div>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}
