"""
storage.py — Skema storage Synapse (knowledge graph) + koneksi thread-local.

Berbeda dengan database.py (schema legacy v1: nodes/edges/operations/approvals),
modul ini memakai schema v2 dengan penamaan yang lebih eksplisit:

    nodes      -> entities      (+ kind, label, attributes_json, version)
    edges      -> relations     (from_id/to_id, relation_type, weight)
    operations -> actions       (impact_scope, reversibility, status, revert_command)
    approvals  -> decisions     (result, reason)
    (baru)                    -> audit_log

Kolom version di entities dipakai untuk tracking re-ingest: ketika isi sebuah
file berubah, version naik dan attributes_json diperbarui, sehingga simpul lama
bisa diinvalidasi lewat perbandingan version.

Path DB: file TERPISA dari schema legacy. Default Path("synapse_v2.db") supaya
tidak bentrok dengan database.py yang memakai Path("synapse.db") — dua skema
berdampingan di file berbeda, tanpa FK/INDEX silang. Override via env var:

    SYNAPSE_DB_PATH=/tmp/synapse-test.db pytest
"""

import os
import sqlite3
import threading
import uuid
from pathlib import Path

# Default punya file sendiri, sengaja tidak "synapse.db" (dipakai database.py).
DB_PATH = Path(os.environ.get("SYNAPSE_DB_PATH", "synapse_v2.db"))

# Koneksi per-thread: FastAPI menjalankan sync endpoint di threadpool, dan
# sqlite3.Connection tidak aman dipakai lintas thread. Setiap thread punya
# koneksinya sendiri; _local.conn dibuat lazily pada pemakaian pertama.
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """
    Ambil koneksi SQLite milik thread pemanggil, buat bila belum ada.

    PERHATIAN: koneksi di-cache per thread dan TIDAK pernah di-close(), jadi:
      - DB_PATH dibaca hanya saat koneksi pertama dibuat. Kalau DB_PATH diganti
        setelah itu, thread tersebut masih memakai path lama.
      - override di test harus dilakukan SEBELUM get_conn() dipanggil, atau
        panggil reset_conn() lebih dulu.
    Untuk pemakaian yang butuh path dinamis, buka koneksi sendiri via
    sqlite3.connect(path) seperti guardian.py lakukan.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def reset_conn() -> None:
    """Tutup & lepas koneksi thread ini (dipakai test / ganti DB_PATH)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _local.conn = None


SCHEMA = """
-- Simpul graph. 'kind' menggantikan type, 'label' menggantikan name.
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,   -- file | symbol | dependency | doc | action
    label           TEXT NOT NULL,
    attributes_json TEXT DEFAULT '{}',
    version         INTEGER DEFAULT 1,   -- naik saat re-ingest
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Sisi graph. 'weight' menggantikan confidence.
CREATE TABLE IF NOT EXISTS relations (
    id            TEXT PRIMARY KEY,
    from_id       TEXT NOT NULL,
    to_id         TEXT NOT NULL,
    relation_type TEXT NOT NULL,   -- DOCUMENTS | EXPLAINS | REFERENCES
                                   -- | IMPLEMENTED_BY | TARGETS
                                   -- | CONFLICTS_WITH | ROLLED_BACK_BY
                                   -- | DEPENDS_ON
    weight        REAL DEFAULT 1.0,
    created_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_id) REFERENCES entities(id),
    FOREIGN KEY (to_id)   REFERENCES entities(id)
);

-- Operasi berisiko yang diawasi Guardian.
CREATE TABLE IF NOT EXISTS actions (
    id                TEXT PRIMARY KEY,
    tool_name         TEXT NOT NULL,
    params_json       TEXT DEFAULT '{}',
    target_entity_id  TEXT,
    impact_scope      TEXT DEFAULT 'unknown',   -- unknown | low | medium | high
    reversibility     TEXT DEFAULT 'unknown',   -- unknown | irreversible_suspected
                                                  -- | needs_snapshot | reversible
    status            TEXT DEFAULT 'pending',   -- pending | approved | running
                                                  -- | done_unverified | verified
                                                  -- | failed | reverted
    snapshot_ref      TEXT,
    revert_command    TEXT,
    needs_approval    INTEGER DEFAULT 1,
    created_at        TEXT DEFAULT (datetime('now')),
    started_at        TEXT,
    finished_at       TEXT,
    verified_at       TEXT
);

-- Keputusan manusia atas sebuah action.
CREATE TABLE IF NOT EXISTS decisions (
    action_id  TEXT PRIMARY KEY,
    result     TEXT NOT NULL,   -- approved | rejected
    decided_at TEXT DEFAULT (datetime('now')),
    reason     TEXT DEFAULT '',
    FOREIGN KEY (action_id) REFERENCES actions(id)
);

-- Jejak audit untuk observability perubahan data penting.
CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    entity_id   TEXT,
    event       TEXT NOT NULL,
    detail_json TEXT DEFAULT '{}',
    ts          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entities_kind        ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_relations_from       ON relations(from_id);
CREATE INDEX IF NOT EXISTS idx_relations_to         ON relations(to_id);
CREATE INDEX IF NOT EXISTS idx_relations_type       ON relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_actions_status       ON actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_target       ON actions(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity         ON audit_log(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts             ON audit_log(ts);
"""


def init_db() -> None:
    """Buat semua tabel & index di atas jika belum ada (idempoten)."""
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate_engine_columns(conn)
    print("[storage] Schema v2 siap di", DB_PATH)


# ---------------------------------------------------------------------------
# Kolom metrics untuk engine.py
# ---------------------------------------------------------------------------
# attributes_json tetap jadi sumber kebenaran (satu blob JSON), tapi kolom di
# bawah adalah proyeksi yang bisa di-QUERY. engine.py butuh
# rank_complexity() dan health_report() menyaring berdasarkan kompleksitas;
# memfilter JSON di Python berarti scan seluruh tabel tiap request.

_ENGINE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("complexity",   "INTEGER DEFAULT 0"),   # cyclomatic complexity (McCabe approx)
    ("line_start",   "INTEGER DEFAULT 0"),   # baris 1-based dalam file
    ("line_count",   "INTEGER DEFAULT 0"),
    ("parent_id",    "TEXT"),                # file::rel untuk kind='symbol'
    ("symbol_kind",  "TEXT"),                # function | class | import
    ("source_path",  "TEXT"),                # path relatif, untuk ambil snippet
)

_ENGINE_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_entities_complexity ON entities(complexity)",
    "CREATE INDEX IF NOT EXISTS idx_entities_parent     ON entities(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_entities_label      ON entities(label)",
    "CREATE INDEX IF NOT EXISTS idx_entities_symbolkind ON entities(symbol_kind)",
)


def _migrate_engine_columns(conn: sqlite3.Connection) -> None:
    """
    Tambah kolom metrics ke tabel entities yang dibuat sebelum engine.py ada.

    CREATE TABLE IF NOT EXISTS tidak mengubah tabel yang sudah ada, jadi DB
    yang dibuat sebelum kolom ini ada tetap perlu ALTER. Dijalankan setiap
    init_db() dan idempoten (sudah ada -> lewati).
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(entities)")}
    added = False
    for col, ddl in _ENGINE_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE entities ADD COLUMN {col} {ddl}")
            added = True
    for idx in _ENGINE_INDEXES:
        conn.execute(idx)
    if added:
        conn.commit()


def upsert_entity(
    entity_id: str,
    kind: str,
    label: str,
    attributes: dict | None = None,
    *,
    complexity: int = 0,
    line_start: int = 0,
    line_count: int = 0,
    parent_id: str | None = None,
    symbol_kind: str | None = None,
    source_path: str | None = None,
) -> bool:
    """
    Tulis satu entity. Kembalikan True kalau kontennya berubah (version naik).

    Versi hanya naik bila label/attributes_json benar-benar berbeda, supaya
    re-ingest repo yang tidak berubah tidak membikin version melonjak terus.
    """
    import json

    payload = json.dumps(attributes or {}, sort_keys=True)
    conn = get_conn()
    row = conn.execute(
        "SELECT label, attributes_json FROM entities WHERE id=?", (entity_id,)
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO entities
                   (id, kind, label, attributes_json, complexity, line_start,
                    line_count, parent_id, symbol_kind, source_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, kind, label, payload, complexity, line_start,
             line_count, parent_id, symbol_kind, source_path),
        )
        conn.commit()
        return True

    if row["label"] == label and (row["attributes_json"] or "") == payload:
        # Konten tidak berubah — hanya segarkan kolom metrics (mis. line_start
        # bergeser kalau ada file di atasnya yang berubah) tanpa menaikkan version.
        conn.execute(
            """UPDATE entities
                  SET complexity=?, line_start=?, line_count=?, parent_id=?,
                      symbol_kind=?, source_path=?, updated_at=datetime('now')
                WHERE id=?""",
            (complexity, line_start, line_count, parent_id, symbol_kind,
             source_path, entity_id),
        )
        conn.commit()
        return False

    conn.execute(
        """UPDATE entities
              SET kind=?, label=?, attributes_json=?, version=version+1,
                  complexity=?, line_start=?, line_count=?, parent_id=?,
                  symbol_kind=?, source_path=?, updated_at=datetime('now')
            WHERE id=?""",
        (kind, label, payload, complexity, line_start, line_count, parent_id,
         symbol_kind, source_path, entity_id),
    )
    conn.commit()
    return True


def upsert_relation(
    from_id: str, to_id: str, relation_type: str, weight: float = 1.0
) -> str | None:
    """
    Tulis satu sisi graph. Kembalikan id relasi, atau None kalau tidak valid.

    Dilewati diam-diam kalau salah satu ujung tidak ada sebagai entity, supaya
    ingest tidak gagal utuh gara-gara satu referensi menggantung.
    """
    conn = get_conn()
    for endpoint in (from_id, to_id):
        if conn.execute(
            "SELECT 1 FROM entities WHERE id=?", (endpoint,)
        ).fetchone() is None:
            return None

    rel_id = f"{from_id}::{relation_type}::{to_id}"
    conn.execute(
        """INSERT INTO relations (id, from_id, to_id, relation_type, weight)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET weight=excluded.weight""",
        (rel_id, from_id, to_id, relation_type, weight),
    )
    conn.commit()
    return rel_id


def record_audit(entity_id: str | None, event: str, detail: dict | None = None) -> str:
    """
    Catat satu baris ke audit_log, kembalikan id-nya.

    Dipisah dari init_db() supaya modul tetap berguna tanpa efek samping
    otomatis: pencatatan audit harus keputusan sadar, bukan terjadi diam-diam
    tiap import.
    """
    import json

    audit_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        """INSERT INTO audit_log (id, entity_id, event, detail_json)
           VALUES (?, ?, ?, ?)""",
        (audit_id, entity_id, event, json.dumps(detail or {})),
    )
    conn.commit()
    return audit_id
