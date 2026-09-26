"use client";
// app/page.tsx
// Shell layout 3-kolom + routing 8 halaman sesuai DESIGN_SYSTEM.md
// FE-1 @nabilfauzandafa · FE-2 @ShannWasHere

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { GraphNode, Operation } from "@/lib/types";
import type { NavPage } from "@/components/LeftNav";
import { mapPending, stamp, withConflicts } from "@/lib/derive";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

// --- Dynamic imports (no SSR) ---
const LeftNav          = dynamic(() => import("@/components/LeftNav"),          { ssr: false });
const TopNavbar        = dynamic(() => import("@/components/TopNavbar"),        { ssr: false });
const GuardianPanel    = dynamic(() => import("@/components/GuardianPanel"),    { ssr: false });
const OverviewMain     = dynamic(() => import("@/components/OverviewMain"),     { ssr: false, loading: () => <PageLoading /> });
const SynapseGraph     = dynamic(() => import("@/components/SynapseGraph"),     { ssr: false, loading: () => <PageLoading /> });

// Pages
const CodeGraphPage  = dynamic(() => import("@/components/pages/CodeGraphPage"),  { ssr: false, loading: () => <PageLoading /> });
const GuardianPage   = dynamic(() => import("@/components/pages/GuardianPage"),   { ssr: false, loading: () => <PageLoading /> });
const CortexPage     = dynamic(() => import("@/components/pages/CortexPage"),     { ssr: false, loading: () => <PageLoading /> });
const AgentsPage     = dynamic(() => import("@/components/pages/AgentsPage"),     { ssr: false, loading: () => <PageLoading /> });
const SecurityPage   = dynamic(() => import("@/components/pages/SecurityPage"),   { ssr: false, loading: () => <PageLoading /> });
const SettingsPage   = dynamic(() => import("@/components/pages/SettingsPage"),   { ssr: false, loading: () => <PageLoading /> });

function PageLoading() {
  return (
    <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
      <span className="animate-pulse">Loading...</span>
    </div>
  );
}

// --- Mock operations fallback ---
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

// --- Hook: load operations from backend or mock ---
function useOperations(): [Operation[], (id: string, d: "approved" | "denied") => void] {
  const [ops, setOps] = useState<Operation[]>(USE_LIVE ? [] : MOCK_OPERATIONS);

  useEffect(() => {
    if (!USE_LIVE) return;
    async function load() {
      try {
        const [pendingRes, historyRes] = await Promise.all([
          fetch(`${BACKEND_URL}/list_pending_approvals`, { cache: "no-store" }).catch(() => null),
          fetch(`${BACKEND_URL}/operations?limit=50`, { cache: "no-store" }).catch(() => null),
        ]);
        if (!pendingRes?.ok && !historyRes?.ok) return;
        const pendingData = pendingRes?.ok ? ((await pendingRes.json()) as { pending?: unknown }) : null;
        const historyData = historyRes?.ok ? await historyRes.json() : null;
        const history = mapPending(historyData).filter(
          (op) => op.requires_approval === 1 && op.status !== "pending"
        );
        setOps(withConflicts([...mapPending(pendingData?.pending ?? []), ...history]));
      } catch { /* backend not ready */ }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleDecided = useCallback((opId: string, decision: "approved" | "denied") => {
    setOps((prev) =>
      prev.map((op) => op.id === opId ? { ...op, status: decision === "approved" ? "approved" : "denied" } : op)
    );
  }, []);

  return [ops, handleDecided];
}

// --- ApprovalCard & ApprovalsPage (FE-2 @ShannWasHere, tetap di sini) ---
const BLAST_BADGE: Record<string, string> = {
  high:    "bg-red-500/20 text-red-400 border border-red-500/30",
  medium:  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  low:     "bg-green-500/20 text-green-400 border border-green-500/30",
  unknown: "bg-slate-700 text-slate-400 border border-slate-600",
};
const STATUS_BADGE: Record<string, string> = {
  pending:     "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  approved:    "bg-blue-500/20 text-blue-400 border border-blue-500/30",
  executing:   "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  verified:    "bg-green-500/20 text-green-400 border border-green-500/30",
  failed:      "bg-red-500/20 text-red-400 border border-red-500/30",
  rolled_back: "bg-red-500/20 text-red-300 border border-red-500/30",
  denied:      "bg-slate-700 text-slate-400 border border-slate-600",
  idle:        "bg-slate-700 text-slate-500 border border-slate-700",
};

function ApprovalCard({ op, onDecided }: { op: Operation; onDecided?: (id: string, d: "approved" | "denied") => void }) {
  const [loading, setLoading] = useState(false);
  const [localStatus, setLocalStatus] = useState(op.status);
  const [errorMsg, setErrorMsg]       = useState<string | null>(null);
  async function decide(decision: "approved" | "denied") {
    setLoading(true); setErrorMsg(null);
    try {
      const r = await fetch(`${BACKEND_URL}/approve_operation`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: op.id, decision }),
      }).catch(() => null);
      const ad = (await r?.json().catch(() => null)) as { status?: string; detail?: string } | null;
      if (!r?.ok) { setErrorMsg(ad?.detail ?? "Approve ditolak backend."); return; }
      setLocalStatus((ad?.status as Operation["status"]) ?? (decision === "approved" ? "approved" : "denied"));
      if (decision === "approved") {
        setLocalStatus("executing");
        const er = await fetch(`${BACKEND_URL}/execute_operation`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ operation_id: op.id }),
        }).catch(() => null);
        const ed = (await er?.json().catch(() => null)) as { status?: string; error?: string; detail?: string; ok?: boolean } | null;
        if (!er?.ok) { setLocalStatus("failed"); setErrorMsg(ed?.detail ?? "Execute gagal."); return; }
        setLocalStatus((ed?.status as Operation["status"]) ?? "verified");
        if (ed?.ok === false) { setLocalStatus("failed"); setErrorMsg(ed.error ?? "Execute gagal."); }
      }
      onDecided?.(op.id, decision);
    } finally { setLoading(false); }
  }
  const params = (() => { try { return JSON.parse(op.params_json); } catch { return {}; } })();
  const isDone = localStatus !== "pending";
  return (
    <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">{op.tool_name}</div>
          {params.sql && <div className="text-xs text-slate-400 font-mono mt-0.5 truncate">{params.sql}</div>}
          {op.target_node_id && <div className="text-xs text-slate-500 mt-0.5 truncate">Target: {op.target_node_id}</div>}
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${BLAST_BADGE[op.blast_radius] ?? BLAST_BADGE.unknown}`}>{op.blast_radius.toUpperCase()} RISK</span>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${STATUS_BADGE[localStatus] ?? STATUS_BADGE.idle}`}>{localStatus.toUpperCase()}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <span className="text-slate-500">ID</span><span className="text-slate-400 font-mono truncate">{op.id.slice(0, 16)}…</span>
        <span className="text-slate-500">Time</span><span className="text-slate-400">{stamp(op.created_at)}</span>
      </div>
      {op.conflicts && op.conflicts.length > 0 && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2 flex items-center gap-1.5">
          <span>&#9888;</span><span>Conflicts with: {op.conflicts.join(", ")}</span>
        </div>
      )}
      {errorMsg && <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2">{errorMsg}</div>}
      {!isDone ? (
        <div className="flex gap-2">
          <button onClick={() => decide("approved")} disabled={loading} className="flex-1 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-bold disabled:opacity-50 transition-colors">{loading ? "…" : "Approve"}</button>
          <button onClick={() => decide("denied")}   disabled={loading} className="flex-1 py-2 rounded-lg bg-red-700/80 hover:bg-red-600 text-white text-xs font-bold disabled:opacity-50 transition-colors">{loading ? "…" : "Deny"}</button>
        </div>
      ) : (
        <div className={`text-xs text-center py-2 rounded-lg font-semibold ${
          localStatus === "verified" || localStatus === "approved" ? "bg-green-900/30 text-green-400" :
          localStatus === "failed" || localStatus === "rolled_back"  ? "bg-red-900/30 text-red-400" : "bg-slate-700/50 text-slate-400"
        }`}>{localStatus.toUpperCase()}</div>
      )}
    </div>
  );
}

function ApprovalsPage({ ops, onOpDecided }: { ops: Operation[]; onOpDecided: (id: string, d: "approved"|"denied") => void }) {
  const pending = ops.filter((op) => op.status === "pending");
  const decided = ops.filter((op) => op.status !== "pending");
  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-6 space-y-6">
      <div><h1 className="text-xl font-bold text-white">Approvals</h1><p className="text-sm text-slate-400 mt-0.5">Review and approve or deny pending risky operations.</p></div>
      <div>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold text-white">Pending</h2>
          {pending.length > 0 && <span className="text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 px-2 py-0.5 rounded-full font-bold">{pending.length}</span>}
        </div>
        {pending.length === 0 ? (
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-6 text-xs text-slate-500 text-center">No pending approvals</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">{pending.map((op) => <ApprovalCard key={op.id} op={op} onDecided={onOpDecided} />)}</div>
        )}
      </div>
      {decided.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-white mb-3">History</h2>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">{decided.map((op) => <ApprovalCard key={op.id} op={op} onDecided={onOpDecided} />)}</div>
        </div>
      )}
    </div>
  );
}

// --- OperationsPage (FE-2 @ShannWasHere) ---
interface BackendOp { id:string; tool_name:string; params_json:string; target_node_id:string|null; blast_radius:string; status:string; requires_approval:number; created_at:string; }

function OperationsPage() {
  const [ops, setOps]           = useState<BackendOp[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string|null>(null);
  const [statusFilter, setFilter] = useState("all");
  const intervalRef = useRef<ReturnType<typeof setInterval>|null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const url = statusFilter === "all" ? `${BACKEND_URL}/operations?limit=50` : `${BACKEND_URL}/operations?status=${statusFilter}&limit=50`;
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as unknown;
        setOps(Array.isArray(data) ? (data as BackendOp[]) : []);
      } else setError("Backend tidak dapat dijangkau");
    } catch { setError("Backend offline"); }
  }, [statusFilter]);

  useEffect(() => {
    setLoading(true); load().finally(() => setLoading(false));
    intervalRef.current = setInterval(load, 5000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [load]);

  const STATUS_OPTIONS = ["all","pending","approved","executing","verified","failed","rolled_back","denied"];
  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div><h1 className="text-xl font-bold text-white">Operations</h1><p className="text-sm text-slate-400 mt-0.5">Full history of all proposed and executed operations.</p></div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-500">Filter:</span>
          <select value={statusFilter} onChange={(e) => setFilter(e.target.value)} className="text-xs bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-slate-300 outline-none">
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s === "all" ? "All Status" : s}</option>)}
          </select>
          <button onClick={() => load()} className="text-xs px-3 py-1.5 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors">&#8635; Refresh</button>
        </div>
      </div>
      {error && <div className="bg-yellow-900/20 border border-yellow-500/30 rounded-xl px-4 py-3 text-xs text-yellow-400">{error}</div>}
      {loading && ops.length === 0 ? (
        <div className="flex items-center justify-center py-16 text-slate-500 text-sm">Loading operations...</div>
      ) : ops.length === 0 ? (
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-10 text-xs text-slate-500 text-center">No operations found.</div>
      ) : (
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 overflow-hidden">
          <div className="grid grid-cols-[minmax(0,2fr)_120px_100px_100px_140px] gap-3 px-4 py-2.5 border-b border-slate-800/60 text-[10px] text-slate-500 uppercase tracking-wide font-semibold">
            <span>Tool / Target</span><span>Blast Radius</span><span>Status</span><span>Approval</span><span>Created</span>
          </div>
          <div className="divide-y divide-slate-800/40">
            {ops.map((op) => {
              const params = (() => { try { return JSON.parse(op.params_json); } catch { return {}; } })();
              return (
                <div key={op.id} className="grid grid-cols-[minmax(0,2fr)_120px_100px_100px_140px] gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors items-center">
                  <div className="min-w-0"><div className="text-xs font-medium text-white truncate">{op.tool_name}</div>{params.sql && <div className="text-[10px] text-slate-500 font-mono truncate">{params.sql}</div>}</div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border w-fit ${BLAST_BADGE[op.blast_radius] ?? BLAST_BADGE.unknown}`}>{op.blast_radius.toUpperCase()}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border w-fit ${STATUS_BADGE[op.status] ?? STATUS_BADGE.idle}`}>{op.status}</span>
                  <span className="text-[10px] text-slate-400">{op.requires_approval ? "Required" : "Auto"}</span>
                  <span className="text-[10px] text-slate-500 font-mono">{stamp(op.created_at)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// --- HomePage ---
export default function HomePage() {
  const [activePage, setActivePage]     = useState<NavPage>("overview");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [graphCount, setGraphCount]     = useState({ nodes: 0, links: 0 });
  const [ops, handleOpDecided]          = useOperations();

  const handleNodeCount = useCallback((nodes: number, links: number) => {
    setGraphCount({ nodes, links });
  }, []);

  const pendingCount = ops.filter((op) => op.status === "pending").length;

  // Halaman yang TIDAK menampilkan GuardianPanel kanan
  const hideRightPanel = !(["overview", "guardian"] as NavPage[]).includes(activePage);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#080d14]">
      <TopNavbar isLive={USE_LIVE} nodeCount={graphCount.nodes} edgeCount={graphCount.links} />

      <div className="flex flex-1 overflow-hidden">
        <LeftNav activePage={activePage} onNavigate={setActivePage} pendingApprovals={pendingCount} />

        {/* ===== Page Content ===== */}
        {activePage === "overview" && (
          <OverviewMain
            onNodeClick={setSelectedNode} onNodeCount={handleNodeCount}
            nodeCount={graphCount.nodes}  edgeCount={graphCount.links}
            operations={ops}
          />
        )}
        {activePage === "code-graph" && (
          <CodeGraphPage
            onNodeClick={setSelectedNode} onNodeCount={handleNodeCount}
            nodeCount={graphCount.nodes}  edgeCount={graphCount.links}
          />
        )}
        {activePage === "guardian"   && <GuardianPage  ops={ops} onOpDecided={handleOpDecided} />}
        {activePage === "cortex"     && <CortexPage />}
        {activePage === "agents"     && <AgentsPage />}
        {activePage === "approvals"  && <ApprovalsPage ops={ops} onOpDecided={handleOpDecided} />}
        {activePage === "operations" && <OperationsPage />}
        {activePage === "security"   && <SecurityPage />}
        {activePage === "settings"   && <SettingsPage />}

        {/* GuardianPanel kanan — hanya overview + guardian */}
        {!hideRightPanel && (
          <GuardianPanel pendingOps={ops} onOpDecided={handleOpDecided} />
        )}
      </div>
    </div>
  );
}
