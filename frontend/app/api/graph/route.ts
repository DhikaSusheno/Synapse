// app/api/graph/route.ts
// Proxy route: frontend → backend /graph/nodes + /graph/edges
// Dipakai untuk initial load data graph dari backend (sebelum SSE)
//
// H9: route ini DULU satu-satunya proxy yang jalan TANPA guard — tanpa
// cek Sec-Fetch-Site (jadi halaman mana pun bisa memicunya sebagai CSRF,
// dan proxy-lah yang menyuntikkan token server), dan tanpa penolakan kalau
// SYNAPSE_API_TOKEN belum disetel (request tetap diteruskan tanpa
// kredensial lalu gagal 401 di ujung). Padahal guard yang sama sudah ada
// di app/backend/[...path]/route.ts sejak isu #63. Dua proxy dengan dua
// tingkat keamanan berbeda adalah jebakan klasik: yang lemah yang
// diserpai. Logikanya kini diambil dari lib/proxyGuard.ts yang juga
// dipakai proxy utama, jadi keduanya tidak mungkin lagi berbeda.

import { NextRequest, NextResponse } from "next/server";
import {
  crossSiteDenial,
  missingTokenDenial,
  parseAllowedOrigins,
} from "@/lib/proxyGuard";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const TOKEN = process.env.SYNAPSE_API_TOKEN ?? "";
const ALLOWED_ORIGINS = parseAllowedOrigins(
  process.env.SYNAPSE_PROXY_ALLOWED_ORIGINS
);

const authHeaders: Record<string, string> = TOKEN
  ? { "X-Synapse-Token": TOKEN }
  : {};

function jsonError(status: number, error: string, hint?: string): Response {
  return new Response(JSON.stringify({ error, ...(hint ? { hint } : {}) }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function GET(request: NextRequest) {
  // Gagal-cepat sebelum menyuntik token dan menyentuh jaringan.
  const tokenDenied = missingTokenDenial(TOKEN);
  if (tokenDenied) {
    return jsonError(tokenDenied.status, tokenDenied.error, tokenDenied.hint);
  }

  const denied = crossSiteDenial(
    request.headers.get("sec-fetch-site"),
    request.headers.get("origin"),
    ALLOWED_ORIGINS
  );
  if (denied) {
    return jsonError(denied.status, denied.error, denied.hint);
  }

  try {
    const [nodesRes, edgesRes] = await Promise.all([
      fetch(`${BACKEND}/graph/nodes`, { cache: "no-store", headers: authHeaders }),
      fetch(`${BACKEND}/graph/edges`, { cache: "no-store", headers: authHeaders }),
    ]);

    if (nodesRes.status === 401 || edgesRes.status === 401) {
      return jsonError(
        502,
        "Token API backend ditolak",
        "Cocokkan SYNAPSE_API_TOKEN di .env.local dengan SYNAPSE_API_TOKEN milik backend"
      );
    }

    if (!nodesRes.ok || !edgesRes.ok) {
      return jsonError(502, "Backend tidak dapat dijangkau");
    }

    const [nodes, edges] = await Promise.all([
      nodesRes.json(),
      edgesRes.json(),
    ]);

    return NextResponse.json({ nodes, edges });
  } catch {
    // Jangan mencetak BACKEND_URL (lihat catatan serupa di proxy utama).
    return jsonError(
      503,
      "Backend offline — gunakan mock data",
      "Pastikan proses uvicorn berjalan dan variabel BACKEND_URL di server benar"
    );
  }
}
