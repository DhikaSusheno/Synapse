"use client";

// components/OverviewMain.tsx
// Konten halaman Overview — Code Graph panel + Operation Timeline + Risk & Activity + Feature Cards
// FE-1 @nabilfauzandafa

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";
import type { GraphNode, Operation } from "@/lib/types";

const SynapseGraph = dynamic(() => import("@/components/SynapseGraph"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      Initializing graph engine...
    </div>
  ),
});

interface Props {
  onNodeClick: (node: GraphNode) => void;
  onNodeCount: (nodes: number, links: number) => void;
  nodeCount: number;
  edgeCount: number;
  operations: Operation[];
}

// ---- Operation Timeline ----
const BADGE_STYLES: Record<string, string> = {
  PROPOSE:  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  EXECUTE:  "bg-blue-500/20 text-blue-400 border border-blue-500/30",
  ANALYZE:  "bg-slate-600/40 text-slate-300 border border-slate-600/40",
  REVIEW:   "bg-purple-500/20 text-purple-400 border border-purple-500/30",
  ROLLBACK: "bg-red-500/20 text-red-400 border border-red-500/30",
};

const RISK_STYLES: Record<string, string> = {
  "High Risk":    "bg-red-500/20 text-red-400 border border-red-500/30",
  "Medium Risk":  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  "Success":      "bg-green-500/20 text-green-400 border border-green-500/30",
  "Info":         "bg-slate-600/40 text-slate-400 border border-slate-600/40",
};

const TIMELINE_DOT: Record<string, string> = {
  PROPOSE:  "bg-red-400",
  EXECUTE:  "bg-green-400",
  ANALYZE:  "bg-blue-400",
  ROLLBACK: "bg-orange-400",
  REVIEW:   "bg-purple-400",
};

interface TimelineEvent {
  time: string;
  type: keyof typeof BADGE_STYLES;
  agent: string;
  description: string;
  risk: keyof typeof RISK_STYLES;
}

// Mock timeline matching prototype
const MOCK_TIMELINE_EVENTS: TimelineEvent[] = [
  { time: "21 Sep 2026 08:42", type: "PROPOSE",  agent: "Cortex Agent", description: "Modify database.py (write operation)", risk: "High Risk" },
  { time: "21 Sep 2026 08:41", type: "EXECUTE",  agent: "Guardian",     description: "Rollback executed (operation denied)",  risk: "Success" },
  { time: "21 Sep 2026 08:37", type: "PROPOSE",  agent: "Cortex Agent", description: "Update graph.py (refactor)",           risk: "Medium Risk" },
  { time: "21 Sep 2026 08:35", type: "EXECUTE",  agent: "Guardian",     description: "Change applied successfully",           risk: "Success" },
  { time: "21 Sep 2026 08:20", type: "ANALYZE",  agent: "Cortex Agent", description: "Repository analysis completed",         risk: "Info" },
];

function OperationTimeline({ ops }: { ops: Operation[] }) {
  // Use live ops if available, else mock
  const events: TimelineEvent[] = ops.length > 0
    ? ops.slice(0, 5).map((op) => ({
        time: new Date(op.created_at).toLocaleString(),
        type: "PROPOSE" as const,
        agent: "Agent",
        description: op.tool_name,
        risk: op.blast_radius === "high" ? "High Risk" : op.blast_radius === "medium" ? "Medium Risk" : "Info",
      }))
    : MOCK_TIMELINE_EVENTS;

  return (
    <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">&#9202;</span>
            <span className="text-sm font-semibold text-white">Operation Timeline</span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Real-time operation flow and history</div>
        </div>
        <select className="text-xs bg-slate-800 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-slate-300 outline-none">
          <option>All Operations</option>
          <option>Pending</option>
          <option>Executed</option>
        </select>
      </div>

      {/* Events */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/40">
        {events.map((ev, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-800/30 transition-colors">
            {/* Dot */}
            <span className={`w-2 h-2 rounded-full shrink-0 ${TIMELINE_DOT[ev.type] ?? "bg-slate-500"}`} />
            {/* Time */}
            <span className="text-[10px] text-slate-500 font-mono w-32 shrink-0">{ev.time}</span>
            {/* Type badge */}
            <span className={`text-[10px] px-2 py-0.5 rounded font-bold shrink-0 ${BADGE_STYLES[ev.type]}`}>
              {ev.type}
            </span>
            {/* Agent + description */}
            <div className="flex-1 min-w-0">
              <span className="text-xs text-slate-400">{ev.agent}</span>
              <div className="text-xs text-slate-200 truncate">{ev.description}</div>
            </div>
            {/* Risk */}
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold shrink-0 ${RISK_STYLES[ev.risk] ?? RISK_STYLES.Info}`}>
              {ev.risk}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Risk & Activity ----
// SVG sparkline — simple polyline chart
function SparklineChart() {
  // Approximate the wave shape from prototype
  const points = [
    [0, 60], [40, 55], [80, 50], [120, 45], [160, 55], [200, 65],
    [240, 60], [280, 30], [320, 15], [340, 5], [360, 25], [380, 55],
    [400, 65], [440, 60], [480, 55], [520, 60], [560, 58], [600, 60],
  ];
  const pts = points.map(([x, y]) => `${x},${y}`).join(" ");
  const fillPts = `0,80 ${pts} 600,80`;

  return (
    <div className="relative">
      <svg viewBox="0 0 600 90" className="w-full h-24" preserveAspectRatio="none">
        <defs>
          <linearGradient id="riskGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon points={fillPts} fill="url(#riskGrad)" />
        <polyline points={pts} fill="none" stroke="#22c55e" strokeWidth="2" strokeLinejoin="round" />
        {/* Peak marker */}
        <circle cx="340" cy="5" r="4" fill="#ef4444" />
        <text x="345" y="5" fontSize="9" fill="#ef4444" dominantBaseline="middle">8.7</text>
      </svg>
      {/* X-axis labels */}
      <div className="flex justify-between text-[10px] text-slate-600 mt-1 px-1">
        {["00:00", "06:00", "12:00", "18:00", "24:00"].map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </div>
  );
}

// Simple donut chart for agent activity
function DonutChart() {
  // Guardian 34%, Cortex 42%, Review 24%
  const r = 40;
  const cx = 55;
  const cy = 55;
  const circumference = 2 * Math.PI * r;
  const guardian = 0.34 * circumference;
  const cortex = 0.42 * circumference;
  // const review = 0.24 * circumference;
  const guardianOffset = 0;
  const cortexOffset = guardian;
  const reviewOffset = guardian + cortex;

  return (
    <svg width="110" height="110" viewBox="0 0 110 110">
      {/* Review (bg) */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#334155" strokeWidth="18"
        strokeDasharray={`${circumference}`} />
      {/* Guardian */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#3b82f6" strokeWidth="18"
        strokeDasharray={`${guardian} ${circumference - guardian}`}
        strokeDashoffset={-guardianOffset}
        transform={`rotate(-90 ${cx} ${cy})`} />
      {/* Cortex */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#a855f7" strokeWidth="18"
        strokeDasharray={`${cortex} ${circumference - cortex}`}
        strokeDashoffset={-cortexOffset}
        transform={`rotate(-90 ${cx} ${cy})`} />
      {/* Review */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#475569" strokeWidth="18"
        strokeDasharray={`${0.24 * circumference} ${circumference - 0.24 * circumference}`}
        strokeDashoffset={-reviewOffset}
        transform={`rotate(-90 ${cx} ${cy})`} />
      {/* Center text */}
      <text x={cx} y={cy - 6} textAnchor="middle" fontSize="18" fontWeight="bold" fill="white">3</text>
      <text x={cx} y={cy + 10} textAnchor="middle" fontSize="8" fill="#94a3b8">Agents</text>
    </svg>
  );
}

function RiskActivityPanel() {
  const [timeRange, setTimeRange] = useState<"1h" | "6h" | "24h" | "7d">("24h");

  return (
    <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm">&#9656;</span>
            <span className="text-sm font-semibold text-white">Risk &amp; Activity</span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Operation risk level and agent activity</div>
        </div>
        <div className="flex gap-1">
          {(["1h", "6h", "24h", "7d"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setTimeRange(r)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                timeRange === r ? "bg-slate-600 text-white" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-4 p-4">
        {/* Sparkline */}
        <div className="flex-1 min-w-0">
          <div className="text-xs text-slate-400 mb-1 font-medium">Risk Level</div>
          <div className="flex items-end gap-1 mb-1">
            <span className="text-slate-400 text-[10px]">10</span>
          </div>
          <SparklineChart />
        </div>
        {/* Donut */}
        <div className="shrink-0 flex flex-col items-center gap-2">
          <div className="text-xs text-slate-400 font-medium self-start">Agent Activity</div>
          <DonutChart />
          <div className="space-y-1 text-[10px]">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-blue-500"></span>
              <span className="text-slate-400">Guardian</span>
              <span className="text-slate-300 ml-auto">34%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-purple-500"></span>
              <span className="text-slate-400">Cortex</span>
              <span className="text-slate-300 ml-auto">42%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-slate-500"></span>
              <span className="text-slate-400">Review</span>
              <span className="text-slate-300 ml-auto">24%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Feature Cards ----
const FEATURE_CARDS = [
  {
    icon: "&#9903;",
    title: "Graph Explorer",
    desc: "Visualize code structure, dependencies, and relationships.",
    color: "text-blue-400",
    border: "border-blue-500/20",
  },
  {
    icon: "&#9672;",
    title: "Guardian Operations",
    desc: "Manage approvals, track risky operations, and handle rollbacks.",
    color: "text-green-400",
    border: "border-green-500/20",
  },
  {
    icon: "&#x1F9E0;",
    title: "Cortex Review",
    desc: "Get AI insights, code analysis, and intelligent suggestions.",
    color: "text-purple-400",
    border: "border-purple-500/20",
  },
  {
    icon: "&#128737;",
    title: "Security Audit",
    desc: "View security rules, scan results, and compliance status.",
    color: "text-slate-300",
    border: "border-slate-600/30",
  },
];

function FeatureCards() {
  return (
    <div className="grid grid-cols-4 gap-3">
      {FEATURE_CARDS.map((card) => (
        <div
          key={card.title}
          className={`bg-[#0d1117] rounded-xl border ${card.border} p-3.5 hover:bg-slate-800/40 transition-colors cursor-pointer`}
        >
          <div className={`text-2xl mb-2 ${card.color}`} dangerouslySetInnerHTML={{ __html: card.icon }} />
          <div className="text-xs font-semibold text-white mb-1">{card.title}</div>
          <div className="text-[10px] text-slate-400 leading-relaxed">{card.desc}</div>
          <div className="mt-3 text-[10px] text-slate-600 flex items-center gap-1">
            <span>&#8594;</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- Code Graph Panel (wraps SynapseGraph) ----
function CodeGraphPanel({ onNodeClick, onNodeCount, nodeCount, edgeCount }: Omit<Props, "operations">) {
  return (
    <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 flex flex-col overflow-hidden" style={{ height: "420px" }}>
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60 shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-slate-400 text-sm">&#9903;</span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-white">Code Graph</span>
              <span className="flex items-center gap-1 text-[10px] text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block"></span>
                Live
              </span>
            </div>
            <div className="text-[10px] text-slate-500">
              Interactive dependency map &nbsp;&#183;&nbsp; {nodeCount} nodes &nbsp;&#183;&nbsp; {edgeCount} edges
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Fit view */}
          <button className="text-xs px-2.5 py-1 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors flex items-center gap-1">
            <span>&#8689;</span> Fit View
          </button>
          {/* Layout dropdown */}
          <button className="text-xs px-2.5 py-1 rounded-lg border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors flex items-center gap-1">
            Layout <span>&#9660;</span>
          </button>
          {/* Legend */}
          <div className="flex items-center gap-2 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-400 inline-block"></span>Module</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-400 inline-block"></span>Class</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-400 inline-block"></span>Function</span>
            <span className="flex items-center gap-1"><span className="w-0.5 h-3 bg-slate-500 inline-block"></span>Edge</span>
          </div>
        </div>
      </div>
      {/* Graph */}
      <div className="flex-1 overflow-hidden">
        <SynapseGraph onNodeClick={onNodeClick} onNodeCount={onNodeCount} />
      </div>
    </div>
  );
}

// ---- Main export ----
export default function OverviewMain({ onNodeClick, onNodeCount, nodeCount, edgeCount, operations }: Props) {
  return (
    <div className="flex-1 overflow-y-auto p-5 space-y-5 bg-[#080d14]">
      {/* Page title */}
      <div>
        <h1 className="text-xl font-bold text-white">Project Overview</h1>
        <p className="text-sm text-slate-400 mt-0.5">
          Live code <span className="text-white underline">understanding</span>, risk protection, and AI-driven review for safer development.
        </p>
      </div>

      {/* Code Graph */}
      <CodeGraphPanel
        onNodeClick={onNodeClick}
        onNodeCount={onNodeCount}
        nodeCount={nodeCount}
        edgeCount={edgeCount}
      />

      {/* Timeline + Risk side by side */}
      <div className="grid grid-cols-2 gap-4">
        <OperationTimeline ops={operations} />
        <RiskActivityPanel />
      </div>

      {/* Explore features */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">Explore Synapse Features</h2>
        <p className="text-xs text-slate-500 mb-3">Jump to key areas of the platform</p>
        <FeatureCards />
      </div>
    </div>
  );
}
