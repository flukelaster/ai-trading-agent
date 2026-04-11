"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { startAuthentication, browserSupportsWebAuthn } from "@simplewebauthn/browser";
import api from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    setSupported(browserSupportsWebAuthn());

    api.get("/api/auth/setup-status")
      .then((res) => {
        if (!res.data.is_setup_complete) {
          router.replace("/setup");
          return;
        }
        // Check if already authenticated
        return api.get("/api/auth/me").then((meRes) => {
          if (meRes.data.authenticated) {
            router.replace("/dashboard");
          } else {
            setChecking(false);
          }
        });
      })
      .catch(() => setChecking(false));
  }, [router]);

  const handleLogin = async () => {
    setError("");
    setLoading(true);

    try {
      // 1. Get login options
      const optionsRes = await api.post("/api/auth/login/options");
      const options = JSON.parse(optionsRes.data.options);

      // 2. Authenticate via browser WebAuthn API
      const credential = await startAuthentication({ optionsJSON: options });

      // 3. Verify with backend (sets httpOnly cookie)
      await api.post("/api/auth/login/verify", { credential });

      // Success — redirect to dashboard
      router.push("/dashboard");
    } catch (err: unknown) {
      if (err && typeof err === "object" && "name" in err) {
        const webauthnErr = err as { name: string; message?: string };
        if (webauthnErr.name === "NotAllowedError") {
          setError("Authentication was cancelled or timed out.");
        } else {
          setError(webauthnErr.message || "Authentication failed");
        }
      } else if (err && typeof err === "object" && "response" in err) {
        const response = (err as { response: { data?: { detail?: string } } }).response;
        setError(response?.data?.detail || "Authentication failed");
      } else {
        setError("Connection error");
      }
    } finally {
      setLoading(false);
    }
  };

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground">Checking authentication...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Gold Trading Bot</h1>
          <p className="text-sm text-muted-foreground mt-1">Sign in to your dashboard</p>
        </div>

        {error && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {!supported ? (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            Your browser does not support passkeys. Please use a modern browser (Chrome, Firefox, Safari, or Edge).
          </div>
        ) : (
          <button
            type="button"
            onClick={handleLogin}
            disabled={loading}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Authenticating..." : "Sign in with Passkey"}
          </button>
        )}
      </div>
    </div>
  );
}
