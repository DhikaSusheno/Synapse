"""
database.py — SQLite setup & helpers (Synapse schema sesuai SYNAPSE.md 4.2)
"""
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path("synapse.db")

# Thread-local connection agar aman dipakai di async FastAPI
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    """Buat semua tabel jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS nodes (
        id          TEXT PRIMARY KEY,
        type        TEXT NOT NULL,   -- file | symbol | dependency | doc | operation
        name        TEXT NOT NULL,
        meta_json   TEXT DEFAULT '{}',
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS edges (
        id           TEXT PRIMARY KEY,
        source_id    TEXT NOT NULL,
        target_id    TEXT NOT NULL,
        relationship TEXT NOT NULL,  -- DOCUMENTS | EXPLAINS | REFERENCES | IMPLEMENTED_BY
                                     -- | TARGETS | CONFLICTS_WITH | ROLLED_BACK_BY
        confidence   REAL DEFAULT 1.0,
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (source_id) REFERENCES nodes(id),
        FOREIGN KEY (target_id) REFERENCES nodes(id)
    );

    CREATE TABLE IF NOT EXISTS operations (
        id                   TEXT PRIMARY KEY,
        tool_name            TEXT NOT NULL,
        params_json          TEXT DEFAULT '{}',
        target_node_id       TEXT,
        blast_radius         TEXT DEFAULT 'unknown',
        reversibility_class  TEXT DEFAULT 'irreversible_suspected',
        status               TEXT DEFAULT 'pending',  -- pending|approved|executing|executed_unverified|verified|failed|rolled_back
        snapshot_ref         TEXT,
        rollback_command     TEXT,
        requires_approval    INTEGER DEFAULT 1,
        created_at           TEXT DEFAULT (datetime('now')),
        executed_at          TEXT,
        verified_at          TEXT
    );

    CREATE TABLE IF NOT EXISTS approvals (
        operation_id TEXT PRIMARY KEY,
        decision     TEXT NOT NULL,   -- approved | denied
        decided_at   TEXT DEFAULT (datetime('now')),
        note         TEXT DEFAULT ''
    );
    """)

    conn.commit()
    conn.close()
    print("[DB] Schema initialised at", DB_PATH)
