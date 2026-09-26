"use client";

// components/OperationsSidebar.tsx
// FE-2 placeholder — approve/deny controls + penjelasan operasi
// Owner FE-2: @ShannWasHere (wiring ke API asli)
// Owner FE-1: @nabilfauzandafa (state yang diterima dari graph / SSE)

import { useState } from "react";
import type { GraphNode, Operation } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// ─── Data mock operasi (ganti dengan fetch ke GET /operations saat live) ─────
const MOCK_OPERATIONS: Operation[] = [
  {
    id: "op::migrate-001",
    tool_name: "db.run_migration",
    params_json: JSON.stringify({ migration: "add_column_users_verified" }),
    target_node_id: "file::backend/database.py",
    blast_radius: "high",
    status: "pending",
    requires_approval: 1,
    created_at: new Date().toISOString(),
  },
];

interface Props {
  selectedNode: GraphNode | null;
}

// ─── Badge warna blast radius ─────────────────────────────────────────────
function BlastBadge({ level }: { level: Operation["blast_radius"] }) {
  const styles: Record<string, string> = {
    high:    "bg-red-900 text-red-300",
    medium:  "bg-yellow-900 text-yellow-300",
    low:     "bg-green-900 text-green-300",
    unknown: "bg-slate-700 text-slate-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[level]}`}>
      {level.toUpperCase()}
    </span>
  );
}

// ─── Badge status ─────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: GraphNode["status"] }) {
  const styles: Record<string, string> = {
    pending:     "bg-yellow-900 text-yellow-300",
    approved:    "bg-blue-900 text-blue-300",
    executing:   "bg-orange-900 text-orange-300",
    verified:    "bg-green-900 text-green-300",
    failed:      "bg-red-900 text-red-300",
    rolled_back: "bg-red-900 text-red-300",
    idle:        "bg-slate-700 text-slate-400",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[status] ?? styles.idle}`}>
      {status}
    </span>
  );
}

// ─── Kartu operasi tunggal ────────────────────────────────────────────────
function OperationCard({ op }: { op: Operation }) {
  const [loading, setLoading] = useState(false);
  const [localStatus, setLocalStatus] = useState(op.status);

  async function decide(decision: "approved" | "denied") {
    setLoading(true);
    try {
      // TODO FE-2: ganti dengan endpoint asli saat backend selesai
      // await fetch(`${BACKEND_URL}/approve_operation`, {
      //   method: "POST",
      //   headers: { "Content-Type": "application/json" },
      //   body: JSON.stringify({ operation_id: op.id, decision }),
      // });
      await new Promise((r) => setTimeout(r, 600)); // simulasi
      setLocalStatus(decision === "approved" ? "approved" : "failed");
    } finally {
      setLoading(false);
    }
  }

  const params = (() => {
    try {
      return JSON.parse(op.params_json);
    } catch {
      return {};
    }
  })();

  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 bg-slate-800/50">
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-sm text-white break-all">{op.tool_name}</span>
        <StatusBadge status={localStatus} />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400">Blast radius:</span>
        <BlastBadge level={op.blast_radius} />
      </div>

      {Object.keys(params).length > 0 && (
        <div className="text-xs text-slate-400 font-mono bg-slate-900 rounded p-1.5 break-all">
          {JSON.stringify(params, null, 2)}
        </div>
      )}

      {op.target_node_id && (
        <div className="text-xs text-slate-400">
          Target: <span className="text-slate-300">{op.target_node_id}</span>
        </div>
      )}

      {localStatus === "pending" && op.requires_approval === 1 && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => decide("approved")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-green-700 hover:bg-green-600 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "…" : "✓ Approve"}
          </button>
          <button
            onClick={() => decide("denied")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-red-800 hover:bg-red-700 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "…" : "✗ Deny"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Panel info node yang diklik di graph ────────────────────────────────
function NodeInfoPanel({ node }: { node: GraphNode }) {
  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-1 bg-slate-800/50">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Node terpilih</div>
      <div className="font-mono text-sm text-white break-all">{node.name}</div>
      <div className="flex gap-2 items-center">
        <span className="text-xs text-slate-400">type:</span>
        <span className="text-xs text-slate-300">{node.type}</span>
      </div>
      <div className="flex gap-2 items-center">
        <span className="text-xs text-slate-400">status:</span>
        <StatusBadge status={node.status} />
      </div>
      {node.meta && Object.keys(node.meta).length > 0 && (
        <div className="text-xs text-slate-400 font-mono bg-slate-900 rounded p-1.5 break-all mt-1">
          {JSON.stringify(node.meta, null, 2)}
        </div>
      )}
    </div>
  );
}

// ─── Sidebar utama ────────────────────────────────────────────────────────
export default function OperationsSidebar({ selectedNode }: Props) {
  const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

  return (
    <aside className="w-72 shrink-0 border-l border-slate-700 flex flex-col overflow-hidden bg-slate-900">
      <div className="px-4 py-3 border-b border-slate-700">
        <h2 className="text-sm font-semibold text-slate-200">Operations</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          {USE_LIVE ? "Live — dari backend" : "Mock — data simulasi"}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {/* Info node terpilih */}
        {selectedNode && <NodeInfoPanel node={selectedNode} />}

        {/* Daftar operasi */}
        <div className="text-xs text-slate-400 uppercase tracking-wide px-0.5">
          Pending approvals
        </div>
        {MOCK_OPERATIONS.map((op) => (
          <OperationCard key={op.id} op={op} />
        ))}
      </div>

      {/* Footer hint */}
      <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500">
        Klik node di graph untuk detail
      </div>
    </aside>
  );
}
