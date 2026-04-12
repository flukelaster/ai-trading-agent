"use client";

import { useEffect, useState } from "react";
import { getBotEvents } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageInstructions } from "@/components/layout/PageInstructions";

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

export default function NotificationsPage() {
  const [events, setEvents] = useState<BotEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [typeFilter, setTypeFilter] = useState<string>("");

  useEffect(() => {
    const fetchEvents = async () => {
      setLoading(true);
      try {
        const res = await getBotEvents({ days, event_type: typeFilter || undefined, limit: 500 });
        setEvents(res.data.events || []);
      } catch {
        setEvents([]);
      } finally {
        setLoading(false);
      }
    };
    fetchEvents();
  }, [days, typeFilter]);

  const eventTypes = [
    "", "STARTED", "STOPPED", "TRADE_OPENED", "TRADE_CLOSED",
    "SIGNAL_DETECTED", "TRADE_BLOCKED", "ORDER_FAILED", "ERROR",
    "CIRCUIT_BREAKER", "SETTINGS_CHANGED", "STRATEGY_CHANGED",
  ];

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      <PageHeader title="Notifications" subtitle="Bot event history and alerts" />

      <PageInstructions
        pageId="notifications"
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
      </div>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground">Loading...</div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">No events found</div>
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
              {events.map((e) => (
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
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
