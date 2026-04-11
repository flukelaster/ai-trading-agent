"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar, MobileHeader } from "@/components/layout/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import api from "@/lib/api";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === "/login";
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(false);

  useEffect(() => {
    if (isLoginPage) {
      setAuthChecked(true);
      return;
    }

    // Check if auth is enabled and user is authenticated
    api.get("/api/auth/me")
      .then((res) => {
        setAuthEnabled(res.data?.auth_enabled ?? false);
        setAuthChecked(true);
      })
      .catch(() => {
        // 401 = auth enabled but no valid token → redirect to login
        setAuthEnabled(true);
        router.replace("/login");
      });
  }, [isLoginPage, router]);

  if (isLoginPage) {
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
