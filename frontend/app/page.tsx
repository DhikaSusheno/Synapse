"use client";

// app/page.tsx
// Layout utama Synapse — 3-kolom: LeftNav + Main + GuardianPanel
// Sesuai prototype prototawalsynapse.jpeg
// FE-1 @nabilfauzandafa · FE-2 @ShannWasHere

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import type { GraphNode, Operation } from "@/lib/types";
import type { NavPage } from "@/components/LeftNav";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const LeftNav = dynamic(() => import("@/components/LeftNav"), { ssr: false });
const TopNavbar = dynamic(() => import("@/components/TopNavbar"), { ssr: false });
const GuardianPanel = dynamic(() => import("@/components/GuardianPanel"), { ssr: false });
const OverviewMain = dynamic(() => import("@/components/OverviewMain"), { ssr: false,
  loading: () => <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">Loading...</div>
});
const OperationsSidebar = dynamic(() => import("@/components/OperationsSidebar"), { ssr: false });

const MOCK_OPERATIONS: Operation[] = [
  {
    id: "op::migrate-tag",
    tool_name: "db.run_migration",
    params_json: JSON.stringify({ sql: "ALTER TABLE nodes ADD COLUMN tag TEXT DEFAULT NULL;", db_path: "synapse.db" }),
    target_node_id: "operation_target::synapse.db::nodes",
    blast_radius: "high",
    status: "pending",
    requires_approval: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "op::migrate-priority",
    tool_name: "db.run_migration (conflict)",
    params_json: JSON.stringify({ sql: "ALTER TABLE nodes ADD COLUMN priority INTEGER DEFAULT 0;" }),
    target_node_id: "operation_target::synapse.db::nodes",
    blast_radius: "high",
    status: "pending",
    requires_approval: 1,
    conflicts: ["op::migrate-tag"],
    created_at: new Date().toISOString(),
  },
];

function useOperations(): [Operation[], (id: string, d: "approved" | "denied") => void] {
  const [ops, setOps] = useState<Operation[]>(MOCK_OPERATIONS);

  useEffect(() => {
    if (!USE_LIVE) return;
    async function load() {
      try {
        const res = await fetch(`${BACKEND_URL}/list_pending_approvals`, { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          const pending: Operation[] = (data.pending ?? []).map(
            (op: Record<string, unknown>) => ({
              id: op.id as string,
              tool_name: op.tool_name as string,
              params_json: (op.params_json as string) ?? "{}",
              target_node_id: (op.target_node_id as string) ?? null,
              blast_radius: (op.blast_radius as Operation["blast_radius"]) ?? "unknown",
              status: (op.status as GraphNode["status"]) ?? "pending",
              requires_approval: (op.requires_approval as number) ?? 1,
              conflicts: op.conflicts ? (op.conflicts as string[]) : undefined,
              created_at: (op.created_at as string) ?? new Date().toISOString(),
            })
          );
          if (pending.length > 0) setOps(pending);
        }
      } catch { /* backend not ready */ }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleDecided = useCallback((opId: string, decision: "approved" | "denied") => {
    setOps((prev) =>
      prev.map((op) =>
        op.id === opId
          ? { ...op, status: decision === "approved" ? "approved" : "failed" }
          : op
      )
    );
  }, []);

  return [ops, handleDecided];
}

export default function HomePage() {
  const [activePage, setActivePage] = useState<NavPage>("overview");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [graphCount, setGraphCount] = useState({ nodes: 0, links: 0 });
  const [ops, handleOpDecided] = useOperations();

  const handleNodeCount = useCallback((nodes: number, links: number) => {
    setGraphCount({ nodes, links });
  }, []);

  const pendingCount = ops.filter((op) => op.status === "pending").length;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#080d14]">
      {/* Top navbar */}
      <TopNavbar
        isLive={USE_LIVE}
        nodeCount={graphCount.nodes}
        edgeCount={graphCount.links}
      />

      {/* Body: LeftNav + Main + GuardianPanel */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left navigation */}
        <LeftNav
          activePage={activePage}
          onNavigate={setActivePage}
          pendingApprovals={pendingCount}
        />

        {/* Main content area */}
        {activePage === "overview" && (
          <OverviewMain
            onNodeClick={setSelectedNode}
            onNodeCount={handleNodeCount}
            nodeCount={graphCount.nodes}
            edgeCount={graphCount.links}
            operations={ops}
          />
        )}

        {activePage === "code-graph" && (
          <div className="flex flex-1 overflow-hidden">
            <main className="flex-1 overflow-hidden relative">
              {/* Inline dynamic import to avoid circular dep */}
              <div className="w-full h-full" id="code-graph-full" />
            </main>
            <OperationsSidebar selectedNode={selectedNode} />
          </div>
        )}

        {activePage === "approvals" && (
          <div className="flex-1 overflow-y-auto p-6">
            <h1 className="text-xl font-bold text-white mb-4">Approvals</h1>
            <OperationsSidebar selectedNode={selectedNode} />
          </div>
        )}

        {(activePage === "guardian" || activePage === "cortex" || activePage === "operations" || activePage === "security" || activePage === "settings") && (
          <div className="flex-1 flex items-center justify-center text-slate-500">
            <div className="text-center">
              <div className="text-4xl mb-3">&#128736;</div>
              <div className="text-sm">{activePage.charAt(0).toUpperCase() + activePage.slice(1)} panel coming soon</div>
            </div>
          </div>
        )}

        {/* Guardian right panel — show on overview + guardian pages */}
        {(activePage === "overview" || activePage === "guardian") && (
          <GuardianPanel
            pendingOps={ops}
            onOpDecided={handleOpDecided}
          />
        )}
      </div>
    </div>
  );
}
