"use client";

import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex flex-col items-center justify-center py-8 px-4 text-center rounded-xl border border-destructive/20 bg-destructive/5">
          <AlertTriangle className="size-8 text-destructive mb-3" />
          <p className="text-sm font-semibold text-foreground mb-1">
            Something went wrong
          </p>
          <p className="text-xs text-muted-foreground mb-4 max-w-xs">
            {this.state.error?.message || "An unexpected error occurred"}
          </p>
          <Button variant="outline" size="sm" onClick={this.handleReset}>
            <RotateCcw className="size-3.5" />
            Try Again
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
