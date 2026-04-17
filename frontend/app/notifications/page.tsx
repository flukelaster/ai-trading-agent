"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getBotEvents } from "@/lib/api";
import { Bell } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";
import { EmptyState } from "@/components/ui/empty-state";

interface BotEvent {
  id: number;
  type: string;
  message: string;
  created_at: string;
}

const EVENT_COLORS: Record<string, string> = {
  TRADE_OPENED: "text-green-600 dark:text-green-400",
  TRADE_CLOSED: "text-amber-600 dark:text-amber-400",
  SIGNAL_DETECTED: "text-blue-600 dark:text-blue-400",
  TRADE_BLOCKED: "text-orange-600 dark:text-orange-400",
  ORDER_FAILED: "text-red-600 dark:text-red-400",
  ERROR: "text-red-600 dark:text-red-400",
  CIRCUIT_BREAKER: "text-red-700 dark:text-red-300",
  SETTINGS_CHANGED: "text-purple-600 dark:text-purple-400",
  STRATEGY_CHANGED: "text-purple-600 dark:text-purple-400",
  STARTED: "text-green-600 dark:text-green-400",
  STOPPED: "text-gray-600 dark:text-gray-400",
};

const PAGE_SIZE = 30;

export default function NotificationsPage() {
  const [events, setEvents] = useState<BotEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    const fetchEvents = async () => {
      setLoading(true);
      try {
        const res = await getBotEvents({ days, event_type: typeFilter || undefined, limit: 500 });
        setEvents(res.data.events || []);
        setVisibleCount(PAGE_SIZE);
      } catch {
        setEvents([]);
      } finally {
        setLoading(false);
      }
    };
    fetchEvents();
  }, [days, typeFilter]);

  const visibleEvents = useMemo(
    () => events.slice(0, visibleCount),
    [events, visibleCount],
  );
  const hasMore = visibleCount < events.length;

  useEffect(() => {
    if (!hasMore) return;
    const node = sentinelRef.current;
    if (!node) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisibleCount((n) => Math.min(n + PAGE_SIZE, events.length));
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [hasMore, events.length]);

  const eventTypes = [
    "", "STARTED", "STOPPED", "TRADE_OPENED", "TRADE_CLOSED",
    "SIGNAL_DETECTED", "TRADE_BLOCKED", "ORDER_FAILED", "ERROR",
    "CIRCUIT_BREAKER", "SETTINGS_CHANGED", "STRATEGY_CHANGED",
  ];

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6 page-enter">
      <PageHeader title="Notifications" subtitle="Bot event history and alerts" />

      <PageInstructions
        items={[
          "Bot event notifications in chronological order, color-coded by type.",
          "Trade events in green, errors in red, settings changes in purple. Filter by time range and type.",
        ]}
      />

      <div className="flex flex-wrap gap-3">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
        >
          <option value={1}>Last 24h</option>
          <option value={3}>Last 3 days</option>
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
        </select>

        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
        >
          <option value="">All types</option>
          {eventTypes.filter(Boolean).map((t) => (
            <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
          ))}
        </select>

        <span className="text-xs text-muted-foreground self-center ml-auto">
          {visibleEvents.length} / {events.length} events
        </span>
      </div>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">Loading...</div>
      ) : events.length === 0 ? (
        <EmptyState icon={Bell} heading="No events found" description="Notifications will appear here when events occur" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="pb-2 pr-4 font-medium">Time</th>
                <th className="pb-2 pr-4 font-medium">Type</th>
                <th className="pb-2 font-medium">Message</th>
              </tr>
            </thead>
            <tbody>
              {visibleEvents.map((e) => (
                <tr key={e.id} className="border-b border-border/50">
                  <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
                    {new Date(e.created_at).toLocaleString("en-GB", { timeZone: "Asia/Bangkok" })}
                  </td>
                  <td className={`py-2 pr-4 whitespace-nowrap font-medium ${EVENT_COLORS[e.type] || ""}`}>
                    {e.type.replace(/_/g, " ")}
                  </td>
                  <td className="py-2">{e.message}</td>
                </tr>
              ))}
              {hasMore && (
                <tr ref={sentinelRef}>
                  <td colSpan={3} className="py-4 text-center text-xs text-muted-foreground">
                    Loading more...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
