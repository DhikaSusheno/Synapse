// lib/graphEdges.test.ts
// node --test "lib/*.test.ts"

import { test } from "node:test";
import assert from "node:assert/strict";
import { normalEdge, normalEdges } from "./graphEdges.ts";

// Bentuk ASLI yang dikirim backend /graph/edges (engine.get_graph_edges):
// source/target/relationship/confidence. Field "source_id"/"target_id" TIDAK
// pernah dikirim. Test pertama mengunci kontrak ini, karena versi lama
// SynapseGraph.tsx justru mencari source_id/target_id dan membuang semua edge.
const BACKEND_EDGE = {
  source: "doc::.github/workflows/ci.yml",
  target: "file::backend/main.py",
  relationship: "DOCUMENTS",
  confidence: 0.8,
} as const;

test("edge backend dengan source/target diteruskan utuh", () => {
  assert.deepEqual(normalEdge({ ...BACKEND_EDGE }), {
    source: "doc::.github/workflows/ci.yml",
    target: "file::backend/main.py",
    relationship: "DOCUMENTS",
  });
});

test("BUG-39: 1256 edge backend tidak boleh terbuang semua jadi 0", () => {
  // Balaan: filter lama memakai e.source_id && e.target_id, yang selalu falsy
  // untuk payload di atas, jadi semua edge hilang tanpa error apa pun.
  const many = Array.from({ length: 1256 }, (_, i) => ({
    source: `file::mod${i}.py`,
    target: `file::main.py`,
    relationship: "DEPENDS_ON",
  }));
  assert.equal(normalEdges(many).length, 1256);
});

test("edge tanpa relationship tetap dipakai, default DEPENDS_ON", () => {
  const link = normalEdge({ source: "a", target: "b" });
  assert.equal(link?.relationship, "DEPENDS_ON");
});

test("bentuk lama source_id/target_id tetap diterima", () => {
  assert.deepEqual(normalEdge({ source_id: "a", target_id: "b", relationship: "TARGETS" }), {
    source: "a",
    target: "b",
    relationship: "TARGETS",
  });
});

test("source menang kalau dua-duanya ada", () => {
  // Field yang baru menang lebih dulu karena itu yang jadi kunci saat ini.
  // Kalau yang lama menang, edge akan menunjuk node yang tidak ada di graph.
  const link = normalEdge({ source: "baru", target: "baru2", source_id: "lama", target_id: "lama2" });
  assert.equal(link?.source, "baru");
  assert.equal(link?.target, "baru2");
});

test("edge tanpa satu ujung ditolak, bukan jadi edge setengah jadi", () => {
  // react-force-graph-2d menulis ulang link jadi undefined kalau node ujung
  // hilang, lalu filterGraph meledak. Lebih baik edge-nya hilang.
  assert.equal(normalEdge({ source: "a" }), null);
  assert.equal(normalEdge({ target: "b" }), null);
  assert.equal(normalEdge({ source: "a", target: "" }), null);
  assert.equal(normalEdge({ source: "", target: "b" }), null);
});

test("ujung non-string ditolak", () => {
  // SSE/react-force-graph bisa mengirim node objek, bukan id string.
  assert.equal(normalEdge({ source: { id: "a" }, target: "b" } as never), null);
  assert.equal(normalEdge({ source: 1, target: 2 } as never), null);
});

test("null dan undefined ditolak", () => {
  assert.equal(normalEdge(null), null);
  assert.equal(normalEdge(undefined), null);
});

test("normalEdges membuang yang rusak tanpa membuang yang sehat", () => {
  const out = normalEdges([
    BACKEND_EDGE,
    null,
    undefined,
    { source: "x" },
    { source_id: "p", target_id: "q", relationship: "REFERENCES" },
    "bukan objek",
  ]);
  assert.equal(out.length, 2);
  assert.deepEqual(out.map((l) => l.source), ["doc::.github/workflows/ci.yml", "p"]);
});

test("payload yang bukan array menghasilkan array kosong, bukan crash", () => {
  // Backend balas 502 dengan {error: "..."} tanpa nodes/edges. useInitialGraph
  // memanggil normalEdges(data.edges) tanpa cek typeof, jadi data.edges undefined.
  assert.deepEqual(normalEdges(undefined), []);
  assert.deepEqual(normalEdges(null), []);
  assert.deepEqual(normalEdges({ error: "Backend offline" }), []);
  assert.deepEqual(normalEdges("nope"), []);
});

test("edge yang ujung merujuk node tak ada tidak diurus di sini", () => {
  // normalEdge tidak tahu daftar node. Penyaringan orphan ada di filterGraph
  // supaya ada satu tempat saja yang tahu soal itu. Test ini hanya menegaskan
  // normalEdge tidak ikut melempar.
  const link = normalEdge({ source: "tidak-ada", target: "juga-tidak-ada" });
  assert.equal(link?.source, "tidak-ada");
});
