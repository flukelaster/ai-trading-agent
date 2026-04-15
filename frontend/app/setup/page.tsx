"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { startRegistration } from "@simplewebauthn/browser";
import api from "@/lib/api";
import { showSuccess, showError } from "@/lib/toast";

export default function SetupPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("Admin");
  const [deviceName, setDeviceName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [step, setStep] = useState<"form" | "registering">("form");

  useEffect(() => {
    api.get("/api/auth/setup-status")
      .then((res) => {
        if (res.data.is_setup_complete) {
          router.replace("/login");
        } else {
          setChecking(false);
        }
      })
      .catch(() => setChecking(false));
  }, [router]);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    setStep("registering");

    try {
      // 1. Get registration options from backend
      const optionsRes = await api.post("/api/auth/register/options", {
        display_name: displayName,
      });
      const options = JSON.parse(optionsRes.data.options);
      const ownerId = optionsRes.data.owner_id;

      // 2. Create credential via browser WebAuthn API
      const credential = await startRegistration({ optionsJSON: options });

      // 3. Verify with backend
      await api.post("/api/auth/register/verify", {
        owner_id: ownerId,
        credential,
        device_name: deviceName || navigator.userAgent.split("(")[0].trim(),
      });

      // Success — redirect to login
      showSuccess("Passkey registered successfully!");
      router.push("/login");
    } catch (err: unknown) {
      setStep("form");
      showError("Registration failed");
      if (err && typeof err === "object" && "name" in err) {
        const webauthnErr = err as { name: string; message?: string };
        if (webauthnErr.name === "NotAllowedError") {
          setError("Passkey registration was cancelled or timed out.");
        } else if (webauthnErr.name === "InvalidStateError") {
          setError("This device is already registered.");
        } else {
          setError(webauthnErr.message || "Registration failed");
        }
      } else if (err && typeof err === "object" && "response" in err) {
        const response = (err as { response: { data?: { detail?: string } } }).response;
        setError(response?.data?.detail || "Registration failed");
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
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8">
        <div className="text-center">
          <h1 className="text-2xl font-bold">AI Trading Agent</h1>
          <p className="text-sm text-muted-foreground mt-1">Initial Setup</p>
        </div>

        <div className="rounded-md bg-blue-500/10 p-3 text-sm text-blue-400">
          Register a passkey to secure your dashboard. You can use fingerprint, Face ID, or a security key.
        </div>

        {step === "registering" && (
          <div className="text-center py-4">
            <div className="animate-pulse text-lg mb-2">Waiting for passkey...</div>
            <p className="text-sm text-muted-foreground">
              Follow the prompt from your browser or device.
            </p>
          </div>
        )}

        {step === "form" && (
          <form onSubmit={handleRegister} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <div>
              <label htmlFor="displayName" className="block text-sm font-medium mb-1">
                Display Name
              </label>
              <input
                id="displayName"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                required
              />
            </div>

            <div>
              <label htmlFor="deviceName" className="block text-sm font-medium mb-1">
                Device Name <span className="text-muted-foreground">(optional)</span>
              </label>
              <input
                id="deviceName"
                type="text"
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                placeholder="e.g. MacBook Pro, iPhone 15"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {loading ? "Registering..." : "Register Passkey"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
