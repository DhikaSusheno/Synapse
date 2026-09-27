"""
conftest.py — shared fixtures untuk semua test QC-1 (pidpid35)

Strategi:
- Semua test pakai DB SQLite file sementara via tmp_path pytest.
- TEST-BUG-3 FIX: gunakan monkeypatch pytest untuk patch DB_PATH agar
  thread-safe dan otomatis di-restore setelah setiap test.
"""
import sqlite3
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Pastikan folder backend ada di path
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------

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


@pytest.fixture()
def mem_db(tmp_path):
    """
    Buat SQLite file sementara di tmp_path, jalankan DDL.
    Return path file DB (pathlib.Path).
    """
    import database as db_mod

    db_file = tmp_path / "test_synapse.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(DDL)
    # DDL di atas adalah SALINAN parsial dari database.py, dan salinan itu
    # pasti akan tertinggal begitu ada kolom baru. Dulu tidak ada yang
    # menghubungkan keduanya, jadi menambah operations.target_id (-> 75 test
    # gagal dengan "no column named target_id"). _add_missing_columns() adalah
    # migrasi yang sama dengan yang dijalankan init_db(), jadi mengedit DDL
    # saja tidak cukup - dan tidak perlu lagi.
    db_mod._add_missing_columns(conn)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture()
def guardian_module(mem_db, monkeypatch):
    """
    TEST-BUG-3 FIX: gunakan monkeypatch pytest untuk patch DB_PATH.
    monkeypatch otomatis di-restore setelah setiap test, thread-safe,
    dan tidak bergantung pada Python module caching behavior.
    """
    import importlib
    import database as db_mod
    import guardian as g

    # monkeypatch.setattr otomatis di-restore setelah test selesai
    monkeypatch.setattr(db_mod, "DB_PATH", mem_db)

    # Reload guardian agar _db_path() langsung pakai DB_PATH yang sudah di-patch
    importlib.reload(g)
    g._emit = MagicMock()

    yield g
