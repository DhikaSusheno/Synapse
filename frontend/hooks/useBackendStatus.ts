"use client";
// hooks/useBackendStatus.ts
// Deteksi ketersediaan backend di runtime dan sediakan status live/mock
// untuk menghindari kebingungan "kenapa fitur ga jalan?" saat pertama kali jalan.
//
// SATU poller, BANYAK subscriber. Dulu banner dan TopNavbar masing-masing poll
// /health sehingga bisa tampil bersamaan "Live Connection" (hijau) dan
// "OFFLINE" (merah). Sekarang keduanya baca state yang sama dari modul ini.

import { useEffect, useState } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

export type BackendMode = "live" | "mock" | "checking" | "offline";

export interface BackendStatus {
  mode: BackendMode;
  isLive: boolean;
  error?: string;
}

const listeners = new Set<(s: BackendStatus) => void>();
let current: BackendStatus = { mode: USE_LIVE ? "checking" : "mock", isLive: false };
let poller: ReturnType<typeof setInterval> | null = null;

function emit() {
  // ponytail: forEach, bukan for..of — tsconfig target-nya di bawah ES2015 dan
  // iterasi Set butuh downlevelIteration.
  listeners.forEach((l) => l(current));
}

async function checkBackend() {
  if (!USE_LIVE) {
    current = { mode: "mock", isLive: false };
    emit();
    return;
  }
  current = { ...current, mode: "checking" };
  emit();
  try {
    const res = await fetch(`${BACKEND_URL}/health`, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      current = { mode: "live", isLive: true };
    } else {
      current = {
        mode: "offline",
        isLive: false,
        error: `Backend responded ${res.status}`,
      };
    }
  } catch (e) {
    current = {
      mode: "offline",
      isLive: false,
      error: e instanceof Error ? e.message : "Unknown error",
    };
  }
  emit();
}

export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>(current);

  useEffect(() => {
    listeners.add(setStatus);
    setStatus(current);
    if (poller === null) {
      checkBackend();
      poller = setInterval(checkBackend, 30_000);
    }
    return () => {
      listeners.delete(setStatus);
      // ponytail: satu timer modul untuk semua consumer. Kalau consumer terakhir
      // hilang, timer ikut mati; poll berikutnya terjadi saat mount lagi.
      if (listeners.size === 0 && poller !== null) {
        clearInterval(poller);
        poller = null;
      }
    };
  }, []);

  return status;
}
