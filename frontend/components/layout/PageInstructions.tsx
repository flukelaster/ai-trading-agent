"use client";

import { useState, useEffect } from "react";
import { Info, ChevronDown, ChevronUp } from "lucide-react";

interface PageInstructionsProps {
  pageId: string;
  items: string[];
}

export function PageInstructions({ pageId, items }: PageInstructionsProps) {
  const storageKey = `help-dismissed-${pageId}`;
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem(storageKey);
    if (saved === "true") setCollapsed(true);
  }, [storageKey]);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem(storageKey, String(next));
  };

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={toggle}
        className="flex items-center gap-1.5 text-[11px] text-blue-400/70 hover:text-blue-400 transition-colors"
      >
        <Info className="size-3" />
        <span>Show help</span>
      </button>
    );
  }

  return (
    <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <Info className="size-3.5 text-blue-400 mt-0.5 shrink-0" />
          <ul className="space-y-1 text-xs text-blue-200/80">
            {items.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </div>
        <button
          type="button"
          onClick={toggle}
          className="text-blue-400/50 hover:text-blue-400 transition-colors shrink-0"
        >
          <ChevronUp className="size-4" />
        </button>
      </div>
    </div>
  );
}
