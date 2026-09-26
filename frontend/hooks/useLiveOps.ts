// hooks/useLiveOps.ts
// Fetch dataoperasian dari backend untuk halaman Agents & Security.
// Mock bukan default: fallback hanya kalau backend tidak merespons.
// FE-1 @nabilfauzandafa

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveOp } from "@/lib/derive";
import { isOpen } from "@/lib/derive";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

export interface LiveOpsState {
  ops: LiveOp[];
  loading: boolean;
  error: string | null;
  offline: boolean;
  refresh: () => void;
}

function mapOp(raw: Record<string, unknown>): LiveOp {
  return {
    id: (raw.id as string) ?? "",
    tool_name: (raw.tool_name as string) ?? "unknown",
    params_json: (raw.params_json as string) ?? "{}",
    target_node_id: (raw.target_node_id as string) ?? null,
    blast_radius: (raw.blast_radius as string) ?? "unknown",
    status: (raw.status as string) ?? "pending",
    requires_approval: (raw.requires_approval as number) ?? 1,
    created_at: (raw.created_at as string) ?? new Date().toISOString(),
    executed_at: (raw.executed_at as string) ?? null,
    verified_at: (raw.verified_at as string) ?? null,
  };
}

export function useLiveOps(pollMs = 5000): LiveOpsState {
  const [ops, setOps] = useState<LiveOp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/operations?limit=100`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as unknown;
      if (!Array.isArray(data)) throw new Error("shape");
      setOps(data.map((r) => mapOp(r as Record<string, unknown>)));
      setError(null);
      setOffline(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "fetch failed");
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!USE_LIVE) {
      setLoading(false);
      return;
    }
    load();
    timerRef.current = setInterval(load, pollMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load, pollMs, USE_LIVE]);

  return { ops, loading, error, offline, refresh: load };
}

export function useOpenOps(pollMs = 5000): LiveOpsState & { open: LiveOp[] } {
  const state = useLiveOps(pollMs);
  return { ...state, open: state.ops.filter((op) => isOpen(op.status)) };
}
