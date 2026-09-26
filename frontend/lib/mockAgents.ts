// lib/mockAgents.ts
// Mock data untuk halaman Agents (mode MOCK)
// FE-1 @nabilfauzandafa

export interface AgentTask {
  id: string;
  agent: "guardian" | "cortex" | "review";
  description: string;
  status: "running" | "pending" | "done" | "error";
  timestamp: string;
}

export interface AgentStats {
  name: "guardian" | "cortex" | "review";
  label: string;
  subtitle: string;
  tasks: number;
  healthy: boolean;
  color: string;
  bgColor: string;
  borderColor: string;
}

export interface SSELogEntry {
  ts: string;
  agent: string;
  event: string;
  message: string;
}

export interface RecentAction {
  agent: "guardian" | "cortex" | "review";
  action: string;
  relativeTime: string;
}

export interface ConflictItem {
  opId: string;
  description: string;
  conflictWith: string;
}

export const MOCK_AGENT_STATS: AgentStats[] = [
  {
    name: "guardian",
    label: "Guardian",
    subtitle: "Protection & Safety",
    tasks: 2,
    healthy: true,
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
    borderColor: "border-blue-500/30",
  },
  {
    name: "cortex",
    label: "Cortex",
    subtitle: "Understanding & Review",
    tasks: 3,
    healthy: true,
    color: "text-purple-400",
    bgColor: "bg-purple-500/10",
    borderColor: "border-purple-500/30",
  },
  {
    name: "review",
    label: "Review",
    subtitle: "Code Review & Analysis",
    tasks: 1,
    healthy: true,
    color: "text-slate-300",
    bgColor: "bg-slate-600/10",
    borderColor: "border-slate-600/30",
  },
];

export const MOCK_CURRENT_TASKS: AgentTask[] = [
  {
    id: "t1",
    agent: "guardian",
    description: "Checking conflicts for db/migration",
    status: "running",
    timestamp: "08:42",
  },
  {
    id: "t2",
    agent: "cortex",
    description: "Building graph for 12 files",
    status: "running",
    timestamp: "08:38",
  },
  {
    id: "t3",
    agent: "guardian",
    description: "operation: proposed",
    status: "done",
    timestamp: "08:36",
  },
  {
    id: "t4",
    agent: "cortex",
    description: "Analyzing PR.diff",
    status: "done",
    timestamp: "08:35",
  },
];

export const MOCK_SSE_LOG: SSELogEntry[] = [
  { ts: "14:32", agent: "Guardian", event: "conflict_detected",   message: "Guardian conflict detected" },
  { ts: "14:30", agent: "Cortex",   event: "graph_update",        message: "Cortex: graph updated" },
  { ts: "14:28", agent: "Review",   event: "review_done",         message: "Review: analysis completed" },
  { ts: "14:27", agent: "Guardian", event: "operation_proposed",  message: "Guardian: operation proposed" },
  { ts: "14:25", agent: "Cortex",   event: "topic_explanation",   message: "Cortex: topic explanation ready" },
];

export const MOCK_RECENT_ACTIONS: RecentAction[] = [
  { agent: "cortex",   action: "explain_topic",       relativeTime: "2 min ago" },
  { agent: "review",   action: "review_artifact",     relativeTime: "4 min ago" },
  { agent: "guardian", action: "propose_operation",   relativeTime: "6 min ago" },
];

export const MOCK_CONFLICTS: ConflictItem[] = [
  {
    opId: "op::migrate-priority",
    description: "db/migration",
    conflictWith: "op::migrate-tag (2 min ago)",
  },
];

// Activity data untuk sparkline chart (guardian, cortex, review)
export const MOCK_ACTIVITY_DATA = {
  labels: ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30"],
  guardian: [2, 3, 4, 2, 5, 6, 4, 3, 5, 4],
  cortex:   [3, 4, 3, 5, 4, 3, 6, 5, 4, 6],
  review:   [1, 2, 1, 3, 2, 1, 2, 3, 2, 1],
};
