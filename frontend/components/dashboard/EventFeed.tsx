"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { TrendingUp, TrendingDown, XCircle, AlertTriangle, Brain, Activity } from "lucide-react";
import type { BotEvent } from "@/store/botStore";

const eventConfig: Record<string, { icon: typeof Activity; color: string }> = {
  trade_opened: { icon: TrendingUp, color: "text-green-400" },
  trade_closed: { icon: TrendingDown, color: "text-amber-400" },
  error: { icon: XCircle, color: "text-red-400" },
  circuit_breaker: { icon: AlertTriangle, color: "text-red-400" },
  sentiment: { icon: Brain, color: "text-blue-400" },
};

function formatTime(timestamp: string) {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return date.toLocaleDateString();
  } catch {
    return "";
  }
}

export default function EventFeed({ events }: { events: BotEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No events yet
      </p>
    );
  }

  return (
    <ScrollArea className="h-64">
      <div className="space-y-1 pr-3">
        {events.map((event, i) => {
          const config = eventConfig[event.type] || { icon: Activity, color: "text-muted-foreground" };
          const Icon = config.icon;
          return (
            <div key={i} className="flex items-start gap-2 py-1.5 border-b border-border/30 last:border-0">
              <Icon className={`size-3.5 mt-0.5 shrink-0 ${config.color}`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-foreground truncate">{event.message}</p>
                <p className="text-[10px] text-muted-foreground">{formatTime(event.timestamp)}</p>
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
