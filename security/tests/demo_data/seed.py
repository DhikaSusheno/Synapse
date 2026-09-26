"""
seed.py — Demo DB factory untuk Synapse (QC-2 · zuyss)

Membuat SQLite demo DB dengan:
  - Skema lengkap sesuai SYNAPSE.md 4.2 (nodes/edges/operations/approvals)
  - Node contoh: file Python, simbol fungsi, doc README
  - Edge contoh: DOCUMENTS, REFERENCES, IMPLEMENTED_BY
  - Satu operasi `verified` sebelumnya (baseline history)

Cara pakai:
  from security.tests.demo_data.seed import create_demo_db
  db_path = create_demo_db(tmp_path / "demo.db")

Atau langsung dari CLI:
  python security/tests/demo_data/seed.py [output_path]
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
import uuid

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


def create_demo_db(db_path: Path) -> Path:
    """
    Buat demo DB di db_path dengan seed data yang realistis.
    Return db_path (untuk chaining).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(DDL)

    now = datetime.utcnow()
    ts = lambda offset_sec=0: (now + timedelta(seconds=offset_sec)).isoformat()

    # ------------------------------------------------------------------
    # Nodes — merepresentasikan repo Python kecil bernama "app"
    # ------------------------------------------------------------------
    nodes = [
        # File nodes
        ("file::app/main.py",          "file",    "app/main.py",
         '{"path": "app/main.py", "language": "python", "lines": 120}'),
        ("file::app/models.py",        "file",    "app/models.py",
         '{"path": "app/models.py", "language": "python", "lines": 60}'),
        ("file::app/database.py",      "file",    "app/database.py",
         '{"path": "app/database.py", "language": "python", "lines": 45}'),
        # Symbol nodes (functions/classes)
        ("symbol::app/models.py::User",       "symbol", "User",
         '{"kind": "class", "file": "app/models.py", "line": 5}'),
        ("symbol::app/models.py::Post",       "symbol", "Post",
         '{"kind": "class", "file": "app/models.py", "line": 25}'),
        ("symbol::app/main.py::create_user",  "symbol", "create_user",
         '{"kind": "function", "file": "app/main.py", "line": 30}'),
        ("symbol::app/database.py::get_conn", "symbol", "get_conn",
         '{"kind": "function", "file": "app/database.py", "line": 10}'),
        # Doc node
        ("doc::README.md",             "doc",     "README.md",
         '{"sections": ["Overview", "Setup", "API"], "word_count": 350}'),
        # Dependency nodes
        ("dep::fastapi",               "dependency", "fastapi",
         '{"version": "0.111.0", "type": "runtime"}'),
        ("dep::sqlalchemy",            "dependency", "sqlalchemy",
         '{"version": "2.0.30", "type": "runtime"}'),
        # Operation target nodes
        ("operation_target::app.db",   "operation", "app.db",   '{}'),
        ("operation_target::app-svc",  "operation", "app-svc",  '{}'),
    ]

    conn.executemany(
        "INSERT OR IGNORE INTO nodes (id, type, name, meta_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(n[0], n[1], n[2], n[3], ts()) for n in nodes]
    )

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------
    edges = [
        # README documents main.py and models.py
        ("edge::readme-docs-main",    "doc::README.md",
         "file::app/main.py",          "DOCUMENTS",       0.9),
        ("edge::readme-docs-models",  "doc::README.md",
         "file::app/models.py",        "DOCUMENTS",       0.85),
        # main.py references models.py
        ("edge::main-ref-models",     "file::app/main.py",
         "file::app/models.py",        "REFERENCES",      1.0),
        # main.py references database.py
        ("edge::main-ref-db",         "file::app/main.py",
         "file::app/database.py",      "REFERENCES",      1.0),
        # create_user is implemented in main.py
        ("edge::createuser-impl",     "symbol::app/main.py::create_user",
         "file::app/main.py",          "IMPLEMENTED_BY",  1.0),
        # User and Post are implemented in models.py
        ("edge::user-impl",           "symbol::app/models.py::User",
         "file::app/models.py",        "IMPLEMENTED_BY",  1.0),
        ("edge::post-impl",           "symbol::app/models.py::Post",
         "file::app/models.py",        "IMPLEMENTED_BY",  1.0),
        # create_user references User model
        ("edge::createuser-ref-user", "symbol::app/main.py::create_user",
         "symbol::app/models.py::User", "REFERENCES",    0.95),
        # database.py implements get_conn
        ("edge::getconn-impl",        "symbol::app/database.py::get_conn",
         "file::app/database.py",      "IMPLEMENTED_BY",  1.0),
        # models.py depends on sqlalchemy
        ("edge::models-dep-sa",       "file::app/models.py",
         "dep::sqlalchemy",            "REFERENCES",      1.0),
        # main.py depends on fastapi
        ("edge::main-dep-fastapi",    "file::app/main.py",
         "dep::fastapi",               "REFERENCES",      1.0),
    ]

    conn.executemany(
        "INSERT OR IGNORE INTO edges "
        "(id, source_id, target_id, relationship, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(e[0], e[1], e[2], e[3], e[4], ts()) for e in edges]
    )

    # ------------------------------------------------------------------
    # Baseline operation — satu operasi verified (menunjukkan history)
    # Ini dipakai oleh test RB6 dan E2E untuk membuktikan
    # rollback tidak merusak history.
    # ------------------------------------------------------------------
    baseline_op_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT OR IGNORE INTO operations
        (id, tool_name, params_json, target_node_id, blast_radius,
         reversibility_class, status, snapshot_ref, rollback_command,
         requires_approval, created_at, executed_at, verified_at)
        VALUES (?, 'service.restart', '{"service": "app-svc"}',
                'operation_target::app-svc', 'medium', 'needs_snapshot',
                'verified', NULL, NULL, 0, ?, ?, ?)
        """,
        (baseline_op_id, ts(-120), ts(-110), ts(-105))
    )

    conn.commit()
    conn.close()

    return db_path


def get_baseline_node_count(db_path: Path) -> int:
    """Helper: jumlah node setelah seed (untuk assertion di test)."""
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    conn.close()
    return count


def get_baseline_edge_count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    return count


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("synapse_demo.db")
    create_demo_db(output)
    print(f"[seed] Demo DB dibuat di: {output}")
    print(f"[seed] Nodes  : {get_baseline_node_count(output)}")
    print(f"[seed] Edges  : {get_baseline_edge_count(output)}")
    import sqlite3 as _s
    c = _s.connect(str(output))
    ops = c.execute("SELECT id, status, tool_name FROM operations").fetchall()
    print(f"[seed] Ops    : {len(ops)}")
    for op in ops:
        print(f"  [{op[1].upper():15}] {op[2]} (id={op[0][:8]}...)")
    c.close()
