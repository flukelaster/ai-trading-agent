"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  headline: string;
  source: string;
  time: string;
  sentimentLabel: string;
  sentimentScore: number;
};

function extractDomain(source: string): string {
  try {
    const url = new URL(source);
    return url.hostname.replace(/^www\./, "");
  } catch {
    return source;
  }
}

function getTimeAgo(isoTime: string): string {
  const ts = isoTime.endsWith("Z") || isoTime.includes("+") ? isoTime : isoTime + "Z";
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

const sentimentConfig = {
  bullish: { icon: TrendingUp, dot: "bg-green-500", text: "text-green-500" },
  bearish: { icon: TrendingDown, dot: "bg-red-500", text: "text-red-500" },
  neutral: { icon: Minus, dot: "bg-zinc-500", text: "text-muted-foreground" },
} as const;

export default function NewsCard({ headline, source, time, sentimentLabel, sentimentScore }: Props) {
  const timeAgo = getTimeAgo(time);
  const config = sentimentConfig[sentimentLabel as keyof typeof sentimentConfig] || sentimentConfig.neutral;
  const Icon = config.icon;

  return (
    <div className="group flex items-center gap-3 py-2.5 border-b border-border/50 last:border-0 transition-colors hover:bg-muted/30 -mx-1 px-1 rounded-md">
      {/* Sentiment indicator dot */}
      <div className="shrink-0 flex flex-col items-center gap-1">
        <div className={cn("size-2 rounded-full", config.dot)} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-[13px] text-foreground leading-snug line-clamp-2">{headline}</p>
        <div className="flex items-center gap-1.5 mt-1">
          <span className="text-[11px] text-muted-foreground/70">{extractDomain(source)}</span>
          <span className="text-[11px] text-muted-foreground/30">·</span>
          <span className="text-[11px] text-muted-foreground/70">{timeAgo}</span>
        </div>
      </div>

      {/* Sentiment score */}
      <div className={cn("shrink-0 flex items-center gap-1 text-xs font-mono tabular-nums", config.text)}>
        <Icon className="size-3 opacity-70" />
        <span>{sentimentScore > 0 ? "+" : ""}{sentimentScore.toFixed(2)}</span>
      </div>
    </div>
  );
}
