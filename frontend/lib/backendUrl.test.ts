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

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

// Semua modul yang fetch-nya berjalan di browser: `"use client"` langsung,
// atau diimpor oleh page client sehingga ikut ter-bundle ke browser.
const BROWSER_MODULES = [
  "app/page.tsx",
  "components/GuardianPanel.tsx",
  "components/pages/AgentsPage.tsx",
  "components/pages/CortexPage.tsx",
  "components/pages/GuardianPage.tsx",
  "components/pages/SettingsPage.tsx",
  "hooks/useBackendStatus.ts",
  "hooks/useLiveOps.ts",
  "lib/platformSettings.ts",
  "lib/sseStream.ts",
];

test("tidak ada modul browser yang fallback ke URL backend absolut", () => {
  const offenders: string[] = [];
  for (const rel of BROWSER_MODULES) {
    const src = readFileSync(join(ROOT, rel), "utf8");
    const match = src.match(
      /NEXT_PUBLIC_BACKEND_URL\s*\?\?\s*"([^"]+)"/,
    );
    if (!match) continue; // tidak punya fallback, tidak bisa salah
    if (/^https?:\/\//.test(match[1])) offenders.push(`${rel} -> ${match[1]}`);
  }
  assert.deepEqual(
    offenders,
    [],
    `Modul browser ini fallback ke URL absolut, jadi melewati proxy dan akan 401:\n${offenders.join("\n")}\n\nGanti dengan "/backend". Lihat frontend/.env.local.example.`,
  );
});

test("setiap modul browser yang butuh backend punya fallback ke proxy", () => {
  const missing: string[] = [];
  for (const rel of BROWSER_MODULES) {
    const src = readFileSync(join(ROOT, rel), "utf8");
    if (!src.includes("NEXT_PUBLIC_BACKEND_URL")) continue;
    if (!/NEXT_PUBLIC_BACKEND_URL\s*\?\?\s*"\/backend"/.test(src)) {
      missing.push(rel);
    }
  }
  assert.deepEqual(
    missing,
    [],
    `Modul ini tidak fallback ke "/backend":\n${missing.join("\n")}`,
  );
});
