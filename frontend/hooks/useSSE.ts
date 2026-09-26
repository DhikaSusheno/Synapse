// hooks/useSSE.ts
// Konsumsi SSE stream dari backend /stream.
// Diaktifkan saat backend sudah live - gantikan useMockSimulation.
//
// Fix #38: tambah onRawEvent callback supaya page.tsx bisa collect
// event log tanpa OperationsSidebar membuka koneksi SSE tersendiri.

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

// #38: entry shape yang sama dengan EventLogPanel di OperationsSidebar
export interface RawSSEEntry {
  ts: string;
  event: string;
  summary: string;
}

interface UseSSEOptions {
  onNodeUpdate: (nodeId: string, status: GraphNode["status"]) => void;
  onGraphUpdate: (nodes: GraphNode[]) => void;
  onIngestProgress?: (progress: IngestProgress) => void;
  /** #38: dipanggil untuk setiap SSE event non-heartbeat — untuk event log di OperationsSidebar */
  onRawEvent?: (entry: RawSSEEntry) => void;
  enabled: boolean;
}

// Exponential backoff: 1s, 2s, 4s, 8s, capped at 10s
function nextDelay(attempt: number): number {
  return Math.min(1000 * Math.pow(2, attempt), 10_000);
}

export function useSSE({
  onNodeUpdate,
  onGraphUpdate,
  onIngestProgress,
  onRawEvent,
  enabled,
}: UseSSEOptions) {
  const esRef = useRef<EventSource | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const es = new EventSource(`${BACKEND_URL}/stream`);
    esRef.current = es;

    es.onopen = () => {
      // Reset backoff counter on successful connection
      attemptRef.current = 0;
    };

    es.onmessage = (event) => {
      try {
        const parsed: SSEEvent = JSON.parse(event.data);

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
            return; // jangan masuk onRawEvent
          default:
            break;
        }

        // #38: kirim ke event log via callback — tidak buka koneksi baru
        if (onRawEvent) {
          const d = parsed.data;
          const summary = (() => {
            if (d.operation_id) return `op ${String(d.operation_id).slice(0, 8)}... ${d.tool_name ?? ""}`.trim();
            if (d.current_doc) return `ingest: ${d.current_doc}`;
            if (d.repo) return `graph: ${d.repo}`;
            return JSON.stringify(d).slice(0, 60);
          })();
          onRawEvent({ ts: new Date().toLocaleTimeString(), event: parsed.event, summary });
        }
      } catch {
        // Abaikan event yang tidak bisa di-parse
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      if (!mountedRef.current) return;
      // Exponential backoff reconnect
      const delay = nextDelay(attemptRef.current);
      attemptRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };
  }, [onNodeUpdate, onGraphUpdate, onIngestProgress, onRawEvent]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return;
    connect();
    return () => {
      mountedRef.current = false;
      esRef.current?.close();
      esRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, connect]);
}
