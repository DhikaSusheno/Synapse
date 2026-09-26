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
    Buat demo SQLite DB di db_path.
    Insert seed data minimal yang dibutuhkan test DR6b:
      - file node: file::app/models.py
      - symbol nodes: User, Post (IMPLEMENTED_BY file::app/models.py)
      - edges IMPLEMENTED_BY dari file ke simbol
    Return Path(db_path).
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DDL)

    # Seed nodes
    seed_nodes = [
        ("file::app/models.py",        "file",   "app/models.py",  '{}'),
        ("file::app/routes.py",        "file",   "app/routes.py",  '{}'),
        ("file::app/services.py",      "file",   "app/services.py",'{"lang": "python"}'),
        ("symbol::app/models.py::User","symbol", "User",           '{"kind": "class", "file": "app/models.py", "line": 5, "complexity": 1}'),
        ("symbol::app/models.py::Post","symbol", "Post",           '{"kind": "class", "file": "app/models.py", "line": 20, "complexity": 1}'),
        ("symbol::app/routes.py::get_users", "symbol", "get_users", '{"kind": "function", "file": "app/routes.py", "line": 10, "complexity": 3}'),
        ("symbol::app/services.py::create_user", "symbol", "create_user", '{"kind": "function", "file": "app/services.py", "line": 8, "complexity": 4}'),
        ("doc::README.md",             "doc",    "README.md",      '{}'),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO nodes (id, type, name, meta_json) VALUES (?, ?, ?, ?)",
        seed_nodes
    )

    # Seed edges
    # DR6b test: query IMPLEMENTED_BY dengan target_id = 'file::app/models.py'
    # harus return >= 2 hasil → edge dari file ke symbol (source=file, target=symbol)
    seed_edges = [
        ("e1", "file::app/models.py", "symbol::app/models.py::User",        "IMPLEMENTED_BY", 1.0),
        ("e2", "file::app/models.py", "symbol::app/models.py::Post",        "IMPLEMENTED_BY", 1.0),
        ("e3", "file::app/routes.py", "symbol::app/routes.py::get_users",   "IMPLEMENTED_BY", 1.0),
        ("e4", "file::app/services.py", "symbol::app/services.py::create_user", "IMPLEMENTED_BY", 1.0),
        ("e5", "doc::README.md",      "file::app/models.py",                "DOCUMENTS",      0.9),
        ("e6", "doc::README.md",      "file::app/routes.py",                "DOCUMENTS",      0.8),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO edges (id, source_id, target_id, relationship, confidence) VALUES (?, ?, ?, ?, ?)",
        seed_edges
    )

    conn.commit()
    conn.close()
    return db_path
