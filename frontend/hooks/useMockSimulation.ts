// hooks/useMockSimulation.ts
// Simulasi perubahan status node — dipakai saat backend belum siap.
// Ganti ini dengan useSSE saat backend sudah live.

import { useEffect } from "react";
import { MOCK_TIMELINE } from "@/lib/mockData";
import type { GraphNode } from "@/lib/types";

type UpdateFn = (nodeId: string, status: GraphNode["status"]) => void;

export function useMockSimulation(onUpdate: UpdateFn, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const timers = MOCK_TIMELINE.map(({ delayMs, nodeId, status }) =>
      setTimeout(() => onUpdate(nodeId, status), delayMs)
    );

    return () => timers.forEach(clearTimeout);
  }, [enabled, onUpdate]);
}
