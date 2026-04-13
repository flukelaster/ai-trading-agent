"use client";

import { Newspaper } from "lucide-react";
import SentimentBadge from "./SentimentBadge";
import { cn } from "@/lib/utils";

type Props = {
  headline: string;
  source: string;
  time: string;
  sentimentLabel: string;
  sentimentScore: number;
};

const borderColorMap: Record<string, string> = {
  bullish: "border-l-success/50 dark:border-l-green-500/50",
  bearish: "border-l-destructive/50",
  neutral: "border-l-muted-foreground/30",
};

function extractDomain(source: string): string {
  try {
    const url = new URL(source);
    return url.hostname.replace(/^www\./, "");
  } catch {
    return source;
  }
}

export default function NewsCard({ headline, source, time, sentimentLabel, sentimentScore }: Props) {
  const timeAgo = getTimeAgo(time);

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border border-border border-l-2 p-3 transition-colors hover:bg-muted/50",
        borderColorMap[sentimentLabel] || borderColorMap.neutral
      )}
    >
      <Newspaper className="size-4 mt-0.5 text-muted-foreground shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-foreground leading-snug">{headline}</p>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-[11px] text-muted-foreground font-medium">{extractDomain(source)}</span>
          <span className="text-[11px] text-muted-foreground/40">·</span>
          <span className="text-[11px] text-muted-foreground font-medium">{timeAgo}</span>
        </div>
      </div>
      <SentimentBadge label={sentimentLabel} score={sentimentScore} size="sm" />
    </div>
  );
}

function getTimeAgo(isoTime: string): string {
  // Backend sends UTC without 'Z' suffix — ensure parsed as UTC
  const ts = isoTime.endsWith("Z") || isoTime.includes("+") ? isoTime : isoTime + "Z";
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
