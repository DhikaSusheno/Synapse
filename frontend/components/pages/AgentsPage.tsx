"use client";
// components/pages/AgentsPage.tsx
// Halaman Agents — sesuai design section 4
// FE-1 @nabilfauzandafa

import { useEffect, useRef, useState } from "react";
import {
  MOCK_AGENT_STATS, MOCK_CURRENT_TASKS, MOCK_SSE_LOG,
  MOCK_RECENT_ACTIONS, MOCK_CONFLICTS, MOCK_ACTIVITY_DATA,
  type SSELogEntry,
} from "@/lib/mockAgents";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const AGENT_ICON: Record<string, string> = {
  guardian: "&#9672;",
  cortex:   "&#x1F9E0;",
  review:   "&#9733;",
};

const AGENT_DOT: Record<string, string> = {
  guardian: "bg-blue-400",
  cortex:   "bg-purple-400",
  review:   "bg-slate-400",
};

function useLiveSSELog(): SSELogEntry[] {
  const [log, setLog] = useState<SSELogEntry[]>(USE_LIVE ? [] : MOCK_SSE_LOG);
  useEffect(() => {
    if (!USE_LIVE) return;
    const es = new EventSource(`${BACKEND_URL}/stream`);
    es.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data);
        if (p.event === "heartbeat" || p.event === "connected") return;
        const agent = p.data.agent ?? (p.event.startsWith("operation") ? "Guardian" : "Cortex");
        setLog((prev) => [{
          ts: new Date().toLocaleTimeString("id", { hour: "2-digit", minute: "2-digit" }),
          agent, event: p.event,
          message: `${agent}: ${p.event.replace(/_/g, " ")}`,
        }, ...prev.slice(0, 19)]);
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);
  return log;
}

// Mini line chart for agent activity
function ActivityChart() {
  const { labels, guardian, cortex, review } = MOCK_ACTIVITY_DATA;
  const maxVal = 8;
  const W = 320; const H = 80; const PAD = 8;
  const xStep = (W - PAD * 2) / (labels.length - 1);

  function toPath(data: number[]) {
    return data.map((v, i) => {
      const x = PAD + i * xStep;
      const y = H - PAD - (v / maxVal) * (H - PAD * 2);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    }).join(" ");
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20">
      <path d={toPath(guardian)} fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinejoin="round" />
      <path d={toPath(cortex)}   fill="none" stroke="#a855f7" strokeWidth="1.5" strokeLinejoin="round" />
      <path d={toPath(review)}   fill="none" stroke="#64748b" strokeWidth="1.5" strokeLinejoin="round" />
      {labels.map((label, i) => (
        <text key={label} x={PAD + i * xStep} y={H - 1} textAnchor="middle" fontSize="6" fill="#475569">{label}</text>
      ))}
    </svg>
  );
}

export default function AgentsPage() {
  const sseLog = useLiveSSELog();

  return (
    <div className="flex-1 overflow-y-auto bg-[#080d14] p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Agents</h1>
          <p className="text-sm text-slate-400 mt-0.5">3 agents &mdash; Coordinated AI workforce</p>
        </div>
        <span className="text-[10px] px-2.5 py-1 rounded-full bg-green-500/20 text-green-400 border border-green-500/30 font-bold">&#9679; Running</span>
      </div>

      {/* 3 Agent Cards */}
      <div className="grid grid-cols-3 gap-4">
        {MOCK_AGENT_STATS.map((agent) => (
          <div key={agent.name} className={`bg-[#0d1117] rounded-xl border ${agent.borderColor} p-4 space-y-3`}>
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <span className={`w-8 h-8 rounded-lg ${agent.bgColor} border ${agent.borderColor} flex items-center justify-center text-sm`}
                  dangerouslySetInnerHTML={{ __html: AGENT_ICON[agent.name] }} />
                <div>
                  <div className={`text-sm font-semibold ${agent.color}`}>{agent.label}</div>
                  <div className="text-[10px] text-slate-500">{agent.subtitle}</div>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-center">
                <div className="text-xl font-bold text-white">{agent.tasks}</div>
                <div className="text-[10px] text-slate-500">Tasks</div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400"></span>
                <span className="text-xs text-green-400">Healthy</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Bottom 2-col */}
      <div className="grid grid-cols-2 gap-4">
        {/* Current Tasks */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="text-sm font-semibold text-white">Current Tasks</div>
          <div className="space-y-2">
            {MOCK_CURRENT_TASKS.map((task) => (
              <div key={task.id} className="flex items-start gap-2.5">
                <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${AGENT_DOT[task.agent] ?? "bg-slate-400"}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium capitalize ${
                      task.agent === "guardian" ? "text-blue-400" : task.agent === "cortex" ? "text-purple-400" : "text-slate-300"
                    }`}>{task.agent}</span>
                    <span className="text-[10px] text-slate-500 font-mono">{task.timestamp}</span>
                  </div>
                  <div className="text-xs text-slate-300 truncate">{task.description}</div>
                </div>
                {task.status === "running" && (
                  <span className="text-[9px] bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-full px-1.5 py-0.5 shrink-0">running</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* SSE Event Stream */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">SSE Event Stream</span>
            <span className="flex items-center gap-1 text-[10px] text-green-400">
              <span className="w-1 h-1 rounded-full bg-green-400"></span>
              {USE_LIVE ? "Live" : "Mock"}
            </span>
          </div>
          <div className="space-y-1.5 max-h-36 overflow-y-auto">
            {sseLog.map((entry, i) => (
              <div key={i} className="flex gap-2 text-[10px]">
                <span className="text-slate-600 font-mono shrink-0">{entry.ts}</span>
                <span className={`shrink-0 font-medium ${
                  entry.agent.toLowerCase() === "guardian" ? "text-blue-400" :
                  entry.agent.toLowerCase() === "cortex"   ? "text-purple-400" : "text-slate-300"
                }`}>{entry.agent}</span>
                <span className="text-slate-400 truncate">{entry.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Agent Activity Chart + Conflicts + Recent Actions */}
      <div className="grid grid-cols-3 gap-4">
        {/* Activity Chart */}
        <div className="col-span-2 bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
          <div className="text-sm font-semibold text-white">Agent Activity</div>
          <ActivityChart />
          <div className="flex gap-4">
            {[["Guardian", "bg-blue-400", "34%"],["Cortex", "bg-purple-400", "42%"],["Review", "bg-slate-400", "24%"]].map(([name, dot, pct]) => (
              <div key={name} className="flex items-center gap-1.5 text-[10px]">
                <span className={`w-2 h-2 rounded-full ${dot}`}></span>
                <span className="text-slate-400">{name}</span>
                <span className="text-slate-300 font-medium">{pct}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Conflicts + Recent Actions */}
        <div className="space-y-3">
          {/* Active Conflicts */}
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-white">Active Conflicts</span>
              {MOCK_CONFLICTS.length > 0 && (
                <span className="text-[9px] bg-red-500/20 text-red-400 border border-red-500/30 rounded-full w-4 h-4 flex items-center justify-center font-bold">
                  {MOCK_CONFLICTS.length}
                </span>
              )}
            </div>
            {MOCK_CONFLICTS.map((c, i) => (
              <div key={i} className="bg-red-900/10 border border-red-500/20 rounded-lg p-2">
                <div className="text-[10px] text-red-400 font-medium">{c.opId.split("::")[1]}</div>
                <div className="text-[10px] text-slate-500">{c.conflictWith}</div>
                <button className="text-[9px] text-blue-400 mt-1">View &#8594;</button>
              </div>
            ))}
          </div>

          {/* Recent Actions */}
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-3 space-y-1.5">
            <div className="text-xs font-semibold text-white mb-1">Recent Actions</div>
            {MOCK_RECENT_ACTIONS.map((action, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px]">
                <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                  action.agent === "guardian" ? "bg-blue-400" : action.agent === "cortex" ? "bg-purple-400" : "bg-slate-400"
                }`} />
                <span className={`capitalize ${
                  action.agent === "guardian" ? "text-blue-400" : action.agent === "cortex" ? "text-purple-400" : "text-slate-300"
                }`}>{action.agent}</span>
                <span className="text-slate-400 flex-1 truncate">{action.action}</span>
                <span className="text-slate-600 shrink-0">{action.relativeTime}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
