"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Globe, Calendar, RefreshCw, ArrowRightLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { getMacroLatest, getMacroCorrelations, getMacroEvents, collectMacro } from "@/lib/api";

export default function MacroPage() {
  const [snapshot, setSnapshot] = useState<Record<string, { name: string; value: number; date: string }>>({});
  const [correlations, setCorrelations] = useState<Record<string, { name: string; correlation: number; data_points: number }>>({});
  const [events, setEvents] = useState<{ type: string; name: string; date: string; impact: string; note: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [snapRes, corrRes, eventRes] = await Promise.all([
        getMacroLatest().catch(() => null),
        getMacroCorrelations().catch(() => null),
        getMacroEvents(30).catch(() => null),
      ]);
      if (snapRes?.data) setSnapshot(snapRes.data);
      if (corrRes?.data && !corrRes.data.error) setCorrelations(corrRes.data);
      if (eventRes?.data) setEvents(Array.isArray(eventRes.data) ? eventRes.data : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCollect = async () => {
    setCollecting(true);
    try {
      await collectMacro();
      await fetchData();
    } catch (e) { console.error(e); }
    finally { setCollecting(false); }
  };

  if (loading) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-60 rounded-2xl" />
          <Skeleton className="h-60 rounded-2xl" />
        </div>
      </div>
    );
  }

  const snapEntries = Object.entries(snapshot);
  const corrEntries = Object.entries(correlations);

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      <PageHeader title="Macro Data" subtitle="Economic indicators and gold correlations">
        <Button onClick={handleCollect} disabled={collecting} variant="outline" size="sm" className="rounded-full">
          <RefreshCw className={`size-4 mr-1.5 ${collecting ? "animate-spin" : ""}`} />
          {collecting ? "Collecting..." : "Refresh FRED Data"}
        </Button>
      </PageHeader>

      {/* Macro Snapshot */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <Globe className="size-4 text-primary-foreground dark:text-primary" />
            Economic Indicators (Latest)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {snapEntries.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {snapEntries.map(([id, data]) => (
                <div key={id} className="border border-border rounded-2xl p-4 space-y-1">
                  <p className="text-xs text-muted-foreground font-medium">{data.name}</p>
                  <p className="text-xl font-black">{typeof data.value === "number" ? data.value.toFixed(2) : data.value}</p>
                  <p className="text-xs text-muted-foreground font-medium">{data.date}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 space-y-3">
              <Globe className="size-10 text-muted-foreground/20 mx-auto" />
              <p className="text-sm text-muted-foreground font-medium">No macro data yet</p>
              <Button onClick={handleCollect} disabled={collecting} className="rounded-full bg-primary text-primary-foreground font-semibold hover-scale">
                <RefreshCw className="size-4 mr-1.5" />
                Collect from FRED
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Correlations */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <ArrowRightLeft className="size-4 text-primary-foreground dark:text-primary" />
              Gold Correlations (90 days)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {corrEntries.length > 0 ? (
              <div className="space-y-3">
                {corrEntries.map(([id, data]) => {
                  const corr = data.correlation;
                  const isNeg = corr < 0;
                  const absCorr = Math.abs(corr);
                  const strength = absCorr > 0.7 ? "Strong" : absCorr > 0.4 ? "Moderate" : "Weak";
                  return (
                    <div key={id} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold">{data.name}</span>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-xs rounded-full">{data.data_points} pts</Badge>
                          <span className={`text-sm font-mono font-bold ${isNeg ? "text-destructive" : "text-success dark:text-green-400"}`}>
                            {corr > 0 ? "+" : ""}{corr.toFixed(3)}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${isNeg ? "bg-destructive" : "bg-success dark:bg-green-400"}`}
                            style={{ width: `${absCorr * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground w-16 text-right font-medium">{strength}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8 font-medium">Collect macro data to see correlations</p>
            )}
          </CardContent>
        </Card>

        {/* Events */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Calendar className="size-4 text-primary-foreground dark:text-primary" />
              Upcoming Economic Events
            </CardTitle>
          </CardHeader>
          <CardContent>
            {events.length > 0 ? (
              <div className="space-y-3">
                {events.map((event, i) => {
                  const daysUntil = Math.ceil(
                    (new Date(event.date).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
                  );
                  return (
                    <div key={i} className="border border-border rounded-2xl p-3 space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Badge className={`rounded-full font-semibold ${
                            event.type === "FOMC" ? "bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-400" :
                            event.type === "NFP" ? "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400" :
                            "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400"
                          }`}>
                            {event.type}
                          </Badge>
                          <span className="text-sm font-semibold">{event.name}</span>
                        </div>
                        <span className="text-xs text-muted-foreground font-medium">
                          {daysUntil <= 0 ? "Today" : daysUntil === 1 ? "Tomorrow" : `${daysUntil}d`}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground font-medium">{event.note}</p>
                      <p className="text-xs text-muted-foreground/60 font-medium">{event.date}</p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8 font-medium">No upcoming events</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
