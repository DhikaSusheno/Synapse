"use client";

// app/page.tsx
// Halaman utama Synapse - graph + sidebar
// FE-1 @nabilfauzandafa
// FE-2 @ShannWasHere - node counter wiring + encoding fix

import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import type { GraphNode } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

// SynapseGraph di-lazy-load karena butuh canvas (browser only)
const SynapseGraph = dynamic(() => import("@/components/SynapseGraph"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      Initializing graph engine.
    </div>
  ),
});

const OperationsSidebar = dynamic(
  () => import("@/components/OperationsSidebar"),
  { ssr: false }
);

// --- Hook: repo health score dari backend ---
interface HealthSummary {
  health_score: number;
  summary: string;
  doc_coverage_percent: number;
}

function useRepoHealth(): HealthSummary | null {
  const [health, setHealth] = useState<HealthSummary | null>(null);

  useEffect(() => {
    if (!USE_LIVE) return;

    async function load() {
      try {
        const res = await fetch(`${BACKEND_URL}/repo_health`);
        if (res.ok) {
          const data = await res.json();
          if (data.ok) setHealth(data as HealthSummary);
        }
      } catch {
        // backend offline - tidak tampilkan badge
      }
    }

    load();
    const interval = setInterval(load, 30_000); // refresh tiap 30 detik
    return () => clearInterval(interval);
  }, []);

  return health;
}

export default function HomePage() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [nodeCount, setNodeCount] = useState<{ nodes: number; links: number } | null>(null);
  const health = useRepoHealth();

  const handleNodeCount = useCallback((nodes: number, links: number) => {
    setNodeCount({ nodes, links });
  }, []);

  const healthColor =
    !health ? undefined :
    health.health_score >= 80 ? { border: "#22c55e", text: "#86efac" } :
    health.health_score >= 60 ? { border: "#f59e0b", text: "#fcd34d" } :
                                { border: "#ef4444", text: "#fca5a5" };

  const healthEmoji =
    !health ? "" :
    health.health_score >= 80 ? "OK" :
    health.health_score >= 60 ? "WARN" : "CRIT";

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 bg-slate-900 shrink-0">
        <span className="text-lg font-bold tracking-tight">&#x1F9E0; Synapse</span>
        <span className="text-xs text-slate-400 hidden sm:block">
          Reversible &middot; Conflict-aware &middot; AI agent guardrail
        </span>

        {/* Node + edge counter - dikirim dari SynapseGraph via onNodeCount */}
        {nodeCount !== null && (
          <div className="hidden sm:flex items-center gap-1.5 ml-1 px-2 py-0.5 rounded-full text-xs font-mono bg-slate-800 text-slate-400 border border-slate-700">
            <span>{nodeCount.nodes} nodes</span>
            <span className="text-slate-600">&middot;</span>
            <span>{nodeCount.links} edges</span>
          </div>
        )}

        {/* Repo health badge - hanya muncul saat live mode dan data tersedia */}
        {health && healthColor && (
          <div
            className="hidden md:flex items-center gap-1.5 ml-2 px-2 py-0.5 rounded-full text-xs font-mono border"
            style={{ borderColor: healthColor.border, color: healthColor.text }}
            title={health.summary}
          >
            <span>[{healthEmoji}]</span>
            <span>Health {health.health_score}/100</span>
            <span className="text-slate-500">&middot;</span>
            <span>Docs {health.doc_coverage_percent}%</span>
          </div>
        )}

        <span className="ml-auto text-xs text-slate-500 font-mono">
          IBM Bob 2.0 Hackathon
        </span>
      </header>

      {/* Body: graph + sidebar */}
      <div className="flex flex-1 overflow-hidden">
        <main className="flex-1 overflow-hidden relative">
          <SynapseGraph onNodeClick={setSelectedNode} onNodeCount={handleNodeCount} />
        </main>
        <OperationsSidebar selectedNode={selectedNode} />
      </div>
    </div>
  );
}