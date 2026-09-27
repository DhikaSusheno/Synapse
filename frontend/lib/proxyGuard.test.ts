// lib/proxyGuard.test.ts
// node --test "lib/*.test.ts"
//
// Regression test untuk H9: repo ini punya DUA proxy yang menyuntikkan
// SYNAPSE_API_TOKEN dari sisi server, tapi guard-nya (cek Sec-Fetch-Site +
// gagal-cepat kalau token kosong) cuma ada di proxy utama sejak isu #63.
// app/api/graph/route.ts jalan telanjang — halaman mana pun bisa memicunya
// dan server tetap menyuntik kredensial ke backend.
//
// Test terakhir di file ini adalah yang paling penting: ia memindai semua
// route handler dan menuntut guard dipakai di situ, sehingga proxy KETIGA
// yang ditambahkan orang tanpa guard langsung bikin test ini merah.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

import {
  SAFE_FETCH_SITES,
  crossSiteDenial,
  missingTokenDenial,
  parseAllowedOrigins,
} from "./proxyGuard.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const rel = (f: string) => relative(ROOT, f).split(/[\\/]/).join("/");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (["node_modules", ".next", ".git", "dist"].includes(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name === "route.ts" || entry.name === "route.tsx") out.push(full);
  }
  return out;
}

// ---------------------------------------------------------------- Sec-Fetch

test("Sec-Fetch-Site cross-site ditolak 403", () => {
  const denied = crossSiteDenial("cross-site", "http://evil.example");
  assert.ok(denied, "cross-site harus ditolak");
  assert.equal(denied.status, 403);
});

test("pengecekan Sec-Fetch-Site tidak case-sensitive", () => {
  assert.ok(crossSiteDenial("Cross-Site", null));
  assert.ok(crossSiteDenial("CROSS-SITE", null));
});

test("same-origin, same-site, dan none diperbolehkan", () => {
  for (const site of ["same-origin", "same-site", "none"]) {
    assert.equal(crossSiteDenial(site, null), null, `${site} harus lolos`);
  }
});

test("tanpa header Sec-Fetch-Site diperbolehkan (klien non-browser)", () => {
  // Kalau header tidak dikirim, tidak ada bukti request dari browser
  // foreign — dan memblokirnya akan mematikan curl serta klien server.
  assert.equal(crossSiteDenial(null, null), null);
});

test("SAFE_FETCH_SITES tidak memuat nilai berbahaya", () => {
  assert.ok(!SAFE_FETCH_SITES.has("cross-site"));
  assert.ok(!SAFE_FETCH_SITES.has("cross-origin"));
  assert.equal(SAFE_FETCH_SITES.size, 3);
});

// ---------------------------------------------------------------- origin

test("origin di luar allowlist ditolak hanya kalau allowlist terisi", () => {
  const allowed = new Set(["http://localhost:3000"]);
  const denied = crossSiteDenial(null, "http://evil.example", allowed);
  assert.ok(denied);
  assert.equal(denied.status, 403);
  assert.match(denied.hint ?? "", /evil\.example/);
});

test("origin di dalam allowlist diperbolehkan", () => {
  const allowed = new Set(["http://localhost:3000"]);
  assert.equal(crossSiteDenial(null, "http://localhost:3000", allowed), null);
});

test("allowlist kosong berarti tanpa pembatasan origin", () => {
  assert.equal(crossSiteDenial(null, "http://evil.example", new Set()), null);
});

test("tanpa header Origin tidak ditolak (GET tidak mengirim Origin)", () => {
  const allowed = new Set(["http://localhost:3000"]);
  assert.equal(crossSiteDenial(null, null, allowed), null);
});

// ---------------------------------------------------------------- token

test("token kosong ditolak 503 sebelum request diteruskan", () => {
  const denied = missingTokenDenial("");
  assert.ok(denied);
  assert.equal(denied.status, 503);
  assert.match(denied.error, /SYNAPSE_API_TOKEN/);
});

test("token ada berarti lolos", () => {
  assert.equal(missingTokenDenial("token-yang-valid-panjang"), null);
});

// ---------------------------------------------------------------- parsing

test("parseAllowedOrigins membuang spasi dan entri kosong", () => {
  const parsed = parseAllowedOrigins(
    " http://localhost:3000 , http://localhost:3001 ,, "
  );
  // Array.from/Set spread sengaja tidak dipakai: tsconfig menargetkan es5
  // sehingga iterasi Set butuh downlevelIteration.
  assert.equal(parsed.size, 2, `dapat ${parsed.size} entri`);
  assert.ok(parsed.has("http://localhost:3000"));
  assert.ok(parsed.has("http://localhost:3001"));
});

test("parseAllowedOrigins(undefined) menghasilkan set kosong", () => {
  assert.equal(parseAllowedOrigins(undefined).size, 0);
  assert.equal(parseAllowedOrigins("").size, 0);
});

// ------------------------------------------------- H9: semua proxy harus guard

test("setiap route handler proxy memakai proxyGuard", () => {
  const routes = walk(join(ROOT, "app"));
  assert.ok(routes.length >= 2, `minimal dua route, dapat ${routes.length}`);

  const offenders: string[] = [];
  for (const file of routes) {
    const src = readFileSync(file, "utf8");
    const mentionsBackend = /BACKEND_URL|SYNAPSE_API_TOKEN/.test(src);
    if (!mentionsBackend) continue; // route biasa, bukan proxy
    const guarded =
      src.includes("@/lib/proxyGuard") ||
      (src.includes("crossSiteDenial") && src.includes("missingTokenDenial"));
    if (!guarded) offenders.push(rel(file));
  }

  assert.deepEqual(
    offenders,
    [],
    `route berikut menyuntik token tanpa guard (H9): ${offenders.join(", ")}`
  );
});

test("proxy /api/graph menyuntik token dan tidak lagi telanjang", () => {
  const file = join(ROOT, "app", "api", "graph", "route.ts");
  const src = readFileSync(file, "utf8");
  assert.match(src, /proxyGuard/, "guard harus diimpor");
  assert.match(
    src,
    /X-Synapse-Token/,
    "route ini memang menyuntik token — karena itu guard wajib"
  );
});
