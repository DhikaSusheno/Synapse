"use client";
// components/shared/BackendStatusBanner.tsx
// Banner visual yang mencolok untuk menunjukkan status backend (live/mock/offline)
// Mencegah kebingungan "kenapa fitur ga jalan?" saat mode MOCK.

import { useBackendStatus, BackendStatus } from "@/hooks/useBackendStatus";

const ICONS = {
  live: "&#9679;",
  mock: "&#9888;",
  checking: "&#8987;",
  offline: "&#10060;",
};

const COLORS = {
  live: "bg-green-500/20 text-green-400 border-green-500/30",
  mock: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  checking: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  offline: "bg-red-500/20 text-red-400 border-red-500/30",
};

const LABELS = {
  live: "LIVE",
  mock: "MOCK MODE",
  checking: "CHECKING...",
  offline: "OFFLINE",
};

const MESSAGES = {
  live: "Connected to backend — real data active",
  mock: "Running in MOCK mode — set NEXT_PUBLIC_USE_LIVE_SSE=true to enable live backend",
  checking: "Checking backend availability...",
  offline: "Backend unreachable — check if backend is running on NEXT_PUBLIC_BACKEND_URL",
};

export default function BackendStatusBanner() {
  const status = useBackendStatus();

  // Don't show banner if live (user already sees real data)
  if (status.mode === "live") return null;

  return (
    <div
      className={`fixed top-0 left-0 right-0 z-50 px-4 py-2.5 ${COLORS[status.mode]} border-b border-solid`}
      role="status"
      aria-live="polite"
    >
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span
            className={`w-5 h-5 rounded-full flex items-center justify-center text-xs ${
              status.mode === "checking" ? "animate-pulse" : ""
            }`}
            dangerouslySetInnerHTML={{ __html: ICONS[status.mode] }}
          />
          <span className="text-xs font-semibold uppercase tracking-wide">
            {LABELS[status.mode]}
          </span>
          <span className="text-xs text-slate-300/80">{MESSAGES[status.mode]}</span>
        </div>
        {status.mode === "mock" && (
          <button
            onClick={() => window.location.reload()}
            className="text-xs px-3 py-1.5 bg-slate-900/50 border border-slate-700/50 rounded-lg hover:bg-slate-800/50 transition-colors whitespace-nowrap"
          >
            Reload after fixing .env.local
          </button>
        )}
        {status.mode === "offline" && (
          <button
            onClick={() => window.location.reload()}
            className="text-xs px-3 py-1.5 bg-slate-900/50 border border-slate-700/50 rounded-lg hover:bg-slate-800/50 transition-colors whitespace-nowrap"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}