"use client";

import { type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  icon?: LucideIcon;
  iconNode?: ReactNode;
  label: string;
  value: string | number;
  subtitle?: string;
  trend?: { direction: "up" | "down" | "flat"; label: string };
  variant?: "default" | "success" | "danger" | "warning" | "gold";
  className?: string;
}

const variantStyles = {
  default: "text-foreground",
  success: "text-success dark:text-green-400",
  danger: "text-destructive",
  warning: "text-amber-600 dark:text-amber-400",
  gold: "text-primary-foreground dark:text-primary",
};

const iconVariantStyles = {
  default: "bg-muted text-muted-foreground",
  success: "bg-success/10 text-success dark:bg-green-400/10 dark:text-green-400",
  danger: "bg-destructive/10 text-destructive",
  warning: "bg-amber-100 text-amber-600 dark:bg-amber-400/10 dark:text-amber-400",
  gold: "bg-primary/10 text-primary-foreground dark:text-primary",
};

export function StatCard({
  icon: Icon,
  iconNode,
  label,
  value,
  subtitle,
  trend,
  variant = "default",
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border p-4 sm:p-5 ring-border transition-all duration-150 hover:-translate-y-0.5",
        "bg-card",
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div
          className={cn(
            "size-7 sm:size-9 rounded-xl flex items-center justify-center",
            iconVariantStyles[variant]
          )}
        >
          {iconNode ? iconNode : Icon ? <Icon className="size-3.5 sm:size-4" /> : null}
        </div>
        {trend && (
          <span
            className={cn(
              "text-xs font-semibold px-1.5 sm:px-2 py-0.5 rounded-full",
              trend.direction === "up" && "bg-success/10 text-success dark:bg-green-400/10 dark:text-green-400",
              trend.direction === "down" && "bg-destructive/10 text-destructive",
              trend.direction === "flat" && "bg-muted text-muted-foreground"
            )}
          >
            {trend.direction === "up" && "+"}
            {trend.label}
          </span>
        )}
      </div>
      <div className="mt-2 sm:mt-3">
        <p className="text-xs text-muted-foreground font-medium">{label}</p>
        <p
          className={cn(
            "mt-0.5 sm:mt-1 text-base sm:text-xl font-bold font-mono tracking-tight truncate",
            variantStyles[variant]
          )}
        >
          {value}
        </p>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground font-medium truncate">{subtitle}</p>
        )}
      </div>
    </div>
  );
}
