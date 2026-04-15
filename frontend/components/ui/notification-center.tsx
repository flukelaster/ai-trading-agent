"use client";

import { useState, useRef, useEffect } from "react";
import { Bell, AlertCircle, TrendingUp, Zap, Info } from "lucide-react";
import { useBotStore } from "@/store/botStore";
import type { BotEvent } from "@/store/botStore";
import { cn } from "@/lib/utils";

const eventIcons: Record<string, typeof Info> = {
  signal: TrendingUp,
  trade: TrendingUp,
  error: AlertCircle,
  warning: AlertCircle,
  system: Zap,
};

const eventColors: Record<string, string> = {
  signal: "text-primary",
  trade: "text-success",
  error: "text-destructive",
  warning: "text-warning",
  system: "text-muted-foreground",
};

function getTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const events = useBotStore((s) => s.events);
  const unreadCount = useBotStore((s) => s.unreadEventCount);
  const markRead = useBotStore((s) => s.markEventsRead);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleToggle = () => {
    if (!open) {
      markRead();
    }
    setOpen((prev) => !prev);
  };

  const displayEvents = events.slice(0, 20);

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={handleToggle}
        className="relative flex items-center justify-center size-8 rounded-full text-muted-foreground hover:text-foreground hover:bg-sidebar-accent transition-colors"
        aria-label="Notifications"
      >
        <Bell className="size-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center min-w-[16px] h-4 rounded-full bg-destructive text-[9px] font-bold text-white px-1 animate-badge-in">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 bottom-full mb-2 w-72 sm:w-80 rounded-xl border border-border bg-card shadow-xl z-50 animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-150">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
            <span className="text-xs font-semibold text-foreground">
              Notifications
            </span>
            <span className="text-[10px] text-muted-foreground">
              {events.length} events
            </span>
          </div>

          <div className="max-h-64 overflow-y-auto">
            {displayEvents.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-6">
                No events yet
              </p>
            ) : (
              displayEvents.map((event: BotEvent, i: number) => {
                const Icon =
                  eventIcons[event.type] || Info;
                const color =
                  eventColors[event.type] || "text-muted-foreground";
                return (
                  <div
                    key={i}
                    className="flex items-start gap-2.5 px-3 py-2 hover:bg-muted/50 transition-colors"
                  >
                    <Icon className={cn("size-3.5 mt-0.5 shrink-0", color)} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-foreground truncate">
                        {event.message}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        {getTimeAgo(event.timestamp)}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
