"""
seed.py — TEST-BUG-1 FIX
Membuat demo SQLite DB dengan schema lengkap + seed data minimal
untuk dipakai oleh test_demo_reliability.py.

Fungsi create_demo_db() dipakai sebagai fixture di test_demo_reliability.py.
"""
import sqlite3
from pathlib import Path

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    meta_json   TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS edges (
    id           TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    relationship TEXT NOT NULL,
    confidence   REAL DEFAULT 1.0,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS operations (
    id                   TEXT PRIMARY KEY,
    tool_name            TEXT NOT NULL,
    params_json          TEXT DEFAULT '{}',
    target_node_id       TEXT,
    blast_radius         TEXT DEFAULT 'unknown',
    reversibility_class  TEXT DEFAULT 'irreversible_suspected',
    status               TEXT DEFAULT 'pending',
    snapshot_ref         TEXT,
    rollback_command     TEXT,
    requires_approval    INTEGER DEFAULT 1,
    created_at           TEXT DEFAULT (datetime('now')),
    executed_at          TEXT,
    verified_at          TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    operation_id TEXT PRIMARY KEY,
    decision     TEXT NOT NULL,
    decided_at   TEXT DEFAULT (datetime('now')),
    note         TEXT DEFAULT ''
);
"""


def create_demo_db(db_path) -> Path:
    """
    Buat demo SQLite DB di db_path dengan seed data lengkap.

    Memenuhi semua kontrak test:
      - E8 : >= 10 nodes
      - E8b: tipe node mencakup file, symbol, doc, dependency, operation
      - DR6b: query IMPLEMENTED_BY dengan target_id='file::app/models.py'
              harus return >= 2 baris (symbol IMPLEMENTED_BY file,
              artinya source=symbol, target=file)

    Return Path(db_path).
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DDL)

    # Seed nodes — 12 nodes mencakup semua tipe yang dibutuhkan E8 + E8b
    seed_nodes = [
        # file nodes (3)
        ("file::app/models.py",   "file",       "app/models.py",   '{"lang": "python"}'),
        ("file::app/routes.py",   "file",       "app/routes.py",   '{"lang": "python"}'),
        ("file::app/services.py", "file",       "app/services.py", '{"lang": "python"}'),
        # symbol nodes (5)
        ("symbol::app/models.py::User",        "symbol", "User",        '{"kind": "class",    "file": "app/models.py",   "line": 5,  "complexity": 1}'),
        ("symbol::app/models.py::Post",        "symbol", "Post",        '{"kind": "class",    "file": "app/models.py",   "line": 20, "complexity": 1}'),
        ("symbol::app/routes.py::get_users",   "symbol", "get_users",   '{"kind": "function", "file": "app/routes.py",   "line": 10, "complexity": 3}'),
        ("symbol::app/services.py::create_user","symbol","create_user", '{"kind": "function", "file": "app/services.py", "line": 8,  "complexity": 4}'),
        ("symbol::app/services.py::delete_user","symbol","delete_user", '{"kind": "function", "file": "app/services.py", "line": 30, "complexity": 2}'),
        # doc nodes (1)
        ("doc::README.md",        "doc",        "README.md",       '{}'),
        # dependency nodes (1) — dibutuhkan E8b
        ("dep::sqlalchemy",       "dependency", "sqlalchemy",      '{"version": "2.0"}'),
        # operation nodes (2) — dibutuhkan E8b
        ("op::baseline-verified", "operation",  "baseline-migrate","{}"),
        ("op::pending-approval",  "operation",  "pending-migrate", '{}'),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO nodes (id, type, name, meta_json) VALUES (?, ?, ?, ?)",
        seed_nodes
    )

    # Seed edges
    # PENTING DR6b: query testnya adalah:
    #   JOIN edges e ON e.source_id = n.id
    #   WHERE e.relationship = 'IMPLEMENTED_BY'
    #     AND e.target_id = 'file::app/models.py'
    # → artinya source=symbol, target=file (symbol IMPLEMENTED_BY file)
    seed_edges = [
        # DR6b: symbol → file (source=symbol, target=file)
        ("e1", "symbol::app/models.py::User",         "file::app/models.py",   "IMPLEMENTED_BY", 1.0),
        ("e2", "symbol::app/models.py::Post",         "file::app/models.py",   "IMPLEMENTED_BY", 1.0),
        ("e3", "symbol::app/routes.py::get_users",    "file::app/routes.py",   "IMPLEMENTED_BY", 1.0),
        ("e4", "symbol::app/services.py::create_user","file::app/services.py", "IMPLEMENTED_BY", 1.0),
        ("e5", "symbol::app/services.py::delete_user","file::app/services.py", "IMPLEMENTED_BY", 1.0),
        # doc → file
        ("e6", "doc::README.md", "file::app/models.py",   "DOCUMENTS", 0.9),
        ("e7", "doc::README.md", "file::app/routes.py",   "DOCUMENTS", 0.8),
        # dependency → file
        ("e8", "dep::sqlalchemy", "file::app/models.py",  "USED_BY",   1.0),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO edges (id, source_id, target_id, relationship, confidence) VALUES (?, ?, ?, ?, ?)",
        seed_edges
    )

    # Seed 1 baseline operation dengan status 'verified' (dibutuhkan test E8 + DR)
    # E8 test cari: tool_name='service.restart' AND status='verified'
    from datetime import datetime
    op_id = "baseline-op-seed-001"
    conn.execute(
        """INSERT OR IGNORE INTO operations
           (id, tool_name, params_json, target_node_id, blast_radius,
            reversibility_class, status, requires_approval, created_at, verified_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (op_id, "service.restart",
         '{"service": "baseline-service"}',
         "file::app/services.py", "medium", "needs_snapshot", "verified",
         0, datetime.utcnow().isoformat(), datetime.utcnow().isoformat())
    )

    conn.commit()
    conn.close()
    return db_path
