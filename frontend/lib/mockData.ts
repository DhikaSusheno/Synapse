// lib/mockData.ts
// Data mock untuk development sebelum backend SSE siap.
// Struktur sesuai skema SQLite backend (SYNAPSE.md 4.2).
// Demo timeline disesuaikan dengan demo_migration_script.py (6 skenario).

import type { GraphNode, GraphLink } from "./types";

export const MOCK_NODES: GraphNode[] = [
  // === DOKUMEN ===
  { id: "doc::README.md",       name: "README.md",         type: "doc",        status: "idle" },
  { id: "doc::SYNAPSE.md",      name: "SYNAPSE.md",        type: "doc",        status: "idle" },
  { id: "doc::backend/PRD.md",  name: "backend/PRD.md",    type: "doc",        status: "idle" },

  // === FILE KODE ===
  { id: "file::backend/main.py",      name: "main.py",      type: "file", status: "idle" },
  { id: "file::backend/database.py",  name: "database.py",  type: "file", status: "idle" },
  { id: "file::backend/guardian.py",  name: "guardian.py",  type: "file", status: "idle" },
  { id: "file::backend/cortex.py",    name: "cortex.py",    type: "file", status: "idle" },

  // === SIMBOL / FUNGSI ===
  { id: "symbol::main.py::understand_repo", name: "understand_repo()", type: "symbol", status: "idle" },
  { id: "symbol::main.py::explain_topic",   name: "explain_topic()",   type: "symbol", status: "idle" },
  { id: "symbol::main.py::stream_events",   name: "stream_events()",   type: "symbol", status: "idle" },
  { id: "symbol::guardian.py::propose_operation",  name: "propose_operation()",  type: "symbol", status: "idle" },
  { id: "symbol::guardian.py::execute_operation",  name: "execute_operation()",  type: "symbol", status: "idle" },
  { id: "symbol::cortex.py::repo_health",   name: "repo_health()",     type: "symbol", status: "idle" },
  { id: "symbol::database.py::init_db",     name: "init_db()",         type: "symbol", status: "idle" },

  // === DEPENDENSI ===
  { id: "dep::fastapi",    name: "fastapi",     type: "dependency", status: "idle" },
  { id: "dep::sqlite3",    name: "sqlite3",     type: "dependency", status: "idle" },
  { id: "dep::networkx",   name: "networkx",    type: "dependency", status: "idle" },
  { id: "dep::tree-sitter",name: "tree-sitter", type: "dependency", status: "idle" },

  // === OPERASI — 3 skenario demo sesuai demo_migration_script.py ===
  // Skenario 1: migration sukses (tambah kolom 'tag')
  {
    id: "op::migrate-tag",
    name: "db.run_migration (add tag)",
    type: "operation",
    status: "pending",
    meta: { blast_radius: "high", requires_approval: true, target: "synapse.db::nodes" },
  },
  // Skenario 2: migration konflik (target sama)
  {
    id: "op::migrate-priority",
    name: "db.run_migration (conflict)",
    type: "operation",
    status: "idle",
    meta: { blast_radius: "high", requires_approval: true, conflicts: ["op::migrate-tag"], target: "synapse.db::nodes" },
  },
  // Skenario 3: migration gagal → rollback
  {
    id: "op::migrate-broken",
    name: "db.run_migration (broken SQL)",
    type: "operation",
    status: "idle",
    meta: { blast_radius: "high", requires_approval: true, target: "synapse.db::broken_target" },
  },
];

export const MOCK_LINKS: GraphLink[] = [
  // Dokumen menjelaskan kode
  { source: "doc::README.md",      target: "file::backend/main.py",      relationship: "DOCUMENTS" },
  { source: "doc::SYNAPSE.md",     target: "file::backend/database.py",  relationship: "DOCUMENTS" },
  { source: "doc::SYNAPSE.md",     target: "file::backend/guardian.py",  relationship: "DOCUMENTS" },
  { source: "doc::backend/PRD.md", target: "symbol::main.py::understand_repo", relationship: "EXPLAINS" },
  { source: "doc::backend/PRD.md", target: "symbol::guardian.py::propose_operation", relationship: "EXPLAINS" },

  // File mengandung simbol
  { source: "file::backend/main.py",     target: "symbol::main.py::understand_repo",         relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/main.py",     target: "symbol::main.py::explain_topic",            relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/main.py",     target: "symbol::main.py::stream_events",            relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/guardian.py", target: "symbol::guardian.py::propose_operation",   relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/guardian.py", target: "symbol::guardian.py::execute_operation",   relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/cortex.py",   target: "symbol::cortex.py::repo_health",           relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/database.py", target: "symbol::database.py::init_db",             relationship: "IMPLEMENTED_BY" },

  // Referensi ke dependency
  { source: "file::backend/main.py",     target: "dep::fastapi",     relationship: "REFERENCES" },
  { source: "file::backend/database.py", target: "dep::sqlite3",     relationship: "REFERENCES" },
  { source: "file::backend/cortex.py",   target: "dep::networkx",    relationship: "REFERENCES" },
  { source: "file::backend/cortex.py",   target: "dep::tree-sitter", relationship: "REFERENCES" },

  // Operasi menarget file
  { source: "op::migrate-tag",      target: "file::backend/database.py", relationship: "TARGETS" },
  { source: "op::migrate-priority", target: "file::backend/database.py", relationship: "TARGETS" },
  { source: "op::migrate-broken",   target: "file::backend/database.py", relationship: "TARGETS" },
  // Konflik antar operasi
  { source: "op::migrate-priority", target: "op::migrate-tag",           relationship: "CONFLICTS_WITH" },
  // Relasi internal
  { source: "symbol::main.py::understand_repo", target: "symbol::cortex.py::repo_health",          relationship: "REFERENCES" },
  { source: "symbol::guardian.py::propose_operation", target: "symbol::guardian.py::execute_operation", relationship: "REFERENCES" },
];

// =============================================================================
// Demo timeline — 6 skenario sesuai demo_migration_script.py
// =============================================================================
export const MOCK_TIMELINE: Array<{
  delayMs: number;
  nodeId: string;
  status: GraphNode["status"];
}> = [
  // --- Skenario 1: migration sukses (add column 'tag') ---
  { delayMs: 1500,  nodeId: "op::migrate-tag",      status: "approved"   },
  { delayMs: 3000,  nodeId: "op::migrate-tag",      status: "executing"  },
  { delayMs: 5000,  nodeId: "op::migrate-tag",      status: "verified"   },

  // --- Skenario 2: konflik (target sama, dalam window) ---
  { delayMs: 6500,  nodeId: "op::migrate-priority", status: "pending"    },
  // Konflik terdeteksi → tetap pending, butuh approval manual
  // (disimulasikan tidak ada approve → tidak ada executing)

  // --- Skenario 3: migration gagal → auto-rollback ---
  { delayMs: 8000,  nodeId: "op::migrate-broken",   status: "pending"    },
  { delayMs: 9500,  nodeId: "op::migrate-broken",   status: "approved"   },
  { delayMs: 11000, nodeId: "op::migrate-broken",   status: "executing"  },
  { delayMs: 13000, nodeId: "op::migrate-broken",   status: "failed"     },
  { delayMs: 14500, nodeId: "op::migrate-broken",   status: "rolled_back" },
  // Pulih: merah berkedip → hijau (auto setelah rollback selesai)
  { delayMs: 18000, nodeId: "op::migrate-broken",   status: "verified"   },
];
