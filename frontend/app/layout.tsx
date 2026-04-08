import type { Metadata } from "next";
import { Noto_Sans, Noto_Sans_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar, MobileHeader } from "@/components/layout/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

const notoSans = Noto_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const notoSansMono = Noto_Sans_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Gold Trading Bot",
  description: "XAUUSD Auto-Trading Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${notoSans.variable} ${notoSansMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col lg:flex-row bg-background text-foreground">
        <TooltipProvider>
          <MobileHeader />
          <Sidebar />
          <main className="flex-1 overflow-auto">
            <div className="max-w-[1400px] mx-auto">{children}</div>
          </main>
        </TooltipProvider>
      </body>
    </html>
  );
}
