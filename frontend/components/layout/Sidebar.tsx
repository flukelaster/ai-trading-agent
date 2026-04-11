"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  Settings2,
  BarChart3,
  History,
  Brain,
  Cpu,
  Globe,
  Menu,
  X,
  Sun,
  Moon,
  TrendingUp,
  Bell,
  KeyRound,
  LogOut,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/strategy", label: "Strategy", icon: Settings2 },
  { href: "/backtest", label: "Backtest", icon: BarChart3 },
  { href: "/history", label: "History", icon: History },
  { href: "/insights", label: "AI Insights", icon: Brain },
  { href: "/ml", label: "ML Model", icon: Cpu },
  { href: "/macro", label: "Macro Data", icon: Globe },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/secrets", label: "Secrets", icon: KeyRound },
];

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <button
      type="button"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-sidebar-accent transition-colors"
      aria-label="Toggle theme"
    >
      <Sun className="size-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute size-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
      <span className="text-xs">Theme</span>
    </button>
  );
}

function LogoutButton() {
  const router = useRouter();
  const handleLogout = async () => {
    try {
      const { default: api } = await import("@/lib/api");
      await api.post("/api/auth/logout");
    } catch {
      // ignore logout errors
    }
    router.push("/login");
  };
  return (
    <button
      type="button"
      onClick={handleLogout}
      className="flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium text-muted-foreground hover:text-red-500 hover:bg-sidebar-accent transition-colors w-full"
    >
      <LogOut className="size-4" />
      <span className="text-xs">Logout</span>
    </button>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {/* Header */}
      <div className="p-5">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-full bg-primary flex items-center justify-center">
            <TrendingUp className="size-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-base font-black tracking-tight text-foreground">
              TRADE BOT
            </h1>
            <p className="text-xs text-muted-foreground font-medium">
              Multi-Symbol Trading
            </p>
          </div>
        </div>
      </div>

      <div className="mx-4 h-px bg-sidebar-border" />

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-0.5">
        <p className="px-3 py-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
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
                "flex items-center gap-3 px-3 py-2.5 rounded-2xl text-sm font-semibold transition-all duration-150",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-sidebar-accent"
              )}
            >
              <Icon className="size-4" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mx-4 h-px bg-sidebar-border" />

      {/* Footer */}
      <div className="p-4 space-y-1">
        <ThemeToggle />
        <LogoutButton />
        <p className="px-3 pt-1 text-xs text-muted-foreground/50 font-medium">v2.0.0</p>
      </div>
    </>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden lg:flex w-60 flex-col bg-sidebar border-r border-sidebar-border h-screen sticky top-0">
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
          <div className="size-7 rounded-full bg-primary flex items-center justify-center">
            <TrendingUp className="size-3.5 text-primary-foreground" />
          </div>
          <span className="text-sm font-black text-foreground">TRADE BOT</span>
        </div>
        <button type="button" aria-label="Open menu" onClick={() => setOpen(true)} className="p-1.5 text-muted-foreground hover:text-foreground">
          <Menu className="size-5" />
        </button>
      </header>

      {open && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
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
