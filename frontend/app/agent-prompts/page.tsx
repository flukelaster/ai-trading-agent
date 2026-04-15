"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Settings2, RotateCcw, Save, ChevronDown, ChevronUp } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
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

const MODEL_BADGE: Record<string, { label: string; className: string }> = {
  "claude-sonnet-4-20250514": { label: "Sonnet", className: "bg-blue-500/10 text-blue-400 border-blue-500/30" },
  "claude-haiku-4-5-20251001": { label: "Haiku", className: "bg-amber-500/10 text-amber-400 border-amber-500/30" },
};

function AgentPromptCard({
  agent,
  onSave,
  onReset,
}: {
  agent: AgentPrompt;
  onSave: (id: string, prompt: string) => Promise<void>;
  onReset: (id: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [value, setValue] = useState(agent.active_prompt);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const isDirty = value !== agent.active_prompt;
  const badge = MODEL_BADGE[agent.model] || { label: agent.model, className: "bg-muted text-muted-foreground" };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(agent.id, value);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("Reset prompt to default? Custom changes will be lost.")) return;
    setResetting(true);
    try {
      await onReset(agent.id);
      setValue(agent.default_prompt);
    } finally {
      setResetting(false);
    }
  };

  return (
    <Card>
      <CardHeader className="p-4 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <CardTitle className="text-sm font-bold flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>{agent.name}</span>
            <Badge variant="outline" className={`text-[10px] px-2 py-0 ${badge.className}`}>
              {badge.label}
            </Badge>
            {agent.is_customized && (
              <Badge variant="outline" className="text-[10px] px-2 py-0 bg-primary/10 text-primary border-primary/30">
                Custom
              </Badge>
            )}
          </div>
          {expanded ? <ChevronUp className="size-4 text-muted-foreground" /> : <ChevronDown className="size-4 text-muted-foreground" />}
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">{agent.description}</p>
      </CardHeader>

      {expanded && (
        <CardContent className="p-4 pt-0 space-y-3">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full h-64 rounded-lg border border-border bg-background p-3 text-xs font-mono leading-relaxed resize-y focus:outline-none focus:ring-2 focus:ring-primary/50"
            spellCheck={false}
          />
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-muted-foreground">
              {value.length.toLocaleString()} chars
            </span>
            <div className="flex items-center gap-2">
              {agent.is_customized && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleReset}
                  disabled={resetting}
                  className="text-xs"
                >
                  <RotateCcw className="size-3 mr-1" />
                  {resetting ? "Resetting..." : "Reset Default"}
                </Button>
              )}
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!isDirty || saving || value.length < 10}
                className="text-xs"
              >
                <Save className="size-3 mr-1" />
                {saving ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export default function AgentPromptsPage() {
  const [agents, setAgents] = useState<AgentPrompt[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await getAgentPrompts();
      setAgents(res.data.agents || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSave = async (id: string, prompt: string) => {
    try {
      await updateAgentPrompt(id, prompt);
      await fetchData();
      showSuccess("Prompt saved");
    } catch {
      showError("Failed to save prompt");
    }
  };

  const handleReset = async (id: string) => {
    try {
      await resetAgentPrompt(id);
      await fetchData();
      showSuccess("Prompt reset to default");
    } catch {
      showError("Failed to reset prompt");
    }
  };

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader
        title="Agent Prompts"
        subtitle="View and customize system prompts for AI trading agents"
      >
        <Button variant="outline" size="sm" onClick={fetchData} className="text-xs">
          Refresh
        </Button>
      </PageHeader>

      <PageInstructions
        items={[
          "Click an agent card to expand and view/edit its system prompt.",
          "Changes take effect on the next agent invocation — no restart needed.",
          "Use 'Reset Default' to revert to the hardcoded prompt.",
        ]}
      />

      <div className="space-y-3">
        {agents.map((agent) => (
          <AgentPromptCard
            key={agent.id}
            agent={agent}
            onSave={handleSave}
            onReset={handleReset}
          />
        ))}
      </div>
    </div>
  );
}
