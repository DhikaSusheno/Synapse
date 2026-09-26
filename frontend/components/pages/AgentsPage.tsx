"use client";
// components/pages/AgentsPage.tsx
// Halaman Agents — sesuai design section 4
// FE-1 @nabilfauzandafa
//
// Data live: /operations (via useLiveOps) + /graph/summary + SSE /stream.
// Task count per agent diturunkan dari data nyata, bukan mock.

import { useEffect, useState } from "react";
import { useLiveOps } from "@/hooks/useLiveOps";
import {
  bucketActivity, clock, conflictCandidates, isOpen, opSummary, pct, relativeTime,
  type ConflictCandidate, type LiveOp,
} from "@/lib/derive";
import type { SSELogEntry } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const AGENT_STYLE: Record<string, { label: string; subtitle: string; color: string; bg: string; border: string; dot: string }> = {
  guardian: { label: "Guardian", subtitle: "Protection & Safety",      color: "text-blue-400",   bg: "bg-blue-500/10",   border: "border-blue-500/30",   dot: "bg-blue-400" },
  cortex:   { label: "Cortex",   subtitle: "Understanding & Review",  color: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/30", dot: "bg-purple-400" },
  review:   { label: "Review",   subtitle: "Code Review & Analysis",  color: "text-slate-300",  bg: "bg-slate-600/10",  border: "border-slate-600/30",  dot: "bg-slate-400" },
};

const AGENT_ICON: Record<string, string> = {
  guardian: "&#9672;",
  cortex:   "&#x1F9E0;",
  review:   "&#9733;",
};

interface GraphSummary {
  total_nodes: number;
  total_edges: number;
  nodes_by_type: Record<string, number>;
  edges_by_relationship: Record<string, number>;
}

function useGraphSummary(enabled: boolean): GraphSummary | null {
  const [summary, setSummary] = useState<GraphSummary | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = () =>
      fetch(`${BACKEND_URL}/graph/summary`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (!cancelled && d) setSummary(d as GraphSummary); })
        .catch(() => null);
    load();
    const t = setInterval(load, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, [enabled]);
  return summary;
}

function useLiveSSELog(): SSELogEntry[] {
  const [log, setLog] = useState<SSELogEntry[]>([]);
  useEffect(() => {
    if (!USE_LIVE) return;
    const es = new EventSource(`${BACKEND_URL}/stream`);
    es.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data) as { event: string; data: Record<string, unknown> };
        if (p.event === "heartbeat" || p.event === "connected") return;
        const agent = p.event.startsWith("operation") ? "Guardian" : "Cortex";
        setLog((prev) => [{
          ts: new Date().toLocaleTimeString("id", { hour: "2-digit", minute: "2-digit" }),
          agent,
          event: p.event,
          message: p.event.replace(/_/g, " "),
        }, ...prev.slice(0, 19)]);
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);
  return log;
}

function ActivityChart({ ops }: { ops: readonly LiveOp[] }) {
  const buckets = bucketActivity(ops);
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <div className="space-y-1">
      <div className="flex items-end gap-1 h-20">
        {buckets.map((b) => (
          <div key={b.label} className="flex-1 flex flex-col items-center justify-end gap-1 group">
            <span className="text-[9px] text-slate-500 opacity-0 group-hover:opacity-100">{b.count}</span>
            <div
              className="w-full rounded-t bg-purple-500/70 min-h-[2px]"
              style={{ height: `${Math.max(2, (b.count / max) * 100)}%` }}
              title={`${b.label}: ${b.count} operasi`}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-1">
        {buckets.map((b) => (
          <span key={b.label} className="flex-1 text-center text-[9px] text-slate-600 truncate">{b.label}</span>
        ))}
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { ops, loading, offline, refresh } = useLiveOps();
  const summary = useGraphSummary(USE_LIVE);
  const sseLog = useLiveSSELog();

  const openOps = ops.filter((op) => isOpen(op.status));
  const conflicts: ConflictCandidate[] = conflictCandidates(ops);

  const agentTasks: Record<string, number> = {
    guardian: openOps.length,
    cortex:   summary?.nodes_by_type.symbol ?? 0,
    review:   summary?.nodes_by_type.file ?? 0,
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Agents</h1>
          <p className="text-sm text-slate-400 mt-0.5">3 agents &mdash; Coordinated AI workforce</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] px-2.5 py-1 rounded-full font-bold border ${
            !USE_LIVE ? "bg-slate-600/20 text-slate-400 border-slate-600/30"
              : offline ? "bg-red-500/20 text-red-400 border-red-500/30"
              : "bg-green-500/20 text-green-400 border-green-500/30"
          }`}>
            &#9679; {!USE_LIVE ? "Env off" : offline ? "Offline" : "Running"}
          </span>
          <button onClick={refresh}
            className="text-[10px] px-2.5 py-1 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors">
            &#8635; Refresh
          </button>
        </div>
      </div>

      {/* 3 Agent Cards */}
      <div className="grid grid-cols-3 gap-4">
        {(Object.keys(AGENT_STYLE) as (keyof typeof AGENT_STYLE)[]).map((name) => {
          const s = AGENT_STYLE[name];
          return (
            <div key={name} className={`bg-[#0d1117] rounded-xl border ${s.border} p-4 space-y-3`}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-8 h-8 rounded-lg ${s.bg} border ${s.border} flex items-center justify-center text-sm`}
                    dangerouslySetInnerHTML={{ __html: AGENT_ICON[name] }} />
                  <div>
                    <div className={`text-sm font-semibold ${s.color}`}>{s.label}</div>
                    <div className="text-[10px] text-slate-500">{s.subtitle}</div>
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-center">
                  <div className="text-xl font-bold text-white">{loading ? "…" : agentTasks[name]}</div>
                  <div className="text-[10px] text-slate-500">
                    {name === "guardian" ? "Open ops" : name === "cortex" ? "Symbols" : "Files"}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${!USE_LIVE ? "bg-slate-600" : offline ? "bg-slate-600" : "bg-green-400"}`}></span>
                  <span className={`text-xs ${!USE_LIVE || offline ? "text-slate-600" : "text-green-400"}`}>
                    {!USE_LIVE ? "No data" : offline ? "Unknown" : "Healthy"}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Bottom 2-col */}
      <div className="grid grid-cols-2 gap-4">
        {/* Current Tasks — operasi yang masih jalan */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Current Tasks</span>
            <span className="text-[9px] bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-full px-1.5 py-0.5 font-bold">
              {openOps.length} open
            </span>
          </div>
          {openOps.length === 0 ? (
            <div className="text-[10px] text-slate-600 py-4 text-center">
              {loading ? "Loading operations..." : !USE_LIVE ? "Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true." : offline ? "Backend offline — no data." : "Tidak ada operasi terbuka."}
            </div>
          ) : (
            <div className="space-y-2">
              {openOps.slice(0, 8).map((op) => (
                <div key={op.id} className="flex items-start gap-2.5">
                  <span className="mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 bg-blue-400" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-blue-400">Guardian</span>
                      <span className="text-[10px] text-slate-500 font-mono">
                        {clock(op.created_at)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-300 truncate">{opSummary(op)}</div>
                  </div>
                  {op.status === "executing" && (
                    <span className="text-[9px] bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded-full px-1.5 py-0.5 shrink-0">executing</span>
                  )}
                  {op.status === "pending" && (
                    <span className="text-[9px] bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded-full px-1.5 py-0.5 shrink-0">pending</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* SSE Event Stream */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">SSE Event Stream</span>
            <span className="flex items-center gap-1 text-[10px] text-green-400">
              <span className="w-1 h-1 rounded-full bg-green-400"></span>
              {USE_LIVE ? "Live" : "Env off"}
            </span>
          </div>
          {sseLog.length === 0 ? (
            <div className="text-[10px] text-slate-600 py-4 text-center">Menunggu event dari backend.</div>
          ) : (
            <div className="space-y-1.5 max-h-36 overflow-y-auto">
              {sseLog.map((entry, i) => (
                <div key={i} className="flex gap-2 text-[10px]">
                  <span className="text-slate-600 font-mono shrink-0">{entry.ts}</span>
                  <span className={`shrink-0 font-medium ${
                    entry.agent === "Guardian" ? "text-blue-400" : "text-purple-400"
                  }`}>{entry.agent}</span>
                  <span className="text-slate-400 truncate">{entry.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Agent Activity Chart + Conflicts + Recent Actions */}
      <div className="grid grid-cols-3 gap-4">
        {/* Activity Chart — histogram operasi 5 jam terakhir */}
        <div className="col-span-2 bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Agent Activity</span>
            <span className="text-[10px] text-slate-500">
              {ops.length} operasi &middot; peak {Math.max(0, ...bucketActivity(ops).map((b) => b.count))}
            </span>
          </div>
          <ActivityChart ops={ops} />
        </div>

        {/* Conflicts + Recent Actions */}
        <div className="space-y-3">
          {/* Conflict Candidates */}
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-white">Conflict Candidates</span>
              {conflicts.length > 0 && (
                <span className="text-[9px] bg-red-500/20 text-red-400 border border-red-500/30 rounded-full w-4 h-4 flex items-center justify-center font-bold">
                  {conflicts.length}
                </span>
              )}
            </div>
            {conflicts.length === 0 ? (
              <div className="text-[10px] text-slate-600">Tidak ada target konflik.</div>
            ) : (
              conflicts.slice(0, 4).map((c) => (
                <div key={c.target} className="bg-red-900/10 border border-red-500/20 rounded-lg p-2">
                  <div className="text-[10px] text-red-400 font-medium truncate">{c.opId.split("::")[1] ?? c.opId}</div>
                  <div className="text-[10px] text-slate-500 truncate">
                    {c.conflictsWith.length} op lain pada {c.target.split("::").pop()}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Recent Actions */}
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-3 space-y-1.5">
            <div className="text-xs font-semibold text-white mb-1">Recent Actions</div>
            {ops.length === 0 ? (
              <div className="text-[10px] text-slate-600">Belum ada aksi.</div>
            ) : (
              ops.slice(0, 5).map((op) => (
                <div key={op.id} className="flex items-center gap-2 text-[10px]">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-blue-400" />
                  <span className="text-blue-400 shrink-0">Guardian</span>
                  <span className="text-slate-400 flex-1 truncate">{op.tool_name}</span>
                  <span className="text-slate-600 shrink-0">{relativeTime(op.created_at)}</span>
                </div>
              ))
            )}
            {ops.length > 0 && (
              <div className="text-[9px] text-slate-600 pt-1">
                {pct(ops.filter((o) => o.status === "verified").length, ops.length)}% verified
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
