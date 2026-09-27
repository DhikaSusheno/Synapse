"use client";
// hooks/useBackendStatus.ts
// Deteksi ketersediaan backend di runtime dan sediakan status live/mock
// untuk menghindari kebingungan "kenapa fitur ga jalan?" saat pertama kali jalan.

import { useEffect, useState, useCallback } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

export type BackendMode = "live" | "mock" | "checking" | "offline";

export interface BackendStatus {
  mode: BackendMode;
  isLive: boolean;
  error?: string;
}

export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>({
    mode: USE_LIVE ? "checking" : "mock",
    isLive: false,
  });

  const checkBackend = useCallback(async () => {
    if (!USE_LIVE) {
      setStatus({ mode: "mock", isLive: false });
      return;
    }
    setStatus((prev) => ({ ...prev, mode: "checking" }));
    try {
      const res = await fetch(`${BACKEND_URL}/health`, {
        method: "GET",
        cache: "no-store",
        signal: AbortSignal.timeout(3000),
      });
      if (res.ok) {
        setStatus({ mode: "live", isLive: true });
      } else {
        setStatus({
          mode: "offline",
          isLive: false,
          error: `Backend responded ${res.status}`,
        });
      }
    } catch (e) {
      setStatus({
        mode: "offline",
        isLive: false,
        error: e instanceof Error ? e.message : "Unknown error",
      });
    }
  }, []);

  useEffect(() => {
    checkBackend();
    // Re-check every 30s to catch backend coming online
    const interval = setInterval(checkBackend, 30_000);
    return () => clearInterval(interval);
  }, [checkBackend]);

  return status;
}