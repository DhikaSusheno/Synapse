// lib/types.ts
// Kontrak data sesuai SYNAPSE.md section 4.2 dan backend/database.py

export type NodeStatus = "idle" | "pending" | "approved" | "executing" | "verified" | "failed" | "rolled_back";
export type NodeType = "file" | "symbol" | "dependency" | "doc" | "operation";
export type EdgeRelationship =
  | "DOCUMENTS"
  | "EXPLAINS"
  | "REFERENCES"
  | "IMPLEMENTED_BY"
  | "TARGETS"
  | "CONFLICTS_WITH"
  | "ROLLED_BACK_BY";

// Node dalam force graph
export interface GraphNode {
  id: string;
  name: string;
  type: NodeType;
  status: NodeStatus;
  meta?: Record<string, unknown>;
  // Diisi otomatis oleh react-force-graph-2d saat simulasi berjalan
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
}

// Edge dalam force graph (library pakai field "source" & "target")
export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  relationship: EdgeRelationship;
}

// Payload SSE event dari backend /stream
export interface SSEEvent {
  event:
    | "connected"
    | "heartbeat"
    | "graph_update"
    | "ingest_progress"
    | "operation_proposed"
    | "operation_approved"
    | "operation_executing"
    | "operation_verified"
    | "operation_failed"
    | "operation_rolled_back"
    | "review_done"
    | "health_report"
    | "refactor_suggestion";
  data: Record<string, unknown>;
}

// Operasi dari backend operations table
export interface Operation {
  id: string;
  tool_name: string;
  params_json: string;
  target_node_id: string | null;
  blast_radius: "low" | "medium" | "high" | "unknown";
  status: NodeStatus;
  requires_approval: number; // 0 | 1
  conflicts?: string[];
  created_at: string;
}
