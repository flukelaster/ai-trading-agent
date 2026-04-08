"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Settings2,
  BarChart3,
  History,
  Brain,
  CircleDot,
  Menu,
  X,
} from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/strategy", label: "Strategy", icon: Settings2 },
  { href: "/backtest", label: "Backtest", icon: BarChart3 },
  { href: "/history", label: "History", icon: History },
  { href: "/insights", label: "AI Insights", icon: Brain },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {/* Header */}
      <div className="p-5">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-lg gold-gradient flex items-center justify-center">
            <span className="text-sm font-bold text-gold-foreground">Au</span>
          </div>
          <div>
            <h1 className="text-base font-bold tracking-wide gold-gradient-text">
              GOLD BOT
            </h1>
            <p className="text-[11px] text-muted-foreground">
              XAUUSD Auto-Trading
            </p>
          </div>
        </div>
      </div>

      <Separator className="bg-sidebar-border" />

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        <p className="px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Navigation
        </p>
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-primary/10 text-primary border-l-2 border-primary glow-gold"
                  : "text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent"
              )}
            >
              <Icon className={cn("size-4", isActive && "text-primary")} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <Separator className="bg-sidebar-border" />

      {/* Footer */}
      <div className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <CircleDot className="size-3 text-success animate-pulse" />
          <span>System Online</span>
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground/50">v1.0.0</p>
      </div>
    </>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden lg:flex w-60 flex-col bg-sidebar border-r border-sidebar-border">
      <SidebarContent />
    </aside>
  );
}

export function MobileHeader() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <header className="lg:hidden flex items-center justify-between p-3 border-b border-sidebar-border bg-sidebar">
        <div className="flex items-center gap-2">
          <div className="size-7 rounded-md gold-gradient flex items-center justify-center">
            <span className="text-xs font-bold text-gold-foreground">Au</span>
          </div>
          <span className="text-sm font-bold gold-gradient-text">GOLD BOT</span>
        </div>
        <button type="button" aria-label="Open menu" onClick={() => setOpen(true)} className="p-1.5 text-muted-foreground hover:text-foreground">
          <Menu className="size-5" />
        </button>
      </header>

      {/* Mobile drawer overlay */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 bottom-0 w-60 bg-sidebar border-r border-sidebar-border flex flex-col animate-in slide-in-from-left duration-200">
            <div className="flex justify-end p-2">
              <button type="button" aria-label="Close menu" onClick={() => setOpen(false)} className="p-1.5 text-muted-foreground hover:text-foreground">
                <X className="size-5" />
              </button>
            </div>
            <SidebarContent onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}
