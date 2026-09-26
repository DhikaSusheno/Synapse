// lib/mockData.ts
// Data mock untuk development sebelum backend SSE siap.
// Struktur ini HARUS sesuai dengan skema SQLite backend (SYNAPSE.md 4.2).

import type { GraphNode, GraphLink } from "./types";

export const MOCK_NODES: GraphNode[] = [
  // === DOKUMEN ===
  { id: "doc::README.md",       name: "README.md",         type: "doc",        status: "idle" },
  { id: "doc::SYNAPSE.md",      name: "SYNAPSE.md",        type: "doc",        status: "idle" },
  { id: "doc::backend/PRD.md",  name: "backend/PRD.md",    type: "doc",        status: "idle" },

  // === FILE KODE ===
  { id: "file::backend/main.py",      name: "main.py",      type: "file", status: "idle" },
  { id: "file::backend/database.py",  name: "database.py",  type: "file", status: "idle" },
  { id: "file::backend/cortex.py",    name: "cortex.py",    type: "file", status: "idle" },

  // === SIMBOL / FUNGSI ===
  { id: "symbol::main.py::understand_repo", name: "understand_repo()", type: "symbol", status: "idle" },
  { id: "symbol::main.py::explain_topic",   name: "explain_topic()",   type: "symbol", status: "idle" },
  { id: "symbol::main.py::stream_events",   name: "stream_events()",   type: "symbol", status: "idle" },
  { id: "symbol::cortex.py::repo_health",   name: "repo_health()",     type: "symbol", status: "idle" },
  { id: "symbol::cortex.py::find_path",     name: "find_path()",       type: "symbol", status: "idle" },
  { id: "symbol::database.py::init_db",     name: "init_db()",         type: "symbol", status: "idle" },

  // === DEPENDENSI ===
  { id: "dep::fastapi",    name: "fastapi",     type: "dependency", status: "idle" },
  { id: "dep::sqlite3",    name: "sqlite3",     type: "dependency", status: "idle" },
  { id: "dep::networkx",   name: "networkx",    type: "dependency", status: "idle" },
  { id: "dep::tree-sitter",name: "tree-sitter", type: "dependency", status: "idle" },

  // === OPERASI (node yang akan pulse saat live) ===
  {
    id: "op::migrate-001",
    name: "db.run_migration",
    type: "operation",
    status: "pending",
    meta: { blast_radius: "high", requires_approval: true },
  },
  {
    id: "op::migrate-002",
    name: "db.run_migration (conflict)",
    type: "operation",
    status: "idle",
    meta: { blast_radius: "high", requires_approval: true, conflicts: ["op::migrate-001"] },
  },
];

export const MOCK_LINKS: GraphLink[] = [
  // Dokumen menjelaskan kode
  { source: "doc::README.md",      target: "file::backend/main.py",    relationship: "DOCUMENTS" },
  { source: "doc::SYNAPSE.md",     target: "file::backend/database.py",relationship: "DOCUMENTS" },
  { source: "doc::backend/PRD.md", target: "symbol::main.py::understand_repo", relationship: "EXPLAINS" },
  { source: "doc::backend/PRD.md", target: "symbol::main.py::stream_events",   relationship: "EXPLAINS" },

  // File mengandung simbol
  { source: "file::backend/main.py",     target: "symbol::main.py::understand_repo", relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/main.py",     target: "symbol::main.py::explain_topic",   relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/main.py",     target: "symbol::main.py::stream_events",   relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/cortex.py",   target: "symbol::cortex.py::repo_health",   relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/cortex.py",   target: "symbol::cortex.py::find_path",     relationship: "IMPLEMENTED_BY" },
  { source: "file::backend/database.py", target: "symbol::database.py::init_db",     relationship: "IMPLEMENTED_BY" },

  // Referensi ke dependency
  { source: "file::backend/main.py",     target: "dep::fastapi",     relationship: "REFERENCES" },
  { source: "file::backend/database.py", target: "dep::sqlite3",     relationship: "REFERENCES" },
  { source: "file::backend/cortex.py",   target: "dep::networkx",    relationship: "REFERENCES" },
  { source: "file::backend/cortex.py",   target: "dep::tree-sitter", relationship: "REFERENCES" },

  // Operasi menarget file
  { source: "op::migrate-001",                    target: "file::backend/database.py",      relationship: "TARGETS" },
  { source: "op::migrate-002",                    target: "file::backend/database.py",      relationship: "TARGETS" },
  { source: "op::migrate-002",                    target: "op::migrate-001",                relationship: "CONFLICTS_WITH" },
  { source: "symbol::main.py::understand_repo",   target: "symbol::cortex.py::repo_health", relationship: "REFERENCES" },
];

// Urutan perubahan status untuk simulasi demo (dipakai oleh useMockSimulation)
// Skenario: migrate-001 sukses, migrate-002 conflict → failed → rolled_back → pulih
export const MOCK_TIMELINE: Array<{ delayMs: number; nodeId: string; status: GraphNode["status"] }> = [
  // Skenario 1: operasi normal
  { delayMs: 2000,  nodeId: "op::migrate-001", status: "approved"  },
  { delayMs: 4000,  nodeId: "op::migrate-001", status: "executing" },
  { delayMs: 7000,  nodeId: "op::migrate-001", status: "verified"  },

  // Skenario 2: operasi dengan konflik → failed → rolled_back
  { delayMs: 9000,  nodeId: "op::migrate-002", status: "pending"   },
  { delayMs: 11000, nodeId: "op::migrate-002", status: "approved"  },
  { delayMs: 13000, nodeId: "op::migrate-002", status: "executing" },
  { delayMs: 15000, nodeId: "op::migrate-002", status: "failed"    },
  { delayMs: 16500, nodeId: "op::migrate-002", status: "rolled_back" },
  // Auto-pulih ke verified setelah rollback selesai (merah berkedip → hijau)
  { delayMs: 20000, nodeId: "op::migrate-002", status: "verified"  },
];
