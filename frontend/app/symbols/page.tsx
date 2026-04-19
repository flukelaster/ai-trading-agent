"use client";

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
    if (!confirm(`Delete ${cfg.symbol}? This disables the symbol and removes it from the active list.`)) {
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
    <div className="space-y-4">
      <PageHeader
        title="Symbols"
        subtitle="Manage tradable instruments, profiles, and broker aliases"
      >
        <Button onClick={openCreate}>Add Symbol</Button>
      </PageHeader>

      {banner && (
        <div
          className={
            banner.kind === "ok"
              ? "rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-600"
              : "rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          }
        >
          {banner.msg}
        </div>
      )}

      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead>Display</TableHead>
              <TableHead>Broker alias</TableHead>
              <TableHead>TF</TableHead>
              <TableHead>Lot (def / max)</TableHead>
              <TableHead>SL/TP ATR</TableHead>
              <TableHead>ML</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={9}>
                  <Skeleton className="h-24 w-full" />
                </TableCell>
              </TableRow>
            ) : configs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                  No symbols configured. Click &quot;Add Symbol&quot; to create one.
                </TableCell>
              </TableRow>
            ) : (
              configs.map((cfg) => (
                <TableRow key={cfg.symbol}>
                  <TableCell className="font-mono font-semibold">{cfg.symbol}</TableCell>
                  <TableCell>{cfg.display_name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {cfg.broker_alias ?? "—"}
                  </TableCell>
                  <TableCell>{cfg.default_timeframe}</TableCell>
                  <TableCell>
                    {cfg.default_lot} / {cfg.max_lot}
                  </TableCell>
                  <TableCell>
                    {cfg.sl_atr_mult} / {cfg.tp_atr_mult}
                  </TableCell>
                  <TableCell>
                    <Badge variant={cfg.ml_status === "ready" ? "default" : "outline"}>
                      {cfg.ml_status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={cfg.is_enabled}
                      onCheckedChange={() => void handleToggle(cfg)}
                    />
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button variant="ghost" size="sm" onClick={() => void handleValidate(cfg)}>
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
                      className="text-destructive"
                      onClick={() => void handleDelete(cfg)}
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

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
