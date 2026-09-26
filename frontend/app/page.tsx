"use client";

// app/page.tsx
// Halaman utama Synapse - graph + sidebar
// FE-1 @nabilfauzandafa · FE-2 @ShannWasHere

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import type { GraphNode } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const SynapseGraph = dynamic(() => import("@/components/SynapseGraph"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      Initializing graph engine...
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
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  return health;
}

export default function HomePage() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [graphCount, setGraphCount] = useState({ nodes: 0, links: 0 });
  const health = useRepoHealth();

  const handleNodeCount = useCallback((nodes: number, links: number) => {
    setGraphCount({ nodes, links });
  }, []);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 bg-slate-900 shrink-0">
        <span className="text-lg font-bold tracking-tight">&#x1F9E0; Synapse</span>
        <span className="text-xs text-slate-400 hidden sm:block">
          Reversible &middot; Conflict-aware &middot; AI agent guardrail
        </span>

        {/* Graph node/link counter */}
        {(graphCount.nodes > 0 || !USE_LIVE) && (
          <span className="hidden md:inline text-xs text-slate-600 font-mono">
            {graphCount.nodes}n / {graphCount.links}e
          </span>
        )}

        {/* Repo health badge - hanya muncul saat live mode */}
        {health && (
          <div
            className="hidden md:flex items-center gap-1.5 ml-1 px-2 py-0.5 rounded-full text-xs font-mono border"
            style={{
              borderColor:
                health.health_score >= 80 ? "#22c55e" :
                health.health_score >= 60 ? "#f59e0b" : "#ef4444",
              color:
                health.health_score >= 80 ? "#86efac" :
                health.health_score >= 60 ? "#fcd34d" : "#fca5a5",
            }}
            title={health.summary}
          >
            <span>
              {health.health_score >= 80 ? "&#x1F49A;" :
               health.health_score >= 60 ? "&#x1F7E1;" : "&#x1F534;"}
            </span>
            <span>Health {health.health_score}/100</span>
            <span className="text-slate-600">&middot;</span>
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
          <SynapseGraph
            onNodeClick={setSelectedNode}
            onNodeCount={handleNodeCount}
          />
        </main>
        <OperationsSidebar selectedNode={selectedNode} />
      </div>
    </div>
  );
}
