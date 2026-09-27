// lib/graphEdges.ts
// Normalisasi sisi graph dari backend jadi GraphLink untuk force-graph.
//
// Dipisah dari komponen supaya bisa diuji tanpa render (lihat graphEdges.test.ts).
//
// BUG yang diperbaiki di sini: backend /graph/edges mengirim field
// "source"/"target" (lihat docstring engine.get_graph_edges), tapi filter di
// SynapseGraph.tsx dulu mencari "source_id"/"target_id" - itu nama kolom di
// tabel `relations`, bukan nama JSON. Akibatnya SEMUA edge terbuang diam-diam:
// graph tampil dengan 1096 node tapi 0 edge, tanpa error, tanpa request gagal.
// Perbaikannya: nama field dinormalkan di satu tempat, dan test mengunci
// kontrak ini supaya tidak bisa regresi diam-diam lagi.

import type { GraphLink } from "./types";

/**
 * Bentuk edge dari backend. Semua field opsional karena bentuknya berbeda
 * antar sumber: route handler /api/graph dan SSE tidak selalu sama.
 *
 * "source"/"target"  - bentuk yang benar-benar dikirim engine.get_graph_edges()
 * "source_id"/"target_id" - bentuk lama; diterima supaya payload lama/berubah
 *                       tidak membuat graph kosong total tanpa penjelasan.
 */
export interface BackendEdge {
  source?: string;
  target?: string;
  source_id?: string;
  target_id?: string;
  relationship?: GraphLink["relationship"];
  confidence?: number;
}

/**
 * Normalkan satu edge backend jadi GraphLink, atau null kalau tidak bisa.
 *
 * Null lebih baik daripada edge setengah jadi: react-force-graph-2d menulis
 * ulang link.source/link.target di tempat dan mengisinya `undefined` kalau
 * node ujung tidak ada, yang lalu menjadi bom waktu di filterGraph.
 */
export function normalEdge(raw: BackendEdge | null | undefined): GraphLink | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw.source ?? raw.source_id;
  const target = raw.target ?? raw.target_id;
  if (typeof source !== "string" || typeof target !== "string") return null;
  if (source === "" || target === "") return null;
  return {
    source,
    target,
    // Edge tanpa relationship tetap ditampilkan, bukan dibuang. Default
    // DEPENDS_ON supaya warna legend (getLinkColor) punya nilai yang dikenal.
    relationship: (raw.relationship ?? "DEPENDS_ON") as GraphLink["relationship"],
  };
}

/** Bentuk singkat untuk.map(...).filter(...). */
export function normalEdges(raw: unknown): GraphLink[] {
  if (!Array.isArray(raw)) return [];
  const out: GraphLink[] = [];
  for (const item of raw as BackendEdge[]) {
    const link = normalEdge(item);
    if (link) out.push(link);
  }
  return out;
}
