"use client";

// components/TopNavbar.tsx
// Top navigation bar sesuai prototype Synapse
// FE-1 @nabilfauzandafa

import { useBackendStatus, type BackendMode } from "@/hooks/useBackendStatus";

interface Props {
  nodeCount: number;
  edgeCount: number;
  onOpenSettings: () => void;
}

const CONNECTION: Record<BackendMode, { dot: string; title: string; sub: string }> = {
  live:     { dot: "bg-green-400",  title: "Live Connection", sub: "SQLite · FastAPI · SSE" },
  mock:     { dot: "bg-yellow-400", title: "Demo Data",        sub: "Sample operations" },
  checking: { dot: "bg-blue-400",   title: "Checking…",       sub: "Contacting backend" },
  offline:  { dot: "bg-red-400",    title: "Backend Offline",  sub: "Showing last known data" },
};

export default function TopNavbar({ nodeCount, edgeCount, onOpenSettings }: Props) {
  const { mode } = useBackendStatus();
  const conn = CONNECTION[mode];

  return (
    <header className="h-12 shrink-0 flex items-center gap-3 px-4 border-b border-slate-800/60 bg-[#0d1117]">
      {/* Repo info */}
      <div className="flex items-center gap-2 shrink-0">
        <svg aria-hidden="true" className="w-4 h-4 text-slate-400" fill="currentColor" viewBox="0 0 16 16">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
        </svg>
        <span className="text-sm text-slate-300 font-medium">DhikaSusheno/Synapse</span>
        <span className="text-xs px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">public</span>
      </div>

      {/* Branch — label statis. Sebelumnya ada chevron dropdown yang tidak
          terhubung ke endpoint mana pun, jadi hanya affordance yang tidak jalan. */}
      <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800/60 border border-slate-700/60 text-xs text-slate-300 shrink-0">
        <svg aria-hidden="true" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        main
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1 shrink-0" />

      {/* Graph size — kedua prop ini sebelumnya tidak pernah dirender */}
      <div className="flex items-center gap-1.5 text-xs text-slate-400 shrink-0">
        <span className="text-slate-500">graph</span>
        <span className="font-mono text-slate-300">{nodeCount}n</span>
        <span className="text-slate-600">/</span>
        <span className="font-mono text-slate-300">{edgeCount}e</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Agents */}
      <div className="flex items-center gap-2 shrink-0">
        <svg aria-hidden="true" className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2c0 1.313 1.125 2.407 2.618 2.943m0-5.943a3 3 0 013.858-2.982A3 3 0 0111 8.5v1.5m-5.618-3.982A3 3 0 003.858 8.5" />
        </svg>
        <div>
          <div className="text-xs font-medium text-white leading-none">3 Agents</div>
          <div className="text-[10px] text-slate-500 leading-none mt-0.5">
            <span className="text-blue-400">· Guardian</span>
            <span className="text-purple-400"> · Cortex</span>
            <span className="text-slate-400"> · Review</span>
          </div>
        </div>
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1 shrink-0" />

      {/* Live Connection — status asli dari /health, bukan const env */}
      <div className="flex items-center gap-2 shrink-0" role="status">
        <span className={`w-2 h-2 rounded-full shrink-0 ${conn.dot} ${mode === "checking" ? "animate-pulse" : ""}`} />
        <div>
          <div className="text-xs font-medium text-white leading-none">{conn.title}</div>
          <div className="text-[10px] text-slate-500 leading-none mt-0.5">{conn.sub}</div>
        </div>
      </div>

      <div className="w-px h-4 bg-slate-700 mx-1 shrink-0" />

      {/* Settings — sebelumnya <button> tanpa onClick, jadi tidak melakukan apa pun */}
      <button
        onClick={onOpenSettings}
        aria-label="Open settings"
        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors shrink-0"
      >
        <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281zM15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
        </svg>
      </button>
    </header>
  );
}
