// hooks/useSSE.ts
// Konsumsi SSE stream dari backend /stream.
// Diaktifkan saat backend sudah live - gantikan useMockSimulation.

import { useEffect, useRef, useCallback } from "react";
import type { SSEEvent, GraphNode } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// Node seperti yang dikirim backend dari understand_repo graph_update
interface BackendNode {
  id: string;
  type: GraphNode["type"];
  name: string;
  parent?: string;
  complexity?: number;
}

// Konversi node format backend → format GraphNode frontend
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

export function useSSE({
  onNodeUpdate,
  onGraphUpdate,
  onIngestProgress,
  enabled,
}: UseSSEOptions) {
  const esRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }

    const es = new EventSource(`${BACKEND_URL}/stream`);
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed: SSEEvent = JSON.parse(event.data);

        switch (parsed.event) {
          // Backend emit graph_update saat understand_repo selesai
          case "graph_update": {
            const rawNodes = (parsed.data.nodes as BackendNode[] | undefined) ?? [];
            if (rawNodes.length > 0) {
              onGraphUpdate(rawNodes.map(mapBackendNode));
            }
            break;
          }

          // Progress ingest per-doc
          case "ingest_progress": {
            onIngestProgress?.({
              current_doc: (parsed.data.current_doc as string) ?? "",
              stats: (parsed.data.stats_so_far as Record<string, number>) ?? {},
            });
            break;
          }

          // Status transition operasi — backend pakai operation_id UUID
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
      } catch {
        // Abaikan event yang tidak bisa di-parse
      }
    };

    es.onerror = () => {
      // Auto-reconnect setelah 3 detik jika koneksi putus
      es.close();
      setTimeout(connect, 3000);
    };
  }, [onNodeUpdate, onGraphUpdate, onIngestProgress]);

  useEffect(() => {
    if (!enabled) return;
    connect();
    return () => esRef.current?.close();
  }, [enabled, connect]);
}
