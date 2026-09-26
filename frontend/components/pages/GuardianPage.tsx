"use client";
// components/pages/GuardianPage.tsx
// Halaman Guardian — sesuai design section 2
// FE-1 @nabilfauzandafa

import { useEffect, useState } from "react";
import type { Operation } from "@/lib/types";
import { stamp } from "@/lib/derive";
import { decideOperation } from "@/lib/operations";
import RiskBadge from "@/components/shared/RiskBadge";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const TIMELINE_STEPS = ["Propose", "Snapshot", "Approve", "Execute", "Verify", "Complete"];

function OperationTimeline({ currentStep }: { currentStep: number }) {
  return (
    <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-white">Operation Timeline</span>
        <button className="text-[10px] text-slate-400 border border-slate-700/60 rounded-lg px-2.5 py-1 hover:text-slate-200 transition-colors">
          View Logs &#8594;
        </button>
      </div>
      <div className="flex items-center gap-0">
        {TIMELINE_STEPS.map((step, i) => {
          const done    = i < currentStep;
          const current = i === currentStep;
          return (
            <div key={step} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold border-2 ${
                  done ? "bg-green-500 border-green-500 text-white" :
                  current ? "bg-blue-500 border-blue-500 text-white" :
                  "bg-slate-800 border-slate-700 text-slate-600"
                }`}>
                  {done ? "&#10003;" : i + 1}
                </div>
                <span className={`text-[9px] font-medium ${
                  done ? "text-green-400" : current ? "text-blue-400" : "text-slate-600"
                }`}>{step}</span>
              </div>
              {i < TIMELINE_STEPS.length - 1 && (
                <div className={`flex-1 h-0.5 mx-1 mb-4 ${
                  i < currentStep ? "bg-green-500" : "bg-slate-800"
                }`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface PendingOpDetailProps { op: Operation; onDecided: (id: string, d: "approved" | "denied") => void; }

function PendingOpDetail({ op, onDecided }: PendingOpDetailProps) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus]   = useState(op.status);
  const [error, setError]     = useState<string | null>(null);
  const params = (() => { try { return JSON.parse(op.params_json); } catch { return {}; } })();

  async function decide(decision: "approved" | "denied") {
    setLoading(true); setError(null);
    try {
      const r = await decideOperation(op.id, decision, BACKEND_URL);
      if (r.status) setStatus(r.status);
      if (r.error) { setError(r.error); return; }
      onDecided(op.id, decision);
    } finally { setLoading(false); }
  }

  const isDone = status !== "pending";
  const currentStep = status === "pending" ? 0 : status === "approved" ? 2 : status === "executing" ? 3 : status === "verified" ? 5 : 5;

  return (
    <div className="space-y-3">
      {/* Pending op card */}
      <div className="bg-red-900/10 border border-red-500/30 rounded-xl p-4 space-y-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-400"></span>
            <span className="text-sm font-semibold text-white">Pending Operation</span>
          </div>
          <RiskBadge level={op.blast_radius} size="md" />
        </div>

        <div>
          <div className="text-sm font-medium text-white">{op.tool_name}</div>
          {params.sql && <div className="text-xs text-slate-400 font-mono mt-1">{params.sql}</div>}
          <div className="text-xs text-slate-500 mt-0.5">This will modify database schema. Requires approval.</div>
        </div>

        <div className="grid grid-cols-4 gap-2 text-xs">
          {[ ["Agent", "Cortex Agent"], ["Target", op.target_node_id ?? "db"], ["Blast Radius", op.blast_radius], ["Time", stamp(op.created_at)] ]
            .map(([k, v]) => (
              <div key={k}>
                <div className="text-slate-500">{k}</div>
                <div className="text-slate-300 font-medium truncate">{v}</div>
              </div>
            ))}
        </div>

        {/* Reversibility Plan */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-slate-800/40 rounded-lg p-3 space-y-1.5">
            <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Reversibility Plan</div>
            {["Create SQLite snapshot (auto)", "Run migration script", "Verify database integrity", "Rollback on failure (restore snapshot)"].map((step, i) => (
              <div key={i} className="flex items-start gap-1.5 text-[10px] text-slate-300">
                <span className="text-green-400 shrink-0">&#10003;</span>
                <span>{step}</span>
              </div>
            ))}
          </div>
          <div className="bg-slate-800/40 rounded-lg p-3 space-y-1.5">
            <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Conflict Detection</div>
            {op.conflicts && op.conflicts.length > 0 ? (
              <div className="text-[10px] text-red-400 bg-red-900/20 rounded p-2">
                &#9888; Overlapping resource detected!<br />
                Another op: db/migration<br />
                <span className="text-slate-500">(6 min ago)</span>
              </div>
            ) : (
              <div className="text-[10px] text-green-400">&#10003; No conflicts detected</div>
            )}
          </div>
        </div>

        {/* Automation + Approval Gate */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-slate-800/40 rounded-lg p-3 space-y-1.5">
            <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Automation</div>
            {[["SQLite snapshot", true],["Verification checks", true],["Rollback plan", true]].map(([label, ready]) => (
              <div key={String(label)} className="flex items-center justify-between text-[10px]">
                <span className="text-slate-300">{String(label)}</span>
                <span className={ready ? "text-green-400" : "text-red-400"}>{ready ? "Ready" : "Not ready"}</span>
              </div>
            ))}
          </div>
          <div className="bg-slate-800/40 rounded-lg p-3 space-y-1.5">
            <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Approval Gate</div>
            <div className="text-[10px] text-slate-300">Requires human approval</div>
            <div className="text-[10px] text-slate-500">(due to high risk + conflict)</div>
          </div>
        </div>

        {error && <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-3 py-2">{error}</div>}

        {!isDone ? (
          <div className="flex gap-2">
            <button onClick={() => decide("approved")} disabled={loading}
              className="flex-1 py-2.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-bold disabled:opacity-50 transition-colors">
              {loading ? "…" : "Approve"}
            </button>
            <button onClick={() => decide("denied")} disabled={loading}
              className="flex-1 py-2.5 rounded-lg bg-red-700/80 hover:bg-red-600 text-white text-sm font-bold disabled:opacity-50 transition-colors">
              {loading ? "…" : "Deny"}
            </button>
          </div>
        ) : (
          <div className="text-xs text-center py-2 rounded-lg bg-slate-700/50 text-slate-400 font-semibold">{status.toUpperCase()}</div>
        )}
      </div>

      {/* Timeline */}
      <OperationTimeline currentStep={currentStep} />
    </div>
  );
}

export default function GuardianPage({ ops, onOpDecided }: { ops: Operation[]; onOpDecided: (id: string, d: "approved" | "denied") => void }) {
  const pending = ops.filter((op) => op.status === "pending");

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <h1 className="text-xl font-bold text-white">Guardian</h1>
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-green-500/20 text-green-400 border border-green-500/30 font-bold">&#9679; ACTIVE</span>
          </div>
          <p className="text-sm text-slate-400">Protecting risky changes &nbsp;&bull;&nbsp; Reversible &nbsp;&bull;&nbsp; Conflict-aware</p>
        </div>
      </div>

      {pending.length === 0 ? (
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-10 text-center text-slate-500 text-sm">
          No pending operations requiring approval.
        </div>
      ) : (
        <div className="space-y-6">
          {pending.map((op) => (
            <PendingOpDetail key={op.id} op={op} onDecided={onOpDecided} />
          ))}
        </div>
      )}
    </div>
  );
}
