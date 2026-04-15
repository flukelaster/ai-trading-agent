"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  LayoutDashboard,
  BarChart3,
  History,
  Brain,
  Activity,
  Cpu,
  Globe,
  Shield,
  Settings2,
  Plug,
  Bell,
  Settings,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandItem {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
  group: string;
}

const navItems: CommandItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, group: "Navigation" },
  { label: "Backtest", href: "/backtest", icon: BarChart3, group: "Navigation" },
  { label: "History", href: "/history", icon: History, group: "Navigation" },
  { label: "AI Insights", href: "/insights", icon: Brain, group: "Navigation" },
  { label: "AI Activity", href: "/activity", icon: Activity, group: "Navigation" },
  { label: "ML Model", href: "/ml", icon: Cpu, group: "Navigation" },
  { label: "Macro Data", href: "/macro", icon: Globe, group: "Navigation" },
  { label: "Quant", href: "/quant", icon: Shield, group: "Navigation" },
  { label: "Agent Prompts", href: "/agent-prompts", icon: Settings2, group: "System" },
  { label: "Integration", href: "/integration", icon: Plug, group: "System" },
  { label: "Notifications", href: "/notifications", icon: Bell, group: "System" },
  { label: "Settings", href: "/settings", icon: Settings, group: "System" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setOpen((prev) => !prev);
    }
  }, []);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const handleSelect = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/20 backdrop-blur-xs animate-in fade-in-0 duration-100"
        onClick={() => setOpen(false)}
      />

      {/* Command dialog */}
      <div className="absolute left-1/2 top-[20%] -translate-x-1/2 w-full max-w-lg animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-150">
        <Command
          className={cn(
            "rounded-xl border border-border bg-card shadow-2xl overflow-hidden",
            "dark:shadow-[0_25px_50px_-12px_rgba(0,0,0,0.5)]"
          )}
          loop
        >
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="size-4 text-muted-foreground shrink-0" />
            <Command.Input
              placeholder="Search pages..."
              className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              autoFocus
            />
            <kbd className="hidden sm:inline-flex h-5 items-center gap-0.5 rounded border border-border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
              ESC
            </kbd>
          </div>

          <Command.List className="max-h-72 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>

            {["Navigation", "System"].map((group) => (
              <Command.Group
                key={group}
                heading={group}
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-muted-foreground/60"
              >
                {navItems
                  .filter((item) => item.group === group)
                  .map((item) => {
                    const Icon = item.icon;
                    return (
                      <Command.Item
                        key={item.href}
                        value={item.label}
                        onSelect={() => handleSelect(item.href)}
                        className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm cursor-pointer text-muted-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground transition-colors"
                      >
                        <Icon className="size-4" />
                        <span>{item.label}</span>
                      </Command.Item>
                    );
                  })}
              </Command.Group>
            ))}
          </Command.List>

          <div className="border-t border-border px-3 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span>Navigate</span>
              <kbd className="inline-flex h-4 items-center rounded border border-border bg-muted px-1 text-[10px]">
                ↑↓
              </kbd>
              <span>Select</span>
              <kbd className="inline-flex h-4 items-center rounded border border-border bg-muted px-1 text-[10px]">
                ↵
              </kbd>
            </div>
          </div>
        </Command>
      </div>
    </div>
  );
}
