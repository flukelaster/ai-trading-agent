"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar, MobileHeader } from "@/components/layout/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import api from "@/lib/api";

const AUTH_BYPASS_PAGES = ["/login", "/setup"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isAuthPage = AUTH_BYPASS_PAGES.includes(pathname);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    if (isAuthPage) {
      setAuthChecked(true);
      return;
    }

    // Check auth status via cookie-based session
    api.get("/api/auth/me")
      .then((res) => {
        if (res.data?.setup_required) {
          router.replace("/setup");
        } else {
          setAuthChecked(true);
        }
      })
      .catch((err: unknown) => {
        const status = (err && typeof err === "object" && "response" in err)
          ? (err as { response?: { status?: number } }).response?.status
          : undefined;
        if (status === 401) {
          router.replace("/login");
        } else {
          // Server error or network issue — allow access (auth might not be set up)
          setAuthChecked(true);
        }
      });
  }, [isAuthPage, router]);

  if (isAuthPage) {
    return <>{children}</>;
  }

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground text-sm">Loading...</p>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col lg:flex-row min-h-full">
        <MobileHeader />
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <div className="max-w-[1600px] mx-auto animate-fade-in">{children}</div>
        </main>
      </div>
    </TooltipProvider>
  );
}
