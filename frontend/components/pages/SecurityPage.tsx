"use client";
// components/pages/SecurityPage.tsx
// Halaman Security — sesuai design section 7
// FE-1 @nabilfauzandafa
//
// Data live: /operations (via useLiveOps) + SSE event feed.
// Daftar rule & nama adversarial test TIDAK ada endpoint backend —
// itu konfigurasi statis, bukan data runtime. Jika backend menambah
// /security/rules, ganti RULES dengan fetch.

import { useEffect, useState } from "react";
import { useLiveOps } from "@/hooks/useLiveOps";
import {
  clock, conflictCandidates, pct, rollbackStats, securityOverview,
  type ConflictCandidate, type LiveOp, type RollbackStats, type SecurityOverview,
} from "@/lib/derive";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const RULES = [
  { name: "Dangerous operation detection",          description: "Block ops flagged as destructive",      enabled: true },
  { name: "Conflict detection (overlapping resources)", description: "Deny concurrent ops on same target", enabled: true },
  { name: "Reversibility requirement",              description: "Require snapshot before execution",     enabled: true },
  { name: "Unknown operation fail-closed",           description: "Unknown tool_names require approval",   enabled: true },
  { name: "Blast radius classification",            description: "Auto-classify ops by impact scope",     enabled: true },
];

const SEVERITY_STYLES: Record<string, string> = {
  blocked: "text-red-400 bg-red-900/20",
  warning: "text-yellow-400 bg-yellow-900/20",
  ok:      "text-green-400 bg-green-900/20",
  info:    "text-slate-400 bg-slate-800/40",
};

interface SecurityEvent { timestamp: string; event: string; detail: string; severity: keyof typeof SEVERITY_STYLES }

const SEVERITY_BY_EVENT: Record<string, SecurityEvent["severity"]> = {
  operation_rolled_back: "warning",
  operation_failed:      "blocked",
  operation_denied:      "blocked",
  operation_verified:    "ok",
  operation_approved:    "info",
  operation_executing:   "info",
  operation_proposed:    "info",
};

function eventDetail(data: Record<string, unknown>): string {
  if (data.operation_id) {
    return `${String(data.operation_id).slice(0, 12)} ${String(data.tool_name ?? "")}`.trim();
  }
  if (data.current_doc) return `ingest: ${String(data.current_doc)}`;
  return JSON.stringify(data).slice(0, 60);
}

// Live event feed dari SSE — sama dengan event log di OperationsSidebar
function useSecurityEvents(enabled: boolean): SecurityEvent[] {
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(`${BACKEND_URL}/stream`);
    es.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data) as { event: string; data: Record<string, unknown> };
        const severity = SEVERITY_BY_EVENT[p.event];
        if (!severity) return;
        setEvents((prev) => [{
          timestamp: new Date().toLocaleTimeString("id", { hour: "2-digit", minute: "2-digit" }),
          event: p.event,
          detail: eventDetail(p.data),
          severity,
        }, ...prev.slice(0, 49)]);
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, [enabled]);
  return events;
}

function opEvents(ops: readonly LiveOp[]): SecurityEvent[] {
  return ops
    .filter((op) => op.status === "rolled_back" || op.status === "failed" || op.status === "verified" || op.status === "denied")
    .slice(0, 20)
    .map((op) => ({
      timestamp: clock(op.created_at),
      event: `operation_${op.status}`,
      detail: `${op.id.slice(0, 12)} ${op.tool_name}`.trim(),
      severity: SEVERITY_BY_EVENT[`operation_${op.status}`] ?? "info",
    }));
}

const EMPTY_OVERVIEW: SecurityOverview = { total_checks: 0, violations: 0, blocked_ops: 0, verified_ops: 0, is_healthy: true };
const EMPTY_ROLLBACK: RollbackStats = { total: 0, successful: 0, recent: [] };

export default function SecurityPage() {
  const { ops, loading, offline, refresh } = useLiveOps();
  const liveEvents = useSecurityEvents(USE_LIVE);

  const overview  = ops.length > 0 ? securityOverview(ops) : EMPTY_OVERVIEW;
  const rollbacks = ops.length > 0 ? rollbackStats(ops) : EMPTY_ROLLBACK;
  const conflicts: ConflictCandidate[] = conflictCandidates(ops);
  const events = liveEvents.length > 0 ? liveEvents : opEvents(ops);

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Security</h1>
          <p className="text-sm text-slate-400 mt-0.5">Security audit and rule engine (rule-based / heuristic).</p>
        </div>
        <div className="flex items-center gap-2">
          {offline && (
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 font-bold">
              BACKEND OFFLINE
            </span>
          )}
          <span className={`text-[10px] px-2.5 py-1 rounded-full font-bold border ${
            !USE_LIVE ? "bg-slate-600/20 text-slate-400 border-slate-600/30"
              : !offline && overview.is_healthy ? "bg-green-500/20 text-green-400 border-green-500/30"
              : "bg-red-500/20 text-red-400 border-red-500/30"
          }`}>
            &#9679; {!USE_LIVE ? "Env off" : offline ? "Offline" : overview.is_healthy ? "Healthy" : "Warning"}
          </span>
          <button onClick={refresh}
            className="text-[10px] px-2.5 py-1 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors">
            &#8635; Refresh
          </button>
        </div>
      </div>

      {/* Top row: 4 stat cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Checks", value: overview.total_checks, note: null,               color: "text-white" },
          { label: "Violations",   value: overview.violations,    note: `${pct(overview.violations, overview.total_checks)}% of checks`, color: "text-red-400" },
          { label: "Blocked Ops",  value: overview.blocked_ops,   note: `${pct(overview.blocked_ops, overview.total_checks)}% denied`,   color: "text-yellow-400" },
          { label: "Verified",     value: overview.verified_ops,  note: `${pct(overview.verified_ops, overview.total_checks)}% ok`,      color: "text-green-400" },
        ].map((stat) => (
          <div key={stat.label} className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4">
            <div className={`text-2xl font-bold ${stat.color}`}>{loading ? "…" : stat.value}</div>
            <div className="text-xs text-slate-400 mt-1">{stat.label}</div>
            {stat.note && <div className="text-[10px] text-slate-600 mt-0.5">{stat.note}</div>}
          </div>
        ))}
      </div>

      {/* Middle row: Rule Engine + Operation Outcomes + Conflict Checks */}
      <div className="grid grid-cols-3 gap-4">
        {/* Rule Engine — konfigurasi statis */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div>
            <div className="text-sm font-semibold text-white">Rule Engine</div>
            <div className="text-[10px] text-slate-500">Static rules &amp; heuristics (not ML)</div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-400">Policy</span>
            <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 rounded-full px-2 py-0.5 font-semibold">Fail-closed (default)</span>
          </div>
          <div className="space-y-1.5">
            {RULES.map((rule) => (
              <div key={rule.name} className="flex items-start gap-2">
                <span className={`shrink-0 mt-0.5 text-[10px] ${rule.enabled ? "text-green-400" : "text-slate-600"}`}>&#9679;</span>
                <div>
                  <div className="text-[10px] text-slate-300 font-medium">{rule.name}</div>
                  <div className="text-[9px] text-slate-600">{rule.description}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Operation Outcomes — live */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-sm font-semibold text-white">Operation Outcomes</div>
              <div className="text-[10px] text-slate-500">Status akhir dari /operations</div>
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700/60 text-slate-400 font-bold">
              {ops.length} total
            </span>
          </div>
          {ops.length === 0 ? (
            <div className="text-[10px] text-slate-600 py-6 text-center">
              {loading ? "Loading operations..." : !USE_LIVE ? "Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true." : offline ? "Backend offline — no data." : "Belum ada operasi."}
            </div>
          ) : (
            <div className="space-y-1.5">
              {ops.slice(0, 12).map((op) => (
                <div key={op.id} className="flex items-center gap-2">
                  <span className={`text-[10px] shrink-0 ${op.status === "verified" ? "text-green-400" : op.status === "rolled_back" || op.status === "failed" ? "text-red-400" : "text-slate-500"}`}>
                    {op.status === "verified" ? "&#10003;" : op.status === "rolled_back" || op.status === "failed" ? "&#10007;" : "&#9679;"}
                  </span>
                  <span className="text-[10px] text-slate-300 truncate">{op.tool_name}</span>
                  <span className="text-[9px] text-slate-600 ml-auto shrink-0">{op.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Conflict Checks + Rollback Verification */}
        <div className="space-y-3">
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">Conflict Candidates</span>
              {conflicts.length > 0 && (
                <span className="text-[9px] bg-red-500/20 text-red-400 border border-red-500/30 rounded-full w-4 h-4 flex items-center justify-center font-bold">
                  {conflicts.length}
                </span>
              )}
            </div>
            {conflicts.length === 0 ? (
              <div className="text-[10px] text-slate-600">Tidak ada target konflik.</div>
            ) : (
              conflicts.map((c) => (
                <div key={c.target} className="bg-slate-800/40 rounded-lg p-2 text-[10px]">
                  <div className="text-slate-300 font-medium truncate">{c.target}</div>
                  <div className="text-slate-500">{c.opId.slice(0, 12)} vs {c.conflictsWith.map((o) => o.slice(0, 12)).join(", ")}</div>
                </div>
              ))
            )}
          </div>

          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">Rollback Verification</span>
              <span className="text-[9px] bg-green-500/20 text-green-400 border border-green-500/30 rounded-full px-1.5 py-0.5 font-bold">
                {rollbacks.successful}/{rollbacks.total} verified
              </span>
            </div>
            {rollbacks.recent.length === 0 ? (
              <div className="text-[10px] text-slate-600">Belum ada operasi dieksekusi.</div>
            ) : (
              rollbacks.recent.map((r) => (
                <div key={r.opId} className="flex items-center gap-2 text-[10px]">
                  <span className={r.success ? "text-green-400" : "text-red-400"}>{r.success ? "&#10003;" : "&#10007;"}</span>
                  <span className="text-slate-400">{r.timestamp}</span>
                  <span className="text-slate-300 truncate">{r.opId.split("::")[1] ?? r.opId}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Security Event Feed */}
      <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-white">Security Event Feed</span>
          <span className="text-[9px] text-slate-600">
            {USE_LIVE ? "live SSE" : "live SSE (env off — turn on NEXT_PUBLIC_USE_LIVE_SSE)"}
          </span>
        </div>
        {events.length === 0 ? (
          <div className="text-[10px] text-slate-600 py-4 text-center">Belum ada event keamanan.</div>
        ) : (
          <div className="divide-y divide-slate-800/40">
            {events.map((ev, i) => (
              <div key={i} className="flex items-center gap-3 py-2">
                <span className="text-[10px] text-slate-600 font-mono w-12 shrink-0">{ev.timestamp}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded font-semibold shrink-0 ${SEVERITY_STYLES[ev.severity]}`}>
                  {ev.event.replace(/_/g, " ").toUpperCase()}
                </span>
                <span className="text-[10px] text-slate-400 flex-1 truncate">{ev.detail}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
