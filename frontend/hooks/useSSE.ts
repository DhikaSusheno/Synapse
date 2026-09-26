// hooks/useSSE.ts
// Konsumsi SSE stream dari backend /stream.
// Diaktifkan saat backend sudah live — gantikan useMockSimulation.

import { useEffect, useRef, useCallback } from "react";
import type { SSEEvent, GraphNode } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

interface UseSSEOptions {
  onNodeUpdate: (nodeId: string, status: GraphNode["status"]) => void;
  onGraphUpdate: (nodes: GraphNode[]) => void;
  enabled: boolean;
}

export function useSSE({ onNodeUpdate, onGraphUpdate, enabled }: UseSSEOptions) {
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
            const newNodes = (parsed.data.nodes as GraphNode[] | undefined) ?? [];
            if (newNodes.length > 0) {
              onGraphUpdate(newNodes);
            }
            break;
          }

          // Status transition operasi
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
  }, [onNodeUpdate, onGraphUpdate]);

  useEffect(() => {
    if (!enabled) return;
    connect();
    return () => esRef.current?.close();
  }, [enabled, connect]);
}
