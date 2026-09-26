// hooks/useSSE.ts
// Konsumsi SSE stream dari backend /stream.
// Diaktifkan saat backend sudah live - gantikan useMockSimulation.
//
// Mitigation BUG-08: cortex._emit() not thread-safe (issue #11)
// Frontend reconnect dengan exponential backoff agar SSE bisa recover
// otomatis jika stream mati saat approve/execute diklik di demo.

import type { SSEEvent, GraphNode } from "@/lib/types";
import { useSSEStream } from "@/hooks/useSSEStream";

// Node seperti yang dikirim backend dari understand_repo graph_update
interface BackendNode {
  id: string;
  type: GraphNode["type"];
  name: string;
  parent?: string;
  complexity?: number;
}

function mapBackendNode(n: BackendNode): GraphNode {
  return {
    id: n.id,
    name: n.name,
    type: n.type ?? "file",
    status: "idle",
    meta: n.complexity !== undefined ? { complexity: n.complexity } : undefined,
  };
}

export interface IngestProgress {
  current_doc: string;
  stats: Record<string, number>;
}

interface UseSSEOptions {
  onNodeUpdate: (nodeId: string, status: GraphNode["status"]) => void;
  onGraphUpdate: (nodes: GraphNode[]) => void;
  onIngestProgress?: (progress: IngestProgress) => void;
  enabled: boolean;
}

// Transport (koneksi + backoff) milik useSSEStream — BUG-38: satu /stream per app.
// Hook ini hanya menerjemahkan event ke callback halaman.
export function useSSE({
  onNodeUpdate,
  onGraphUpdate,
  onIngestProgress,
  enabled,
}: UseSSEOptions) {
  useSSEStream((parsed: SSEEvent) => {
    switch (parsed.event) {
      case "graph_update": {
        const rawNodes = (parsed.data.nodes as BackendNode[] | undefined) ?? [];
        if (rawNodes.length > 0) onGraphUpdate(rawNodes.map(mapBackendNode));
        break;
      }
      case "ingest_progress": {
        onIngestProgress?.({
          current_doc: (parsed.data.current_doc as string) ?? "",
          stats: (parsed.data.stats_so_far as Record<string, number>) ?? {},
        });
        break;
      }
      case "operation_proposed":
        onNodeUpdate(parsed.data.operation_id as string, "pending");
        break;
      case "operation_approved":
        onNodeUpdate(parsed.data.operation_id as string, "approved");
        break;
      case "operation_executing":
        onNodeUpdate(parsed.data.operation_id as string, "executing");
        break;
      case "operation_verified":
        onNodeUpdate(parsed.data.operation_id as string, "verified");
        break;
      case "operation_failed":
        onNodeUpdate(parsed.data.operation_id as string, "failed");
        break;
      case "operation_rolled_back":
        onNodeUpdate(parsed.data.operation_id as string, "rolled_back");
        break;
      case "heartbeat":
      case "connected":
      default:
        break;
    }
  }, enabled);
}
