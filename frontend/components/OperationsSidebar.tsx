"use client";

// components/OperationsSidebar.tsx
// FE-2 placeholder - approve/deny controls + penjelasan operasi
// Owner FE-2: @ShannWasHere (wiring ke API asli)
// Owner FE-1: @nabilfauzandafa (state yang diterima dari graph / SSE)

import { useEffect, useState } from "react";
import type { GraphNode, Operation } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// Data mock operasi (fallback saat backend offline)
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
  {
    id: "op::migrate-002",
    tool_name: "db.run_migration (conflict)",
    params_json: JSON.stringify({ migration: "drop_column_users_legacy" }),
    target_node_id: "file::backend/database.py",
    blast_radius: "high",
    status: "pending",
    requires_approval: 1,
    conflicts: ["op::migrate-001"],
    created_at: new Date().toISOString(),
  },
];

interface Props {
  selectedNode: GraphNode | null;
}

// ─── Badge blast radius ────────────────────────────────────────────────────────────
function BlastBadge({ level }: { level: Operation["blast_radius"] }) {
  const styles: Record<string, string> = {
    high: "bg-red-900 text-red-300",
    medium: "bg-yellow-900 text-yellow-300",
    low: "bg-green-900 text-green-300",
    unknown: "bg-slate-700 text-slate-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[level]}`}>
      {level.toUpperCase()}
    </span>
  );
}

// ─── Badge status ─────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: GraphNode["status"] }) {
  const styles: Record<string, string> = {
    pending: "bg-yellow-900 text-yellow-300",
    approved: "bg-blue-900 text-blue-300",
    executing: "bg-orange-900 text-orange-300",
    verified: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
    rolled_back: "bg-red-900 text-red-300",
    idle: "bg-slate-700 text-slate-400",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[status] ?? styles.idle}`}>
      {status}
    </span>
  );
}

// ─── Kartu operasi tunggal ────────────────────────────────────────────────────
function OperationCard({ op }: { op: Operation }) {
  const [loading, setLoading] = useState(false);
  const [localStatus, setLocalStatus] = useState(op.status);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function decide(decision: "approved" | "denied") {
    setLoading(true);
    setErrorMsg(null);
    try {
      // 1. Approve / deny di backend
      const approveRes = await fetch(`${BACKEND_URL}/approve_operation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: op.id, decision }),
      }).catch(() => null);

      const approveData = approveRes?.ok ? await approveRes.json().catch(() => null) : null;

      if (!approveRes || !approveRes.ok) {
        // Backend offline — simulasi lokal
        await new Promise((r) => setTimeout(r, 600));
        setLocalStatus(decision === "approved" ? "approved" : "failed");
        return;
      }

      setLocalStatus(approveData?.status ?? (decision === "approved" ? "approved" : "failed"));

      // 2. Jika approve → langsung execute di backend
      //    (backend akan emit SSE operation_executing → operation_verified / rolled_back)
      if (decision === "approved") {
        setLocalStatus("executing");
        const execRes = await fetch(`${BACKEND_URL}/execute_operation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ operation_id: op.id }),
        }).catch(() => null);

        if (execRes?.ok) {
          const execData = await execRes.json().catch(() => null);
          setLocalStatus(execData?.status ?? "verified");
        } else {
          setLocalStatus("failed");
          setErrorMsg("Execute gagal — lihat log backend.");
        }
      }
    } finally {
      setLoading(false);
    }
  }

  const params = (() => {
    try { return JSON.parse(op.params_json); } catch { return {}; }
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

      {op.conflicts && op.conflicts.length > 0 && (
        <div className="text-xs text-red-400 flex items-center gap-1">
          <span>⚡</span>
          <span>Konflik dengan: {op.conflicts.join(", ")}</span>
        </div>
      )}

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

      {errorMsg && (
        <div className="text-xs text-red-400">{errorMsg}</div>
      )}

      {localStatus === "pending" && op.requires_approval === 1 && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => decide("approved")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-green-700 hover:bg-green-600 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "…" : "✅ Approve"}
          </button>
          <button
            onClick={() => decide("denied")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-red-800 hover:bg-red-700 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "…" : "❌ Deny"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Panel info node yang diklik di graph ─────────────────────────────────────
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

// ─── Hook: fetch operasi dari /list_pending_approvals, fallback ke mock ────────────
function useOperations() {
  const [ops, setOps] = useState<Operation[]>(MOCK_OPERATIONS);

  useEffect(() => {
    const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
    if (!USE_LIVE) return;

    async function load() {
      try {
        // Endpoint resmi backend: GET /list_pending_approvals
        const res = await fetch(`${BACKEND_URL}/list_pending_approvals`, {
          cache: "no-store",
        });
        if (res.ok) {
          const data = await res.json();
          // Backend return { ok, count, pending: [...] }
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
      } catch {
        // backend belum siap — tetap pakai mock
      }
    }

    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return ops;
}

// ─── Sidebar utama ────────────────────────────────────────────────────────────
export default function OperationsSidebar({ selectedNode }: Props) {
  const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
  const ops = useOperations();

  return (
    <aside className="w-72 shrink-0 border-l border-slate-700 flex flex-col overflow-hidden bg-slate-900">
      <div className="px-4 py-3 border-b border-slate-700">
        <h2 className="text-sm font-semibold text-slate-200">Operations</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          {USE_LIVE ? "🟢 Live — dari backend" : "🟡 Mock — data simulasi"}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {selectedNode && <NodeInfoPanel node={selectedNode} />}

        <div className="text-xs text-slate-400 uppercase tracking-wide px-0.5">
          Pending approvals
        </div>
        {ops.length === 0 ? (
          <p className="text-xs text-slate-500 px-0.5">Tidak ada operasi pending.</p>
        ) : (
          ops.map((op) => <OperationCard key={op.id} op={op} />)
        )}
      </div>

      <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500">
        Klik node di graph untuk detail
      </div>
    </aside>
  );
}
