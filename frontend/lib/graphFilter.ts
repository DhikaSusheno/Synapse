// lib/graphFilter.ts
// Filter graph berdasarkan tipe node + pencarian teks.
// Dipisah dari komponen supaya bisa diuji tanpa render (lihat graphFilter.test.ts).
//
// ponytail: TIDAK menyaring node bertipe "operation". Node itu adalah state
// machine operasi yang sedang berjalan - menyembunyikannya saat user mengetik
// filter membuat status Approved/executing hilang dan rollback jadi tak terlihat.
// Kalau nanti memang mau ikut filter operation, ubah di sini + tambah test.

import type { GraphNode, GraphLink } from "./types";

export const NODE_TYPE_FILTERS = ["All", "File", "Symbol", "Dependency", "Doc"] as const;
export type NodeTypeFilter = (typeof NODE_TYPE_FILTERS)[number];

const TYPE_MAP: Record<Exclude<NodeTypeFilter, "All">, GraphNode["type"]> = {
  File: "file",
  Symbol: "symbol",
  Dependency: "dependency",
  Doc: "doc",
};

function endId(end: string | GraphNode): string {
  return typeof end === "string" ? end : end.id;
}

export function filterGraph(
  nodes: GraphNode[],
  links: GraphLink[],
  type: NodeTypeFilter,
  query: string
): { nodes: GraphNode[]; links: GraphLink[] } {
  const q = query.trim().toLowerCase();
  const wanted = type === "All" ? null : TYPE_MAP[type];

  const keep = nodes.filter((n) => {
    // Node operasi selalu ikut, apa pun filter-nya.
    if (n.type === "operation") return true;
    if (wanted && n.type !== wanted) return false;
    if (!q) return true;
    return n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q);
  });

  const keptIds = new Set(keep.map((n) => n.id));
  // Edge yang salah satu ujungnya tersaring harus ikut hilang, kalau tidak
  // force-graph akan menggambar edge menuju node yang tidak ada.
  const keptLinks = links.filter((l) => keptIds.has(endId(l.source)) && keptIds.has(endId(l.target)));

  return { nodes: keep, links: keptLinks };
}
