"use client";

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { CandlestickChart } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createSymbolConfig,
  deleteSymbolConfig,
  listSymbolConfigs,
  retrainSymbolConfig,
  toggleSymbolConfig,
  updateSymbolConfig,
  validateSymbolConfig,
  type SymbolConfig,
  type SymbolConfigInput,
} from "@/lib/api";
import { SymbolForm } from "./SymbolForm";

function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) return detail[0].msg ?? "Validation error";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

const ML_STATUS_STYLE: Record<string, string> = {
  ready: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  training: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  failed: "bg-red-500/10 text-red-500 border-red-500/20",
  pending: "bg-amber-500/10 text-amber-500 border-amber-500/20",
};

export default function SymbolsPage() {
  const [configs, setConfigs] = useState<SymbolConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SymbolConfig | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const resp = await listSymbolConfigs();
        if (active) setConfigs(resp.data);
      } catch (err) {
        if (active) setBanner({ kind: "err", msg: errorMessage(err) });
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const upsertLocal = (cfg: SymbolConfig) =>
    setConfigs((prev) => {
      const i = prev.findIndex((c) => c.symbol === cfg.symbol);
      if (i === -1) return [...prev, cfg];
      const next = prev.slice();
      next[i] = cfg;
      return next;
    });

  const removeLocal = (symbol: string) =>
    setConfigs((prev) => prev.filter((c) => c.symbol !== symbol));

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (cfg: SymbolConfig) => {
    setEditing(cfg);
    setDialogOpen(true);
  };

  const handleSubmit = async (input: SymbolConfigInput) => {
    setSubmitting(true);
    try {
      if (editing) {
        const { symbol: _omit, ...rest } = input;
        void _omit;
        const resp = await updateSymbolConfig(editing.symbol, rest);
        upsertLocal(resp.data);
        setBanner({ kind: "ok", msg: `Updated ${editing.symbol}` });
      } else {
        const resp = await createSymbolConfig(input);
        upsertLocal(resp.data);
        setBanner({ kind: "ok", msg: `Created ${input.symbol}` });
      }
      setDialogOpen(false);
    } catch (err) {
      setBanner({ kind: "err", msg: errorMessage(err) });
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (cfg: SymbolConfig) => {
    try {
      const resp = await toggleSymbolConfig(cfg.symbol);
      upsertLocal(resp.data);
    } catch (err) {
      setBanner({ kind: "err", msg: errorMessage(err) });
    }
  };

  const handleDelete = async (cfg: SymbolConfig) => {
    if (
      !confirm(
        `Delete ${cfg.symbol}? This disables the symbol and removes it from the active list.`,
      )
    ) {
      return;
    }
    try {
      await deleteSymbolConfig(cfg.symbol);
      removeLocal(cfg.symbol);
      setBanner({ kind: "ok", msg: `Deleted ${cfg.symbol}` });
    } catch (err) {
      setBanner({ kind: "err", msg: errorMessage(err) });
    }
  };

  const handleRetrain = async (cfg: SymbolConfig) => {
    try {
      await retrainSymbolConfig(cfg.symbol);
      upsertLocal({ ...cfg, ml_status: "training" });
      setBanner({ kind: "ok", msg: `Queued retrain for ${cfg.symbol}` });
    } catch (err) {
      setBanner({ kind: "err", msg: errorMessage(err) });
    }
  };

  const handleValidate = async (cfg: SymbolConfig) => {
    try {
      const resp = await validateSymbolConfig(cfg.symbol);
      if (resp.data.ok) {
        setBanner({
          kind: "ok",
          msg: `${cfg.symbol}: broker spec OK (digits ${resp.data.spec?.digits}, min lot ${resp.data.spec?.volume_min})`,
        });
      } else {
        setBanner({ kind: "err", msg: `${cfg.symbol}: ${resp.data.message}` });
      }
    } catch (err) {
      setBanner({ kind: "err", msg: errorMessage(err) });
    }
  };

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader
        title="Symbols"
        subtitle="Manage tradable instruments, profiles, and broker aliases"
      >
        <Button onClick={openCreate}>Add Symbol</Button>
      </PageHeader>

      <PageInstructions
        items={[
          "Add, enable, or edit trading symbols. Edits hot-reload across BotManager without restart.",
          "Validate the broker alias before enabling — the bot queries MT5 Bridge for lot limits, digits, and contract size.",
          "New symbols need ML training before they can trade. Click Retrain to queue a training job.",
        ]}
      />

      {banner && (
        <div
          className={
            "rounded-xl border px-4 py-3 text-sm " +
            (banner.kind === "ok"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-destructive/40 bg-destructive/10 text-destructive")
          }
        >
          {banner.msg}
        </div>
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-12 text-sm">Loading symbols...</div>
      ) : configs.length === 0 ? (
        <EmptyState
          icon={CandlestickChart}
          heading="No symbols configured"
          description='Click "Add Symbol" to create the first trading instrument.'
          action={{ label: "Add Symbol", onClick: openCreate }}
        />
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted-foreground bg-muted/30">
                  <th className="px-4 py-3 font-medium">Symbol</th>
                  <th className="px-4 py-3 font-medium">Display</th>
                  <th className="px-4 py-3 font-medium">Broker alias</th>
                  <th className="px-4 py-3 font-medium">Class</th>
                  <th className="px-4 py-3 font-medium">TF</th>
                  <th className="px-4 py-3 font-medium">Lot (def / max)</th>
                  <th className="px-4 py-3 font-medium">SL / TP ATR</th>
                  <th className="px-4 py-3 font-medium">ML</th>
                  <th className="px-4 py-3 font-medium">Enabled</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((cfg) => (
                  <tr
                    key={cfg.symbol}
                    className="border-b border-border/50 last:border-b-0 hover:bg-muted/20 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono font-semibold">{cfg.symbol}</td>
                    <td className="px-4 py-3 text-muted-foreground">{cfg.display_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      {cfg.broker_alias ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground capitalize">
                      {cfg.asset_class}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{cfg.default_timeframe}</td>
                    <td className="px-4 py-3 tabular-nums">
                      {cfg.default_lot} / {cfg.max_lot}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">
                      {cfg.sl_atr_mult} / {cfg.tp_atr_mult}
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className={
                          ML_STATUS_STYLE[cfg.ml_status] ??
                          "bg-muted/40 text-muted-foreground border-border"
                        }
                      >
                        {cfg.ml_status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Switch
                        checked={cfg.is_enabled}
                        onCheckedChange={() => void handleToggle(cfg)}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void handleValidate(cfg)}
                        >
                          Validate
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => void handleRetrain(cfg)}>
                          Retrain
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => openEdit(cfg)}>
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => void handleDelete(cfg)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.symbol}` : "Add symbol"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "Update trading profile. Changes apply immediately via hot-reload."
                : "Create a new symbol profile. Validate the broker alias before enabling."}
            </DialogDescription>
          </DialogHeader>
          <SymbolForm
            key={editing?.symbol ?? "new"}
            initial={editing ?? undefined}
            onSubmit={handleSubmit}
            onCancel={() => setDialogOpen(false)}
            submitting={submitting}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
