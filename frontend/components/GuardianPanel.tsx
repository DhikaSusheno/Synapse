"use client";

// components/GuardianPanel.tsx
// Right panel — Guardian + Cortex Insight sesuai prototype
// FE-1 @nabilfauzandafa

import { useState } from "react";
import type { Operation, GraphNode } from "@/lib/types";
import { stamp } from "@/lib/derive";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

interface Props {
  pendingOps: Operation[];
  onOpDecided?: (opId: string, decision: "approved" | "denied") => void;
}

function BlastBadge({ level }: { level: Operation["blast_radius"] }) {
  const styles: Record<string, string> = {
    high:    "bg-red-500/20 text-red-400 border border-red-500/30",
    medium:  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
    low:     "bg-green-500/20 text-green-400 border border-green-500/30",
    unknown: "bg-slate-700 text-slate-400 border border-slate-600",
  };
  const labels: Record<string, string> = {
    high: "High Risk", medium: "Medium Risk", low: "Low Risk", unknown: "Unknown"
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${styles[level]}`}>
      {labels[level] ?? level}
    </span>
  );
}

function PendingApprovalCard({ op, onDecided }: { op: Operation; onDecided?: (id: string, d: "approved" | "denied") => void }) {
  const [loading, setLoading] = useState(false);
  const [localStatus, setLocalStatus] = useState<GraphNode["status"]>(op.status);
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

      const approveData = (await approveRes?.json().catch(() => null)) as
        { status?: string; new_status?: string; detail?: string } | null;

      if (!approveRes || !approveRes.ok) {
        setErrorMsg(approveData?.detail ?? "Approve ditolak backend.");
        return;
      }

      setLocalStatus(
        ((approveData?.status ?? approveData?.new_status) as GraphNode["status"]) ??
        (decision === "approved" ? "approved" : "denied")
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
        } else {
          setLocalStatus("failed");
          setErrorMsg("Execute failed — check backend log.");
        }
      }
      onDecided?.(op.id, decision);
    } finally {
      setLoading(false);
    }
  }

  const params = (() => { try { return JSON.parse(op.params_json); } catch { return {}; } })();
  const isDone = localStatus !== "pending";

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3.5 space-y-2.5">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
          </span>
          <span className="text-xs font-semibold text-white">Pending Approval</span>
        </div>
        <BlastBadge level={op.blast_radius} />
      </div>

      {/* Op title */}
      <div>
        <div className="text-sm font-medium text-white">{op.tool_name}</div>
        {params.sql && (
          <div className="text-xs text-slate-400 mt-0.5 font-mono truncate">{params.sql}</div>
        )}
        {!params.sql && op.target_node_id && (
          <div className="text-xs text-slate-400 mt-0.5">Target: {op.target_node_id}</div>
        )}
      </div>

      {/* Meta table */}
      <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
        <span className="text-slate-500">Agent</span>
        <span className="text-slate-300">Cortex Agent</span>
        <span className="text-slate-500">Operation</span>
        <span className="text-slate-300 font-mono truncate">{op.tool_name.split(".")[1] ?? op.tool_name}</span>
        <span className="text-slate-500">Risk Score</span>
        <span className="text-red-400 font-semibold">
          {op.blast_radius === "high" ? "8.7 / 10" : op.blast_radius === "medium" ? "5.0 / 10" : "2.1 / 10"}
        </span>
        <span className="text-slate-500">Time</span>
        <span className="text-slate-300">{stamp(op.created_at)}</span>
      </div>

      {op.conflicts && op.conflicts.length > 0 && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-2.5 py-1.5 flex items-center gap-1.5">
          <span>&#9888;</span>
          <span>Conflicts with: {op.conflicts.join(", ")}</span>
        </div>
      )}

      {errorMsg && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded-lg px-2.5 py-1.5">{errorMsg}</div>
      )}

      {isDone ? (
        <div className={`text-xs text-center py-1.5 rounded-lg font-semibold ${
          localStatus === "verified" || localStatus === "approved" ? "bg-green-900/30 text-green-400" :
          "bg-slate-700/50 text-slate-400"
        }`}>
          {localStatus.toUpperCase()}
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => decide("approved")}
            disabled={loading}
            className="flex-1 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-bold transition-colors disabled:opacity-50"
          >
            {loading ? "..." : "Approve"}
          </button>
          <button
            onClick={() => decide("denied")}
            disabled={loading}
            className="flex-1 py-2 rounded-lg bg-red-700/80 hover:bg-red-600 text-white text-xs font-bold transition-colors disabled:opacity-50"
          >
            {loading ? "..." : "Deny"}
          </button>
        </div>
      )}
    </div>
  );
}

function CortexInsightPanel({ pendingOps }: { pendingOps: Operation[] }) {
  const highRisk = pendingOps.filter((op) => op.blast_radius === "high").length;
  const conflicts = pendingOps.filter((op) => (op.conflicts?.length ?? 0) > 0).length;
  const insights = [
    `${pendingOps.length} operasi menunggu approval`,
    `${highRisk} berisiko high blast radius`,
    `${conflicts} operasi konflik dengan operasi lain`,
    "Guardian fail-closed: verifikasi gagal = rollback",
  ];
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3.5 space-y-2.5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-violet-500/20 border border-violet-500/40 flex items-center justify-center text-[10px]">&#x1F9E0;</span>
          <span className="text-xs font-semibold text-white">Cortex Insight</span>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400 border border-violet-500/30 font-semibold">REVIEW</span>
      </div>

      <div className="text-xs font-medium text-slate-300">Codebase Understanding</div>

      <div className="space-y-1.5">
        {insights.map((text) => (
          <div key={text} className="flex items-start gap-2 text-xs">
            <span className="text-green-400 mt-0.5 shrink-0">&#9679;</span>
            <span className="text-slate-300">{text}</span>
          </div>
        ))}
      </div>

      <button className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-slate-700/60 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors">
        View Detailed Analysis
        <span>&#8594;</span>
      </button>
    </div>
  );
}

export default function GuardianPanel({ pendingOps, onOpDecided }: Props) {
  const pendingList = pendingOps.filter((op) => op.status === "pending");

  return (
    <aside className="w-72 shrink-0 flex flex-col bg-[#0d1117] border-l border-slate-800/60 overflow-hidden">
      {/* Guardian header — fixed */}
      <div className="p-3 shrink-0">
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3.5">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-lg bg-green-500/20 border border-green-500/40 flex items-center justify-center text-xs">&#9672;</span>
              <span className="text-sm font-semibold text-white">Guardian</span>
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30 font-bold tracking-wide">PROTECTED</span>
          </div>
          <div className="text-[11px] text-slate-400">
            Monitoring operations &nbsp;&#183;&nbsp; Detecting risky changes
          </div>
          {pendingList.length > 0 && (
            <div className="mt-1.5 text-[10px] text-yellow-400 font-semibold">
              {pendingList.length} pending approval{pendingList.length > 1 ? "s" : ""}
            </div>
          )}
        </div>
      </div>

      {/* Scrollable pending list */}
      <div className="flex-1 overflow-y-auto px-3 space-y-3 pb-3">
        {pendingList.length === 0 ? (
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3.5 text-xs text-slate-500 text-center">
            No pending approvals
          </div>
        ) : (
          pendingList.map((op) => (
            <PendingApprovalCard key={op.id} op={op} onDecided={onOpDecided} />
          ))
        )}

        {/* Cortex insight */}
        <CortexInsightPanel pendingOps={pendingOps} />
      </div>
    </aside>
  );
}
