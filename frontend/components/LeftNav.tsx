"use client";

// components/LeftNav.tsx
// Sidebar navigasi kiri sesuai prototype Synapse
// FE-1 @nabilfauzandafa

import Link from "next/link";
import { useBackendStatus, type BackendMode } from "@/hooks/useBackendStatus";

export type NavPage = "overview" | "code-graph" | "guardian" | "cortex" | "agents" | "approvals" | "operations" | "security" | "settings";

interface Props {
  activePage: NavPage;
  onNavigate: (page: NavPage) => void;
  pendingApprovals?: number;
}

// Ikon garis 24x24 (stroke, currentColor) — satu gaya, satu ukuran.
// Sebelumnya: entitas HTML + emoji 🛡 (warna ikut platform, tidak cocok dengan garis).
const NAV_ITEMS: { id: NavPage; label: string; d: string }[] = [
  { id: "overview",   label: "Overview",   d: "M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" },
  { id: "code-graph", label: "Code Graph", d: "M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" },
  { id: "guardian",   label: "Guardian",   d: "M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" },
  { id: "cortex",     label: "Cortex",     d: "M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z" },
  { id: "agents",     label: "Agents",     d: "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" },
  { id: "approvals",  label: "Approvals",  d: "M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { id: "operations", label: "Operations", d: "M3 12h4.5l2.25-6 3.75 12 2.25-6H21" },
  { id: "security",   label: "Security",   d: "M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z" },
  { id: "settings",   label: "Settings",   d: "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281zM15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" },
];

function NavIcon({ d }: { d: string }) {
  return (
    <svg aria-hidden="true" className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d={d} />
    </svg>
  );
}

// Logo: glyph sinaps (1 nukleus + 4 dendrit) warna aksen tunggal.
// Sebelumnya gradien biru→ungu + huruf "S" — generic AI-slop, tidak nyambung
// dengan sisa UI yang monochrome.
function LogoMark() {
  return (
    <svg aria-hidden="true" className="w-full h-full" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth={1.6} strokeLinecap="round">
      <path d="M12 12L6 6.5M12 12l6-5.5M12 12l-5.5 6M12 12l5.5 6" opacity={0.55} />
      <circle cx="12" cy="12" r="3.1" fill="#3b82f6" stroke="none" />
      <circle cx="6" cy="6.5" r="1.9" />
      <circle cx="18" cy="6.5" r="1.9" />
      <circle cx="6.5" cy="18" r="1.9" />
      <circle cx="17.5" cy="18" r="1.9" />
    </svg>
  );
}

const FOOTER_STATUS: Record<BackendMode, { dot: string; text: string }> = {
  live:     { dot: "bg-green-400",  text: "text-green-400" },
  mock:     { dot: "bg-yellow-400", text: "text-yellow-400" },
  checking: { dot: "bg-blue-400",   text: "text-blue-400" },
  offline:  { dot: "bg-red-400",    text: "text-red-400" },
};
const FOOTER_LABEL: Record<BackendMode, string> = {
  live: "Backend connected",
  mock: "Demo data",
  checking: "Checking backend…",
  offline: "Backend offline",
};

export default function LeftNav({ activePage, onNavigate, pendingApprovals = 0 }: Props) {
  const { mode } = useBackendStatus();
  const footer = FOOTER_STATUS[mode];

  return (
    <nav aria-label="Primary" className="w-52 shrink-0 flex flex-col bg-[#0d1117] border-r border-slate-800/60 overflow-hidden">
      {/* Logo — Link ke /landing. Sebelumnya div biasa, tidak bisa diklik. */}
      <div className="px-4 py-4 border-b border-slate-800/60 shrink-0">
        <Link href="/landing" className="flex items-center gap-2.5 rounded-lg group" aria-label="Synapse — about and demo guide">
          <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 group-hover:border-blue-400/60 transition-colors">
            <LogoMark />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-bold text-white tracking-tight">SYNAPSE</div>
            <div className="text-[10px] text-slate-500 leading-tight truncate">Understanding Layer for AI Agents</div>
          </div>
        </Link>
      </div>

      {/* Nav items */}
      <div className="flex-1 py-2 space-y-0.5 px-2 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const isActive = activePage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              aria-current={isActive ? "page" : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                isActive
                  ? "bg-blue-600/20 text-blue-400 font-medium"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              <NavIcon d={item.d} />
              <span className="flex-1">{item.label}</span>
              {item.id === "approvals" && pendingApprovals > 0 && (
                <span className="text-xs bg-blue-600 text-white rounded-full w-5 h-5 flex items-center justify-center font-bold shrink-0">
                  {pendingApprovals}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer — status asli dari /health, bukan hardcoded "System Healthy" */}
      <div className="px-4 py-3 border-t border-slate-800/60 space-y-1 shrink-0">
        <div className="text-xs text-slate-500 font-mono">v0.1.0</div>
        <div className="flex items-center gap-1.5" role="status">
          <span className={`w-1.5 h-1.5 rounded-full inline-block shrink-0 ${footer.dot} ${mode === "checking" ? "animate-pulse" : ""}`} />
          <span className={`text-xs truncate ${footer.text}`}>{FOOTER_LABEL[mode]}</span>
        </div>
      </div>
    </nav>
  );
}
