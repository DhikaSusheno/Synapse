// lib/backendUrl.test.ts
// node --test "lib/*.test.ts"
//
// Guard untuk kontrak proxy BUG-11. Backend mewajibkan token API di setiap
// path non-public (backend/auth.py, fail-closed), dan browser tidak boleh
// menyimpan token itu. Jadi semua panggilan dari browser WAJIB lewat
// route handler app/backend/[...path]/route.ts yang menyuntikkan token.
//
// Kalau satu modul fallback ke URL absolut, request-nya menembak backend
// langsung tanpa header token dan dibalas 401 - sementara /health tetap
// public, jadi banner status tetap hijau sementara datanya kosong. Failure
// mode itu yang paling mahal, jadi dijaga di sini.
//
// Pindai SELURUH tree, bukan daftar file. Daftar keras akan misses file
// baru dari branch lain yang membawa pola yang sama - misalnya
// OperationsSidebar.tsx di frontend/nabilfauzandafa-polish2.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCAN_DIRS = ["app", "components", "hooks", "lib"];
const SKIP = new Set(["node_modules", ".next", ".git", "dist"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

// Path selalu pakai "/" supaya assertion tidak Depends on separator OS.
const rel = (f: string) => relative(ROOT, f).split(/[\\/]/).join("/");

const SOURCES = SCAN_DIRS.flatMap((d) => walk(join(ROOT, d))).filter(
  // Jangan scan diri sendiri: file ini memuat polanya sebagai contoh.
  (f) => rel(f) !== "lib/backendUrl.test.ts",
);

// Default yang sah: path relatif, supaya request lewat proxy.
const PUBLIC_DEFAULT = /process\.env\.NEXT_PUBLIC_BACKEND_URL\s*\?\?\s*"\/backend"/;
// Host absolut = request menembak backend tanpa header token.
const ABSOLUTE_DEFAULT =
  /process\.env\.NEXT_PUBLIC_BACKEND_URL\s*\?\?\s*"(https?:\/\/[^"]+)"/;
// Hanya VARIABEL yang dibaca, bukan penyebutan di teks UI. BackendStatusBanner
// memuat "NEXT_PUBLIC_BACKEND_URL" di pesan error dan itu bukan pembacaan env.
const READS_ENV = /process\.env\.NEXT_PUBLIC_BACKEND_URL/;

// Pakai exec, bukan matchAll: matchAll mengembalikan iterator yang butuh
// --downlevelIteration, dan tidak perlu mengubah tsconfig global demi test.
function allMatches(src: string, re: RegExp): string[] {
  const out: string[] = [];
  const rx = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  let m: RegExpExecArray | null;
  while ((m = rx.exec(src)) !== null) {
    out.push(m[1]);
    if (m.index === rx.lastIndex) rx.lastIndex++;
  }
  return out;
}

test("tree scan benar-benar menemukan file sumber", () => {
  assert.ok(
    SOURCES.length > 30,
    `hanya ${SOURCES.length} file ketemu - pola walk-nya salah`,
  );
  assert.ok(
    SOURCES.some((f) => rel(f) === "app/page.tsx"),
    "app/page.tsx tidak ikut ter-scan",
  );
  assert.ok(
    SOURCES.some((f) => rel(f) === "app/backend/[...path]/route.ts"),
    "proxy tidak ikut ter-scan",
  );
});

test("tidak ada modul browser yang fallback ke URL backend absolut", () => {
  const offenders: string[] = [];
  for (const file of SOURCES) {
    const src = readFileSync(file, "utf8");
    for (const host of allMatches(src, ABSOLUTE_DEFAULT)) {
      offenders.push(`${rel(file)} -> ${host}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `Modul ini fallback ke URL absolut, jadi melewati proxy dan akan 401:\n` +
      `${offenders.join("\n")}\n\nGanti dengan "/backend". ` +
      `Lihat frontend/.env.local.example.`,
  );
});

test("modul yang membaca env itu defaultnya ke proxy", () => {
  const bad: string[] = [];
  for (const file of SOURCES) {
    const src = readFileSync(file, "utf8");
    if (!READS_ENV.test(src)) continue;
    if (!PUBLIC_DEFAULT.test(src)) bad.push(rel(file));
  }
  assert.deepEqual(bad, [], `Default bukan "/backend":\n${bad.join("\n")}`);
});

test("proxy tidak boleh pakai NEXT_PUBLIC_, hanya server-side env", () => {
  const proxy = readFileSync(
    join(ROOT, "app/backend/[...path]/route.ts"),
    "utf8",
  );
  // NEXT_PUBLIC_ di-inline ke bundle browser, jadi token / URL backend akan
  // ikut terkirim ke client. Proxy harus hanya membaca env server.
  assert.ok(
    !/NEXT_PUBLIC_/.test(proxy),
    "proxy memuat NEXT_PUBLIC_* - nilainya akan masuk bundle browser",
  );
  assert.match(
    proxy,
    /process\.env\.BACKEND_URL\s*\?\?\s*"https?:\/\//,
    "proxy harus default ke URL absolut server-side; hanya browser yang wajib /backend",
  );
});
