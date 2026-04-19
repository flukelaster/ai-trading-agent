"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ASSET_CLASSES, type AssetClass, type SymbolConfig, type SymbolConfigInput } from "@/lib/api";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"] as const;

interface SymbolFormProps {
  initial?: SymbolConfig;
  onSubmit: (input: SymbolConfigInput) => Promise<void>;
  onCancel: () => void;
  onValidateAlias?: (alias: string) => Promise<void>;
  submitting?: boolean;
}

type FormState = {
  symbol: string;
  display_name: string;
  broker_alias: string;
  asset_class: AssetClass;
  default_timeframe: string;
  pip_value: string;
  default_lot: string;
  max_lot: string;
  price_decimals: string;
  sl_atr_mult: string;
  tp_atr_mult: string;
  contract_size: string;
  ml_tp_pips: string;
  ml_sl_pips: string;
  ml_forward_bars: string;
  ml_timeframe: string;
};

function toFormState(cfg?: SymbolConfig): FormState {
  return {
    symbol: cfg?.symbol ?? "",
    display_name: cfg?.display_name ?? "",
    broker_alias: cfg?.broker_alias ?? "",
    asset_class: cfg?.asset_class ?? "forex",
    default_timeframe: cfg?.default_timeframe ?? "M15",
    pip_value: String(cfg?.pip_value ?? ""),
    default_lot: String(cfg?.default_lot ?? ""),
    max_lot: String(cfg?.max_lot ?? ""),
    price_decimals: String(cfg?.price_decimals ?? 2),
    sl_atr_mult: String(cfg?.sl_atr_mult ?? 1.5),
    tp_atr_mult: String(cfg?.tp_atr_mult ?? 2.0),
    contract_size: String(cfg?.contract_size ?? 1),
    ml_tp_pips: String(cfg?.ml_tp_pips ?? ""),
    ml_sl_pips: String(cfg?.ml_sl_pips ?? ""),
    ml_forward_bars: String(cfg?.ml_forward_bars ?? 10),
    ml_timeframe: cfg?.ml_timeframe ?? "M15",
  };
}

function toPayload(state: FormState): SymbolConfigInput {
  return {
    symbol: state.symbol.trim(),
    display_name: state.display_name.trim(),
    broker_alias: state.broker_alias.trim() || null,
    asset_class: state.asset_class,
    default_timeframe: state.default_timeframe,
    pip_value: Number(state.pip_value),
    default_lot: Number(state.default_lot),
    max_lot: Number(state.max_lot),
    price_decimals: Number(state.price_decimals),
    sl_atr_mult: Number(state.sl_atr_mult),
    tp_atr_mult: Number(state.tp_atr_mult),
    contract_size: Number(state.contract_size),
    ml_tp_pips: Number(state.ml_tp_pips),
    ml_sl_pips: Number(state.ml_sl_pips),
    ml_forward_bars: Number(state.ml_forward_bars),
    ml_timeframe: state.ml_timeframe,
  };
}

function validate(state: FormState): string | null {
  if (!state.symbol.match(/^[A-Za-z0-9._-]{2,32}$/)) return "Symbol must be 2-32 alphanumeric chars";
  if (!state.display_name) return "Display name required";
  const nums = [
    ["pip_value", state.pip_value],
    ["default_lot", state.default_lot],
    ["max_lot", state.max_lot],
    ["contract_size", state.contract_size],
    ["ml_tp_pips", state.ml_tp_pips],
    ["ml_sl_pips", state.ml_sl_pips],
  ] as const;
  for (const [field, raw] of nums) {
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) return `${field} must be > 0`;
  }
  if (Number(state.default_lot) > Number(state.max_lot)) {
    return "default_lot must be <= max_lot";
  }
  return null;
}

export function SymbolForm({
  initial,
  onSubmit,
  onCancel,
  onValidateAlias,
  submitting,
}: SymbolFormProps) {
  const [state, setState] = useState<FormState>(toFormState(initial));
  const [error, setError] = useState<string | null>(null);

  const isEdit = Boolean(initial);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setState((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validate(state);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    await onSubmit(toPayload(state));
  };

  const handleValidate = async () => {
    if (!onValidateAlias) return;
    const alias = state.broker_alias.trim() || state.symbol.trim();
    if (!alias) {
      setError("Enter a symbol or broker alias first");
      return;
    }
    await onValidateAlias(alias);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Symbol (canonical)" required>
          <Input
            value={state.symbol}
            onChange={(e) => update("symbol", e.target.value)}
            disabled={isEdit}
            placeholder="EURUSD"
          />
        </Field>
        <Field label="Display name" required>
          <Input
            value={state.display_name}
            onChange={(e) => update("display_name", e.target.value)}
            placeholder="Euro/Dollar"
          />
        </Field>
        <Field label="Broker alias (e.g. EURUSDmicro)">
          <div className="flex gap-2">
            <Input
              value={state.broker_alias}
              onChange={(e) => update("broker_alias", e.target.value)}
              placeholder="optional"
            />
            {onValidateAlias && (
              <Button type="button" variant="outline" size="sm" onClick={handleValidate}>
                Validate
              </Button>
            )}
          </div>
        </Field>
        <Field label="Default timeframe">
          <Select
            value={state.default_timeframe}
            onValueChange={(v) => update("default_timeframe", v as string)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TIMEFRAMES.map((tf) => (
                <SelectItem key={tf} value={tf}>
                  {tf}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Asset class" required>
          <Select
            value={state.asset_class}
            onValueChange={(v) => update("asset_class", v as AssetClass)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ASSET_CLASSES.map((cls) => (
                <SelectItem key={cls} value={cls}>
                  {cls}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Pip value" required>
          <Input
            type="number"
            step="any"
            value={state.pip_value}
            onChange={(e) => update("pip_value", e.target.value)}
          />
        </Field>
        <Field label="Price decimals">
          <Input
            type="number"
            value={state.price_decimals}
            onChange={(e) => update("price_decimals", e.target.value)}
          />
        </Field>
        <Field label="Default lot" required>
          <Input
            type="number"
            step="any"
            value={state.default_lot}
            onChange={(e) => update("default_lot", e.target.value)}
          />
        </Field>
        <Field label="Max lot" required>
          <Input
            type="number"
            step="any"
            value={state.max_lot}
            onChange={(e) => update("max_lot", e.target.value)}
          />
        </Field>
        <Field label="SL ATR multiplier">
          <Input
            type="number"
            step="any"
            value={state.sl_atr_mult}
            onChange={(e) => update("sl_atr_mult", e.target.value)}
          />
        </Field>
        <Field label="TP ATR multiplier">
          <Input
            type="number"
            step="any"
            value={state.tp_atr_mult}
            onChange={(e) => update("tp_atr_mult", e.target.value)}
          />
        </Field>
        <Field label="Contract size" required>
          <Input
            type="number"
            step="any"
            value={state.contract_size}
            onChange={(e) => update("contract_size", e.target.value)}
          />
        </Field>
        <Field label="ML timeframe">
          <Select
            value={state.ml_timeframe}
            onValueChange={(v) => update("ml_timeframe", v as string)}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TIMEFRAMES.map((tf) => (
                <SelectItem key={tf} value={tf}>
                  {tf}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="ML TP pips" required>
          <Input
            type="number"
            step="any"
            value={state.ml_tp_pips}
            onChange={(e) => update("ml_tp_pips", e.target.value)}
          />
        </Field>
        <Field label="ML SL pips" required>
          <Input
            type="number"
            step="any"
            value={state.ml_sl_pips}
            onChange={(e) => update("ml_sl_pips", e.target.value)}
          />
        </Field>
        <Field label="ML forward bars">
          <Input
            type="number"
            value={state.ml_forward_bars}
            onChange={(e) => update("ml_forward_bars", e.target.value)}
          />
        </Field>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting}>
          {submitting ? "Saving..." : isEdit ? "Save changes" : "Create symbol"}
        </Button>
      </div>
    </form>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-muted-foreground">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </span>
      {children}
    </label>
  );
}
