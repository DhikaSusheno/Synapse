// lib/sseStream.ts
// BUG-38: tiap halaman buka EventSource sendiri ke /stream → 4 koneksi per user.
// Transport tunggal di sini: koneksi dibuat saat subscriber pertama, ditutup saat
// subscriber terakhir hilang, event di-fanout ke semua subscriber.

import type { SSEEvent } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type Handler = (event: SSEEvent) => void;

const handlers = new Set<Handler>();
let es: EventSource | null = null;
let attempt = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

// Exponential backoff 1s, 2s, 4s, 8s, capped 10s (mitigasi BUG-08).
function nextDelay(n: number): number {
  return Math.min(1000 * Math.pow(2, n), 10_000);
}

function connect() {
  if (es || typeof EventSource === "undefined") return;
  es = new EventSource(`${BACKEND_URL}/stream`);
  es.onopen = () => { attempt = 0; };
  es.onmessage = (e) => {
    let parsed: SSEEvent;
    try {
      parsed = JSON.parse(e.data) as SSEEvent;
    } catch {
      return; // event rusak, abaikan
    }
    handlers.forEach((h) => {
      try { h(parsed); } catch { /* subscriber error tidak menumbangkan yang lain */ }
    });
  };
  es.onerror = () => {
    es?.close();
    es = null;
    if (handlers.size === 0) return;
    timer = setTimeout(connect, nextDelay(attempt));
    attempt += 1;
  };
}

function disconnectIfIdle() {
  if (handlers.size > 0) return;
  es?.close();
  es = null;
  if (timer) clearTimeout(timer);
  timer = null;
  attempt = 0;
}

/** Daftar ke /stream. Return fungsi unsubscribe. */
export function subscribeStream(handler: Handler): () => void {
  handlers.add(handler);
  connect();
  return () => {
    handlers.delete(handler);
    disconnectIfIdle();
  };
}

/** Jumlah koneksi /stream yang sedang terbuka — 1 per app, bukan 1 per halaman. */
export function openStreamCount(): number {
  return es ? 1 : 0;
}
