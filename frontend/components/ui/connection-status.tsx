"use client";

import { useBotStore } from "@/store/botStore";
import { cn } from "@/lib/utils";

export function ConnectionStatus() {
  const wsConnected = useBotStore((s) => s.wsConnected);
  const lastSyncAt = useBotStore((s) => s.lastSyncAt);

  const statusColor = wsConnected
    ? "bg-emerald-500"
    : "bg-destructive";

  const statusLabel = wsConnected ? "Live" : "Offline";

  const timeAgo = lastSyncAt ? getTimeAgo(lastSyncAt) : null;

  return (
    <div className="flex items-center gap-2 min-w-0" title={timeAgo ? `Last sync: ${timeAgo}` : statusLabel}>
      <span className="relative flex size-2">
        <span
          className={cn(
            "absolute inline-flex size-full rounded-full opacity-75",
            wsConnected && "animate-ping",
            statusColor
          )}
        />
        <span
          className={cn("relative inline-flex size-2 rounded-full", statusColor)}
        />
      </span>
      <span className="text-[10px] font-semibold text-muted-foreground">
        {statusLabel}
      </span>
      {timeAgo && (
        <span className="text-[10px] text-muted-foreground/50 truncate">
          {timeAgo}
        </span>
      )}
    </div>
  );
}

function getTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}
