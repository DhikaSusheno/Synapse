"use client";

// components/OperationsSidebar.tsx
// FE-2 placeholder - approve/deny controls + penjelasan operasi
// Owner FE-2: @ShannWasHere (wiring ke API asli + encoding fix)
// Owner FE-1: @nabilfauzandafa (state, explain_topic panel, repo_health, event log)

import { useEffect, useRef, useState } from "react";
import type { GraphNode, Operation } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

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

interface Props {
  selectedNode: GraphNode | null;
}

// --- Badge ---
function BlastBadge({ level }: { level: Operation["blast_radius"] }) {
  const styles: Record<string, string> = {
    high: "bg-red-900 text-red-300",
    medium: "bg-yellow-900 text-yellow-300",
    low: "bg-green-900 text-green-300",
    unknown: "bg-slate-700 text-slate-300",
  };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[level]}`}>{level.toUpperCase()}</span>;
}

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
  return <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${styles[status] ?? styles.idle}`}>{status}</span>;
}

// --- Kartu operasi ---
function OperationCard({ op }: { op: Operation }) {
  const [loading, setLoading] = useState(false);
  const [localStatus, setLocalStatus] = useState(op.status);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function decide(decision: "approved" | "denied") {
    setLoading(true);
    setErrorMsg(null);
    try {
      const approveRes = await fetch(`${BACKEND_URL}/approve_operation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: op.id, decision }),
      }).catch(() => null);

      const approveData = approveRes?.ok ? await approveRes.json().catch(() => null) : null;

      if (!approveRes || !approveRes.ok) {
        await new Promise((r) => setTimeout(r, 600));
        setLocalStatus(decision === "approved" ? "approved" : "failed");
        return;
      }

      setLocalStatus(
        ((approveData?.status ?? approveData?.new_status) as GraphNode["status"]) ??
        (decision === "approved" ? "approved" : "failed")
      );

      if (decision === "approved") {
        setLocalStatus("executing");
        const execRes = await fetch(`${BACKEND_URL}/execute_operation`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ operation_id: op.id }),
        }).catch(() => null);

        if (execRes?.ok) {
          const execData = await execRes.json().catch(() => null);
          setLocalStatus((execData?.status ?? "verified") as GraphNode["status"]);
          if (!execData?.ok) setErrorMsg(execData?.error ?? "Execute gagal.");
        } else {
          setLocalStatus("failed");
          setErrorMsg("Execute gagal - lihat log backend.");
        }
      }
    } finally {
      setLoading(false);
    }
  }

  const params = (() => { try { return JSON.parse(op.params_json); } catch { return {}; } })();

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
          <span>&#9888;</span>
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
          Target: <span className="text-slate-300 break-all">{op.target_node_id}</span>
        </div>
      )}
      {errorMsg && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-1.5">{errorMsg}</div>
      )}
      {localStatus === "pending" && op.requires_approval === 1 && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => decide("approved")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-green-700 hover:bg-green-600 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "..." : "Approve"}
          </button>
          <button
            onClick={() => decide("denied")}
            disabled={loading}
            className="flex-1 text-xs py-1.5 rounded bg-red-800 hover:bg-red-700 text-white font-semibold disabled:opacity-50 transition-colors"
          >
            {loading ? "..." : "Deny"}
          </button>
        </div>
      )}
    </div>
  );
}

// --- Panel info node + explain_topic ---
interface ExplainResult {
  definition: string;
  mental_model: string;
  complexity_note: string;
  how_to_use: string;
  example: string;
}

function NodeInfoPanel({ node }: { node: GraphNode }) {
  const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
  const [explain, setExplain] = useState<ExplainResult | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);

  useEffect(() => {
    if (!USE_LIVE) return;
    let cancelled = false;
    setExplain(null);
    setExplainLoading(true);
    fetch(`${BACKEND_URL}/explain_topic`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: node.name }),
    })
      .then((r) => r.json())
      .then((data) => { if (!cancelled && data.ok) setExplain(data as ExplainResult); })
      .catch(() => null)
      .finally(() => { if (!cancelled) setExplainLoading(false); });
    return () => { cancelled = true; };
  }, [node.id, node.name, USE_LIVE]);

  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 bg-slate-800/50">
      <div className="text-xs text-slate-400 uppercase tracking-wide">Node terpilih</div>
      <div className="font-mono text-sm text-white break-all">{node.name}</div>
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-slate-400">type: <span className="text-slate-300">{node.type}</span></span>
        <StatusBadge status={node.status} />
      </div>
      {node.meta && Object.keys(node.meta).length > 0 && (
        <div className="text-xs text-slate-500 font-mono bg-slate-900 rounded p-1.5 break-all">
          {JSON.stringify(node.meta, null, 2)}
        </div>
      )}
      {USE_LIVE && explainLoading && (
        <div className="text-xs text-slate-500 animate-pulse">Menanya graph...</div>
      )}
      {USE_LIVE && explain && (
        <div className="space-y-1.5 pt-1 border-t border-slate-700">
          <div className="text-xs text-slate-400 uppercase tracking-wide">Explain</div>
          <p className="text-xs text-slate-300">{explain.definition}</p>
          <p className="text-xs text-slate-400 italic">{explain.mental_model}</p>
          {explain.complexity_note && <p className="text-xs text-amber-400">{explain.complexity_note}</p>}
          {explain.how_to_use && <p className="text-xs text-slate-400">{explain.how_to_use}</p>}
          {explain.example && explain.example !== "(Tidak ada snippet tersedia)" && (
            <pre className="text-xs text-slate-300 bg-slate-900 rounded p-1.5 overflow-x-auto max-h-24">{explain.example}</pre>
          )}
        </div>
      )}
    </div>
  );
}

// --- Event log - tabel live SSE events (deliverable #6 PRD) ---
interface EventLogEntry {
  ts: string;
  event: string;
  summary: string;
}

// Hook global - subscribe SSE stream dan catat semua event ke log
function useEventLog(enabled: boolean): EventLogEntry[] {
  const [log, setLog] = useState<EventLogEntry[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(`${BACKEND_URL}/stream`);
    esRef.current = es;
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as { event: string; data: Record<string, unknown> };
        if (parsed.event === "heartbeat" || parsed.event === "connected") return;
        const summary = (() => {
          const d = parsed.data;
          if (d.operation_id) return `op ${String(d.operation_id).slice(0, 8)}... ${d.tool_name ?? ""}`.trim();
          if (d.current_doc) return `ingest: ${d.current_doc}`;
          if (d.repo) return `graph: ${d.repo}`;
          return JSON.stringify(d).slice(0, 60);
        })();
        setLog((prev) => [
          { ts: new Date().toLocaleTimeString(), event: parsed.event, summary },
          ...prev.slice(0, 49), // cap at 50 entries
        ]);
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, [enabled]);

  return log;
}

const EVENT_COLORS: Record<string, string> = {
  operation_proposed:    "text-yellow-400",
  operation_approved:    "text-blue-400",
  operation_executing:   "text-orange-400",
  operation_verified:    "text-green-400",
  operation_failed:      "text-red-400",
  operation_rolled_back: "text-red-300",
  operation_denied:      "text-slate-400",
  graph_update:          "text-teal-400",
  ingest_progress:       "text-cyan-400",
  review_done:           "text-purple-400",
  health_report:         "text-emerald-400",
  refactor_suggestion:   "text-indigo-400",
};

function EventLogPanel({ log }: { log: EventLogEntry[] }) {
  if (log.length === 0) {
    return (
      <p className="text-xs text-slate-500 px-0.5">Menunggu event dari backend.</p>
    );
  }
  return (
    <div className="space-y-1">
      {log.map((entry, i) => (
        <div key={i} className="flex gap-2 text-xs">
          <span className="text-slate-600 shrink-0 font-mono">{entry.ts}</span>
          <span className={`shrink-0 font-mono ${EVENT_COLORS[entry.event] ?? "text-slate-400"}`}>
            {entry.event}
          </span>
          <span className="text-slate-500 truncate">{entry.summary}</span>
        </div>
      ))}
    </div>
  );
}

// --- Hook: fetch operasi dari backend, fallback ke mock ---
function useOperations() {
  const [ops, setOps] = useState<Operation[]>(MOCK_OPERATIONS);

  useEffect(() => {
    const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
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
      } catch { /* backend belum siap */ }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return ops;
}

// --- Sidebar utama ---
export default function OperationsSidebar({ selectedNode }: Props) {
  const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";
  const ops = useOperations();
  const eventLog = useEventLog(USE_LIVE);
  const [activeTab, setActiveTab] = useState<"ops" | "log">("ops");

  return (
    <aside className="w-72 shrink-0 border-l border-slate-700 flex flex-col overflow-hidden bg-slate-900">
      {/* Header + tabs */}
      <div className="px-4 py-3 border-b border-slate-700">
        <h2 className="text-sm font-semibold text-slate-200">Operations</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          {USE_LIVE ? "LIVE - dari backend" : "MOCK - data simulasi"}
        </p>
        <div className="flex gap-1 mt-2">
          {(["ops", "log"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                activeTab === tab
                  ? "bg-slate-700 text-slate-200"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {tab === "ops" ? "Ops" : "Log"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {activeTab === "ops" ? (
          <>
            {selectedNode && <NodeInfoPanel node={selectedNode} />}
            <div className="text-xs text-slate-400 uppercase tracking-wide px-0.5">
              Pending approvals
            </div>
            {ops.length === 0 ? (
              <p className="text-xs text-slate-500 px-0.5">Tidak ada operasi pending.</p>
            ) : (
              ops.map((op) => <OperationCard key={op.id} op={op} />)
            )}
          </>
        ) : (
          <>
            <div className="text-xs text-slate-400 uppercase tracking-wide px-0.5">
              SSE Event Log
            </div>
            <EventLogPanel log={eventLog} />
          </>
        )}
      </div>

      <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500">
        Klik node di graph untuk detail
      </div>
    </aside>
  );
}