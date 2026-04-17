"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useBotStore } from "@/store/botStore";
import { showError, showSuccess } from "@/lib/toast";

type WSMessage = {
  channel: string;
  data: unknown;
};

type Callback = (data: unknown) => void;

// ─── Module-level singleton state ────────────────────────────────────────────
// Single WS connection lives for the app lifetime — survives route changes.

let wsInstance: WebSocket | null = null;
let reconnectAttempts = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let wasConnected = false;
let isStarted = false;
let visibilityHandler: (() => void) | null = null;

const subscribers = new Map<string, Set<Callback>>();
const connectionListeners = new Set<(connected: boolean) => void>();

function notifyConnection(connected: boolean) {
  connectionListeners.forEach((cb) => cb(connected));
}

function openSocket() {
  if (
    wsInstance?.readyState === WebSocket.OPEN ||
    wsInstance?.readyState === WebSocket.CONNECTING
  ) {
    return;
  }

  const baseWsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") || "" : "";
  const wsUrl = token ? `${baseWsUrl}?token=${token}` : baseWsUrl;

  try {
    const ws = new WebSocket(wsUrl);
    wsInstance = ws;

    ws.onopen = () => {
      useBotStore.getState().setWsConnected(true);
      useBotStore.getState().setLastSyncAt(new Date().toISOString());
      notifyConnection(true);
      if (wasConnected) {
        showSuccess("Connection restored");
      }
      wasConnected = true;
      reconnectAttempts = 0;
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        useBotStore.getState().setLastSyncAt(new Date().toISOString());
        const channelSubs = subscribers.get(msg.channel);
        if (channelSubs) {
          channelSubs.forEach((cb) => cb(msg.data));
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      useBotStore.getState().setWsConnected(false);
      notifyConnection(false);
      // If stopWebSocket() closed the socket, do not schedule a reconnect —
      // otherwise we get a zombie connection after logout.
      if (!isStarted) return;
      if (wasConnected && reconnectAttempts === 0) {
        showError("Connection lost. Reconnecting...");
      }
      const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000);
      reconnectAttempts++;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(openSocket, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch {
    // connection failed — reconnect timer will retry
  }
}

/**
 * Start the singleton WebSocket. Idempotent. Called once from AppShell
 * after auth. Also re-attempts on tab visibility change.
 */
export function startWebSocket() {
  if (isStarted) {
    // Already started — just ensure socket is open (e.g. after logout/login)
    if (!wsInstance || wsInstance.readyState !== WebSocket.OPEN) {
      reconnectAttempts = 0;
      openSocket();
    }
    return;
  }
  isStarted = true;
  openSocket();

  if (typeof document !== "undefined" && !visibilityHandler) {
    visibilityHandler = () => {
      if (document.visibilityState === "visible") {
        reconnectAttempts = 0;
        if (!wsInstance || wsInstance.readyState !== WebSocket.OPEN) {
          openSocket();
        }
      }
    };
    document.addEventListener("visibilitychange", visibilityHandler);
  }
}

/**
 * Close the singleton. Use on logout only.
 */
export function stopWebSocket() {
  isStarted = false;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (visibilityHandler && typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", visibilityHandler);
    visibilityHandler = null;
  }
  subscribers.clear();
  wasConnected = false;
  reconnectAttempts = 0;
  wsInstance?.close();
  wsInstance = null;
}

type UseWebSocketReturn = {
  isConnected: boolean;
  subscribe: (channel: string, callback: Callback) => void;
  unsubscribe: (channel: string, callback?: Callback) => void;
};

/**
 * Hook that attaches subscribers to the singleton WS. Hook cleanup removes
 * its subscribers but does NOT close the connection — other pages keep it.
 */
export function useWebSocket(): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState<boolean>(
    () => wsInstance?.readyState === WebSocket.OPEN,
  );
  const ownSubsRef = useRef<Map<string, Callback>>(new Map());

  useEffect(() => {
    const listener = (connected: boolean) => setIsConnected(connected);
    connectionListeners.add(listener);

    // Ensure socket is starting (AppShell should already have called this,
    // but harmless to re-invoke)
    startWebSocket();

    const ownSubs = ownSubsRef.current;
    return () => {
      connectionListeners.delete(listener);
      // Remove only this hook instance's callbacks
      ownSubs.forEach((cb, channel) => {
        subscribers.get(channel)?.delete(cb);
      });
      ownSubs.clear();
    };
  }, []);

  const subscribe = useCallback((channel: string, callback: Callback) => {
    // Replace any prior callback from this same hook instance for the channel
    const prior = ownSubsRef.current.get(channel);
    if (prior) subscribers.get(channel)?.delete(prior);
    ownSubsRef.current.set(channel, callback);

    let set = subscribers.get(channel);
    if (!set) {
      set = new Set();
      subscribers.set(channel, set);
    }
    set.add(callback);
  }, []);

  const unsubscribe = useCallback((channel: string, callback?: Callback) => {
    const cb = callback ?? ownSubsRef.current.get(channel);
    if (!cb) return;
    subscribers.get(channel)?.delete(cb);
    if (ownSubsRef.current.get(channel) === cb) {
      ownSubsRef.current.delete(channel);
    }
  }, []);

  return { isConnected, subscribe, unsubscribe };
}
