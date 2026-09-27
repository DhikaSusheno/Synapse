// app/backend/[...path]/route.ts
// Proxy server-side ke backend FastAPI.
//
// BUG-11: backend mewajibkan token API di setiap route, sementara halaman
// browser tidak boleh menyimpan token itu di bundle. Route handler ini
// meneruskan request ke backend sambil menyuntikkan header token dari
// environment server, sehingga token tidak pernah sampai ke browser.
//
// Karena lewat server yang sama, request juga menjadi same-origin sehingga
// CORS tidak relevan untuk jalur ini.

import { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const TOKEN = process.env.SYNAPSE_API_TOKEN ?? "";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "host",
  "origin",
  "referer",
  "cookie",
  "content-length",
]);

async function proxy(
  request: NextRequest,
  context: { params: { path?: string[] } },
): Promise<Response> {
  const segments = context.params?.path ?? [];
  const target = `${BACKEND}/${segments.join("/")}${request.nextUrl.search}`;

  const headers: Record<string, string> = {};
  if (TOKEN) headers["X-Synapse-Token"] = TOKEN;

  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers[key] = value;
  });
  if (TOKEN) headers["X-Synapse-Token"] = TOKEN;

  const method = request.method.toUpperCase();
  const hasBody = method !== "GET" && method !== "HEAD" && method !== "OPTIONS";
  const body = hasBody ? await request.arrayBuffer() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return new Response(
      JSON.stringify({
        error: "Backend tidak dapat dijangkau",
        backend: BACKEND,
        hint: "Pastikan uvicorn jalan dan BACKEND_URL benar",
      }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  }

  if (upstream.status === 401) {
    return new Response(
      JSON.stringify({
        error: "Token API backend ditolak",
        hint: "Cocokkan SYNAPSE_API_TOKEN di .env.local dengan SYNAPSE_API_TOKEN milik backend",
      }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) responseHeaders.set(key, value);
  });
  responseHeaders.set("Cache-Control", "no-store");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
