// lib/targets.test.ts
// Unit test untuk helper targets yang murni + store snapshot (tanpa network).

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  slugify,
  validateLocalDraft,
  validateGitHubDraft,
  findActive,
  selectableTargets,
  summarizeIngest,
  publishTargets,
  getActiveTarget,
  getTargetSnapshot,
  subscribeTargets,
  type Target,
} from "./targets.ts";

const target = (id: string, over: Partial<Target> = {}): Target => ({
  id,
  kind: "local",
  label: id.toUpperCase(),
  path: `C:/projects/${id}`,
  source: null,
  branch: null,
  available: true,
  ...over,
});

// --- slugify -------------------------------------------------------------

test("slugify: label jadi id ramah, sama aturan dengan backend", () => {
  assert.equal(slugify("My Repo"), "my-repo");
  assert.equal(slugify("  Face API  "), "face-api");
  assert.equal(slugify("face-api"), "face-api");
  assert.equal(slugify("A,B.C"), "a-b-c");
  assert.equal(slugify("__a__b__"), "a-b");
});

test("slugify: input tanpa huruf tidak jadi string kosong", () => {
  // String kosong akan jadi nama file DB dari sisi server juga, jadi harus
  // tetap ada isinya.
  assert.equal(slugify(""), "target");
  assert.equal(slugify("   "), "target");
  assert.equal(slugify("---"), "target");
  assert.equal(slugify("!!!"), "target");
});

// --- validasi draft ------------------------------------------------------

test("validateLocalDraft: path dan label wajib", () => {
  assert.deepEqual(validateLocalDraft({ kind: "local", label: "P", path: "   " }), [
    "Path folder wajib diisi.",
  ]);
  assert.deepEqual(validateLocalDraft({ kind: "local", label: "  ", path: "C:/proyek" }), [
    "Label target wajib diisi.",
  ]);
  assert.deepEqual(
    validateLocalDraft({ kind: "local", label: "  ", path: "  " }),
    ["Path folder wajib diisi.", "Label target wajib diisi."],
  );
  assert.deepEqual(validateLocalDraft({ kind: "local", label: "P", path: "C:/proyek" }), []);
});

test("validateLocalDraft: separator Windows dan POSIX sama-sama diterima", () => {
  // Path dari pemilih folder (Windows) dan dari user Linux harus lolos sama.
  assert.deepEqual(validateLocalDraft({ kind: "local", label: "P", path: "C:\\proyek\\api" }), []);
  assert.deepEqual(validateLocalDraft({ kind: "local", label: "P", path: "/home/dhika/api" }), []);
});

test("validateGitHubDraft: harus owner/repo", () => {
  const bad = "Format harus owner/repo, contoh: DhikaSusheno/Synapse";
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "" }), [bad]);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "owner" }), [bad]);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "owner/" }), [bad]);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "/repo" }), [bad]);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "owner/repo/extra" }), [bad]);
});

test("validateGitHubDraft: karakter yang jadi bagian path server ditolak", () => {
  // Source masuk ke path filesystem backend, jadi ini bukan sekadar estetika.
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "user$name/repo" }).length, 1);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "owner/..%2f..%2fetc" }).length, 1);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "own er/repo" }).length, 1);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "dhika-susheno/synapse_v2" }), []);
  assert.deepEqual(validateGitHubDraft({ kind: "github", source: "user.name/repo.name" }), []);
});

// --- pencarian target ----------------------------------------------------

test("findActive: id aktif yang tidak ada di daftar -> null", () => {
  // Kalau id aktif menunjuk target yang sudah dihapus, UI harus jujur bilang
  // tidak ada, bukan menampilkan target pertama sebagai-if aktif.
  const t = target("t1");
  assert.equal(findActive({ active: "t1", targets: [t] }), t);
  assert.equal(findActive({ active: "t2", targets: [t] }), null);
  assert.equal(findActive({ active: null, targets: [t] }), null);
  assert.equal(findActive({ active: "t1", targets: [] }), null);
});

test("selectableTargets: hanya yang available", () => {
  // available: false akan 409 saat diaktifkan, jadi tidak boleh ditawarkan.
  const ok = target("a");
  const broken = target("b", { available: false });
  assert.deepEqual(selectableTargets([ok, broken]), [ok]);
  assert.deepEqual(selectableTargets([]), []);
});

// --- ringkasan ingest ----------------------------------------------------

test("summarizeIngest: null, gagal, dan sukses", () => {
  assert.equal(summarizeIngest(null), "");
  assert.equal(summarizeIngest(undefined), "");
  assert.equal(summarizeIngest({ ok: false }), "Ingest gagal");
  assert.equal(summarizeIngest({ ok: false, error: "graph tidak bisa dibuka" }), "graph tidak bisa dibuka");
});

test("summarizeIngest: hanya field yang ada ikut ditampilkan", () => {
  assert.equal(summarizeIngest({ ok: true }), "");
  assert.equal(summarizeIngest({ ok: true, files: 5 }), "5 file");
  assert.equal(summarizeIngest({ ok: true, files: 5, symbols: 87 }), "5 file, 87 simbol");
  assert.equal(
    summarizeIngest({ ok: true, files: 12, symbols: 87, edges: 125, docs: 3 }),
    "12 file, 87 simbol, 125 relasi",
  );
});

// --- store snapshot ------------------------------------------------------

test("publishTargets mengisi snapshot dan getActiveTarget ikut", () => {
  const t = target("x");
  publishTargets({ active: "x", targets: [t] });
  assert.equal(getActiveTarget(), t);
  assert.equal(getTargetSnapshot().active, t);
  assert.deepEqual(getTargetSnapshot().targets, [t]);
});

test("publishTargets selalu membuat objek baru (useSyncExternalStore butuh itu)", () => {
  const t = target("x");
  publishTargets({ active: "x", targets: [t] });
  const first = getTargetSnapshot();
  publishTargets({ active: "x", targets: [t] });
  const second = getTargetSnapshot();
  // Konten sama, tapi referensinya beda - kalau tidak, React menganggap
  // store tidak berubah dan useEffect pemanggil reload tidak pernah jalan.
  assert.notEqual(first, second);
  assert.equal(first.active, second.active);
});

test("publishTargets: active menunjuk target yang tidak ada -> active null", () => {
  publishTargets({ active: "hilang", targets: [target("a")] });
  assert.equal(getActiveTarget(), null);
  assert.equal(getTargetSnapshot().targets.length, 1);
});

test("subscribeTargets: unsubscribe benar-benar menghentikan pemanggilan", () => {
  const t = target("s");
  let calls = 0;
  const off = subscribeTargets(() => {
    calls += 1;
  });
  publishTargets({ active: "s", targets: [t] });
  const afterFirst = calls;
  off();
  publishTargets({ active: "s", targets: [t] });
  assert.ok(afterFirst > 0, "listener aktif harus dipanggil");
  assert.equal(calls, afterFirst, "setelah unsubscribe tidak boleh dipanggil lagi");
});
