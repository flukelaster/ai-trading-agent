"use client";

import { cn } from "@/lib/utils";

interface CorrelationHeatmapProps {
  matrix: Record<string, number>; // "GOLD_BTCUSD" → 0.3
  symbols?: string[];
  className?: string;
}

function getColor(value: number): string {
  if (value >= 0.7) return "bg-green-500 text-white";
  if (value >= 0.3) return "bg-green-500/40 text-green-200";
  if (value > -0.3) return "bg-muted text-muted-foreground";
  if (value > -0.7) return "bg-red-500/40 text-red-200";
  return "bg-red-500 text-white";
}

export function CorrelationHeatmap({
  matrix,
  symbols = [],
  className,
}: CorrelationHeatmapProps) {
  const getCorr = (a: string, b: string): number | null => {
    if (a === b) return 1;
    const key1 = `${a}_${b}`;
    const key2 = `${b}_${a}`;
    if (key1 in matrix) return matrix[key1];
    if (key2 in matrix) return matrix[key2];
    return null;
  };

  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="border-collapse">
        <thead>
          <tr>
            <th className="p-1.5 text-[10px] text-muted-foreground" />
            {symbols.map((s) => (
              <th key={s} className="p-1.5 text-[10px] text-muted-foreground font-semibold text-center">
                {s.slice(0, 4)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row) => (
            <tr key={row}>
              <td className="p-1.5 text-[10px] text-muted-foreground font-semibold">{row.slice(0, 4)}</td>
              {symbols.map((col) => {
                const corr = getCorr(row, col);
                return (
                  <td key={col} className="p-0.5">
                    <div
                      className={cn(
                        "w-10 h-8 rounded flex items-center justify-center text-[10px] font-mono font-bold",
                        corr !== null ? getColor(corr) : "bg-muted/50 text-muted-foreground/50",
                      )}
                    >
                      {corr !== null ? corr.toFixed(2) : "—"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
