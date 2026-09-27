"use client";
// components/shared/BackendStatusBanner.tsx
// Banner visual yang mencolok untuk menunjukkan status backend (live/mock/offline)
// Mencegah kebingungan "kenapa fitur ga jalan?" saat mode MOCK.

import { useBackendStatus, BackendStatus } from "@/hooks/useBackendStatus";

const ICONS = {
  live: "●",
  mock: "▲",
  checking: "◌",
  offline: "✕",
};

const COLORS = {
  live: "bg-green-500/20 text-green-400 border-green-500/30",
  mock: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  checking: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  offline: "bg-red-500/20 text-red-400 border-red-500/30",
};

const LABELS = {
  live: "LIVE DATA",
  mock: "DEMO DATA",
  checking: "CHECKING",
  offline: "OFFLINE",
};

const MESSAGES = {
  live: "Connected to backend — real data active",
  mock: "Sample operations, not real runs — start the backend and set NEXT_PUBLIC_USE_LIVE_SSE=true for live data",
  checking: "Checking backend availability…",
  offline: "Backend unreachable — check NEXT_PUBLIC_BACKEND_URL",
};

export default function BackendStatusBanner() {
  const status = useBackendStatus();

  // Don't show banner if live (user already sees real data)
  if (status.mode === "live") return null;

  return (
    <div
      className={`shrink-0 px-4 py-2.5 ${COLORS[status.mode]} border-b border-solid`}
      role="status"
      aria-live="polite"
    >
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            aria-hidden="true"
            className={`text-sm leading-none shrink-0 ${
              status.mode === "checking" ? "animate-pulse" : ""
            }`}
          >
            {ICONS[status.mode]}
          </span>
          <span className="text-xs font-semibold uppercase tracking-wide shrink-0">
            {LABELS[status.mode]}
          </span>
          <span className="text-xs text-slate-300/80 truncate">{MESSAGES[status.mode]}</span>
        </div>
        {(status.mode === "mock" || status.mode === "offline") && (
          <button
            onClick={() => window.location.reload()}
            className="text-xs px-3 py-1.5 bg-slate-900/50 border border-slate-700/50 rounded-lg hover:bg-slate-800/50 transition-colors whitespace-nowrap shrink-0"
          >
            {status.mode === "mock" ? "Reload after fixing .env.local" : "Retry"}
          </button>
        )}
      </div>
    </div>
  );
}