"use client";

// app/page.tsx
// Halaman utama Synapse — graph + sidebar
// FE-1 @nabilfauzandafa

import { useState } from "react";
import dynamic from "next/dynamic";
import type { GraphNode } from "@/lib/types";

// SynapseGraph di-lazy-load karena butuh canvas (browser only)
const SynapseGraph = dynamic(() => import("@/components/SynapseGraph"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      Initializing graph engine…
    </div>
  ),
});

const OperationsSidebar = dynamic(
  () => import("@/components/OperationsSidebar"),
  { ssr: false }
);

export default function HomePage() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 bg-slate-900 shrink-0">
        <span className="text-lg font-bold tracking-tight">
          ⚡ Synapse
        </span>
        <span className="text-xs text-slate-400 hidden sm:block">
          Reversible · Conflict-aware · AI agent guardrail
        </span>
        <span className="ml-auto text-xs text-slate-500 font-mono">
          IBM Bob 2.0 Hackathon
        </span>
      </header>

      {/* Body: graph + sidebar */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph area — mengisi sisa ruang */}
        <main className="flex-1 overflow-hidden relative">
          <SynapseGraph onNodeClick={setSelectedNode} />
        </main>

        {/* Sidebar */}
        <OperationsSidebar selectedNode={selectedNode} />
      </div>
    </div>
  );
}
