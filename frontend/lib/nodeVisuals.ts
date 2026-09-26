// lib/nodeVisuals.ts
// Warna dan ukuran node berdasarkan TYPE dan STATUS.
// Sesuai PRD frontend: pending=kuning, verified=hijau, rolled_back=merah.

import type { GraphNode, NodeType, NodeStatus } from "./types";

// Warna per TYPE (dipakai saat status = idle)
const TYPE_COLOR: Record<NodeType, string> = {
  file:       "#60a5fa", // biru
  symbol:     "#a78bfa", // ungu
  dependency: "#64748b", // abu gelap
  doc:        "#34d399", // hijau muda
  operation:  "#f8fafc", // putih (di-override oleh status)
};

// Warna per STATUS (khusus operation node)
const STATUS_COLOR: Record<NodeStatus, string> = {
  idle:        "#f8fafc",
  pending:     "#fbbf24", // kuning — pulse
  approved:    "#38bdf8", // biru muda — menunggu eksekusi
  executing:   "#fb923c", // oranye — sedang jalan
  verified:    "#22c55e", // hijau — sukses
  failed:      "#ef4444", // merah — gagal
  rolled_back: "#ef4444", // merah (akan pulse lalu hijau di animasi)
};

// Ukuran node (nilai ini menentukan radius lingkaran di canvas)
const TYPE_SIZE: Record<NodeType, number> = {
  file:       5,
  symbol:     4,
  dependency: 3,
  doc:        6,
  operation:  10, // operation selalu paling besar agar menonjol
};

export function getNodeColor(node: GraphNode): string {
  if (node.type === "operation") {
    return STATUS_COLOR[node.status] ?? STATUS_COLOR.idle;
  }
  return TYPE_COLOR[node.type] ?? "#f8fafc";
}

export function getNodeSize(node: GraphNode): number {
  return TYPE_SIZE[node.type] ?? 4;
}

// Label pendek untuk tooltip
export function getNodeLabel(node: GraphNode): string {
  const statusBadge: Partial<Record<NodeStatus, string>> = {
    pending:     " ⏳",
    executing:   " ⚡",
    verified:    " ✅",
    failed:      " ❌",
    rolled_back: " 🔄",
  };
  return `${node.name}${statusBadge[node.status] ?? ""}`;
}

// Warna edge berdasarkan relationship
export function getLinkColor(relationship: string): string {
  const map: Record<string, string> = {
    DOCUMENTS:       "#34d399",
    EXPLAINS:        "#818cf8",
    REFERENCES:      "#475569",
    IMPLEMENTED_BY:  "#3b82f6",
    TARGETS:         "#f59e0b",
    CONFLICTS_WITH:  "#ef4444",
    ROLLED_BACK_BY:  "#f97316",
  };
  return map[relationship] ?? "#334155";
}
