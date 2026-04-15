"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

export function Toaster() {
  const { theme = "light" } = useTheme();

  return (
    <Sonner
      theme={theme as "light" | "dark"}
      position="bottom-right"
      toastOptions={{
        duration: 3500,
        classNames: {
          toast:
            "group rounded-xl border border-border bg-card text-card-foreground shadow-lg !px-4 !py-3",
          title: "text-sm font-semibold",
          description: "text-xs text-muted-foreground",
          success:
            "!border-success/20 !bg-success/5 [&>[data-icon]]:!text-success",
          error:
            "!border-destructive/20 !bg-destructive/5 [&>[data-icon]]:!text-destructive",
          info: "!border-primary/20 !bg-primary/5 [&>[data-icon]]:!text-primary",
          actionButton:
            "!bg-primary !text-primary-foreground !rounded-lg !text-xs !font-semibold",
          cancelButton:
            "!bg-muted !text-muted-foreground !rounded-lg !text-xs !font-semibold",
        },
      }}
    />
  );
}
