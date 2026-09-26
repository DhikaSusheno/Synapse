"use client";

// components/LeftNav.tsx
// Sidebar navigasi kiri sesuai prototype Synapse
// FE-1 @nabilfauzandafa

import { useState } from "react";

export type NavPage = "overview" | "code-graph" | "guardian" | "cortex" | "approvals" | "operations" | "security" | "settings";

interface Props {
  activePage: NavPage;
  onNavigate: (page: NavPage) => void;
  pendingApprovals?: number;
}

const NAV_ITEMS: { id: NavPage; icon: string; label: string }[] = [
  { id: "overview",    icon: "&#9632;",  label: "Overview" },
  { id: "code-graph",  icon: "&#9903;",  label: "Code Graph" },
  { id: "guardian",    icon: "&#9shieldtext;", label: "Guardian" },
  { id: "cortex",      icon: "&#9736;",  label: "Cortex" },
  { id: "approvals",   icon: "&#9745;",  label: "Approvals" },
  { id: "operations",  icon: "&#9881;",  label: "Operations" },
  { id: "security",    icon: "&#128737;", label: "Security" },
  { id: "settings",    icon: "&#9881;",  label: "Settings" },
];

// Icon per nav item
function NavIcon({ id }: { id: NavPage }) {
  switch (id) {
    case "overview":   return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9632;</span>;
    case "code-graph": return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9903;</span>;
    case "guardian":   return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9672;</span>;
    case "cortex":     return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9684;</span>;
    case "approvals":  return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9745;</span>;
    case "operations": return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9881;</span>;
    case "security":   return <span className="w-4 h-4 flex items-center justify-center text-xs">&#128737;</span>;
    case "settings":   return <span className="w-4 h-4 flex items-center justify-center text-xs">&#9881;</span>;
    default:           return null;
  }
}

export default function LeftNav({ activePage, onNavigate, pendingApprovals = 0 }: Props) {
  return (
    <nav className="w-52 shrink-0 flex flex-col bg-[#0d1117] border-r border-slate-800/60 overflow-hidden">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-slate-800/60">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shrink-0">
            <span className="text-white text-xs font-bold">S</span>
          </div>
          <div>
            <div className="text-sm font-bold text-white tracking-tight">SYNAPSE</div>
            <div className="text-[10px] text-slate-500 leading-tight">Understanding Layer for AI Agents</div>
          </div>
        </div>
      </div>

      {/* Nav items */}
      <div className="flex-1 py-2 space-y-0.5 px-2">
        {NAV_ITEMS.map((item) => {
          const isActive = activePage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                isActive
                  ? "bg-blue-600/20 text-blue-400 font-medium"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
              }`}
            >
              <NavIcon id={item.id} />
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

      {/* Footer */}
      <div className="px-4 py-3 border-t border-slate-800/60 space-y-1">
        <div className="text-xs text-slate-500 font-mono">v0.1.0</div>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block"></span>
          <span className="text-xs text-green-400">System Healthy</span>
        </div>
      </div>
    </nav>
  );
}
