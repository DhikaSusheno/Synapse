// hooks/useSSEStream.ts
// React wrapper tipis di atas lib/sseStream — logic koneksi + backoff di sana
// supaya bisa diuji tanpa React (BUG-38: satu /stream per app, bukan per halaman).

import { useEffect, useRef } from "react";
import type { SSEEvent } from "@/lib/types";
import { subscribeStream } from "@/lib/sseStream";

export function useSSEStream(onEvent: (event: SSEEvent) => void, enabled: boolean): void {
  const ref = useRef(onEvent);
  ref.current = onEvent; // callback terbaru tanpa resubscribe tiap render

  useEffect(() => {
    if (!enabled) return;
    return subscribeStream((event) => ref.current(event));
  }, [enabled]);
}
