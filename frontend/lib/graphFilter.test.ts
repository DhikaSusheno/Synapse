// lib/graphFilter.test.ts
// node --test "lib/*.test.ts"

import { test } from "node:test";
import assert from "node:assert/strict";
import { filterGraph } from "./graphFilter.ts";
import type { GraphNode, GraphLink } from "./types.ts";

function node(id: string, type: GraphNode["type"], name = id): GraphNode {
  return { id, name, type, status: "idle" };
}

const NODES: GraphNode[] = [
  node("f1", "file", "auth.py"),
  node("f2", "file", "db.py"),
  node("s1", "symbol", "verify_token"),
  node("d1", "doc", "Auth Design"),
  node("o1", "operation", "op::migrate"),
];

const LINKS: GraphLink[] = [
  { source: "f1", target: "s1", relationship: "REFERENCES" },
  { source: "f1", target: "d1", relationship: "DOCUMENTS" },
  { source: "f2", target: "s1", relationship: "TARGETS" },
];

test("All + query kosong: semua node dan edge lewat", () => {
  const r = filterGraph(NODES, LINKS, "All", "");
  assert.equal(r.nodes.length, 5);
  assert.equal(r.links.length, 3);
});

test("filter tipe: hanya tipe itu, operation tetap ikut", () => {
  const r = filterGraph(NODES, LINKS, "File", "");
  assert.deepEqual(r.nodes.map((n) => n.id).sort(), ["f1", "f2", "o1"]);
});

test("query cocok sebagian: case-insensitive, cocok ke name", () => {
  const r = filterGraph(NODES, LINKS, "All", "AUTH");
  assert.deepEqual(r.nodes.map((n) => n.id).sort(), ["d1", "f1", "o1"]);
});

test("query dicocokkan ke id juga", () => {
  const r = filterGraph(NODES, LINKS, "All", "s1");
  assert.deepEqual(r.nodes.map((n) => n.id).sort(), ["o1", "s1"]);
});

test("edge ke node tersaring ikut hilang (tidak ada edge ke node hantu)", () => {
  const r = filterGraph(NODES, LINKS, "File", "");
  // f1-s1 dan f2-s1 hilang karena s1 bukan File; f1-d1 hilang karena d1 bukan File
  assert.deepEqual(r.links, []);
});

test("edge dengan kedua ujung lolos tetap ada", () => {
  const r = filterGraph(NODES, LINKS, "All", "auth");
  assert.deepEqual(r.links.map((l) => `${l.relationship}`).sort(), ["DOCUMENTS"]);
});

test("query tidak ada hasil: hanya operation yang selamat, edge kosong", () => {
  const r = filterGraph(NODES, LINKS, "All", "tidak-ada-sama-sekali");
  assert.deepEqual(r.nodes.map((n) => n.id), ["o1"]);
  assert.deepEqual(r.links, []);
});

test("spasi di query di-trim, tidak menggagalkan kecocokan", () => {
  const r = filterGraph(NODES, LINKS, "All", "   db.py   ");
  assert.deepEqual(r.nodes.map((n) => n.id).sort(), ["f2", "o1"]);
});

test("edge dengan endpoint berupa objek (setelah force-graph init) ikut difilter", () => {
  const r = filterGraph(NODES, [{ source: NODES[2], target: NODES[0], relationship: "REFERENCES" }], "File", "");
  assert.deepEqual(r.links, []);
});

// --- Regresi: #1 di produksi. force-graph menulis ulang link.source/target jadi
// undefined kalau node-nya hilang, lalu filterGraph meledak di endId(). ---

test("edge dengan source undefined dibuang, tidak melempar", () => {
  const broken = [{ source: undefined, target: "s1", relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, broken, "All", "");
  assert.deepEqual(r.links, []);
});

test("edge dengan target undefined dibuang, tidak melempar", () => {
  const broken = [{ source: "f1", target: undefined, relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, broken, "All", "");
  assert.deepEqual(r.links, []);
});

test("edge dengan kedua ujung undefined dibuang, tidak melempar", () => {
  const broken = [{ source: undefined, target: undefined, relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, broken, "All", "");
  assert.deepEqual(r.links, []);
});

test("edge null dibuang, tidak melempar", () => {
  const broken = [null, { source: "f1", target: "s1", relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, broken, "All", "");
  assert.deepEqual(r.links.length, 1);
});

test("edge dengan id yang tidak ada di nodes (yatim) dibuang", () => {
  const orphan = [{ source: "f1", target: "hantu", relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, orphan, "All", "");
  assert.deepEqual(r.links, []);
});

test("endpoint objek tanpa field id dibuang, tidak melempar", () => {
  const noId = [{ source: {}, target: NODES[0], relationship: "REFERENCES" }] as unknown as GraphLink[];
  const r = filterGraph(NODES, noId, "All", "");
  assert.deepEqual(r.links, []);
});

test("edge rusak tidak merusak node yang sehat", () => {
  const broken = [
    { source: undefined, target: "s1", relationship: "REFERENCES" },
    { source: "f1", target: "s1", relationship: "REFERENCES" },
  ] as unknown as GraphLink[];
  const r = filterGraph(NODES, broken, "All", "");
  assert.equal(r.nodes.length, 5);
  assert.equal(r.links.length, 1);
});
