"use client";

const DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"];

type TimeframeSelectorProps = {
  value: string;
  onChange: (tf: string) => void;
  options?: string[];
  size?: "sm" | "md";
};

export function TimeframeSelector({
  value,
  onChange,
  options = DEFAULT_TIMEFRAMES,
  size = "sm",
}: TimeframeSelectorProps) {
  return (
    <div className="flex gap-0.5 bg-muted rounded-xl p-0.5">
      {options.map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => onChange(tf)}
          className={`min-h-[32px] rounded-lg font-semibold transition-colors ${
            size === "sm" ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-xs"
          } ${
            value === tf
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}
