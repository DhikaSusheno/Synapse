// app/api/graph/route.ts
// Proxy route: frontend → backend /graph/nodes + /graph/edges
// Dipakai untuk initial load data graph dari backend (sebelum SSE)

import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const [nodesRes, edgesRes] = await Promise.all([
      fetch(`${BACKEND}/graph/nodes`, { cache: "no-store" }),
      fetch(`${BACKEND}/graph/edges`, { cache: "no-store" }),
    ]);

    if (!nodesRes.ok || !edgesRes.ok) {
      return NextResponse.json(
        { error: "Backend tidak dapat dijangkau" },
        { status: 502 }
      );
    }

    const [nodes, edges] = await Promise.all([
      nodesRes.json(),
      edgesRes.json(),
    ]);

    return NextResponse.json({ nodes, edges });
  } catch {
    return NextResponse.json(
      { error: "Backend offline — gunakan mock data" },
      { status: 503 }
    );
  }
}
