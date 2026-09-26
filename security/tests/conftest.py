"""
conftest.py — shared fixtures untuk semua test QC-1 (pidpid35)

Strategi:
- Semua test pakai DB SQLite in-memory (:memory:) via monkeypatching database.DB_PATH
  agar tidak mencemari synapse.db yang sedang berjalan.
- guardian di-import setelah DB di-patch supaya setiap test mulai dari state bersih.
"""
import sqlite3
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Pastikan folder backend ada di path
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
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
    Buat SQLite file sementara di tmp_path, jalankan DDL,
    dan patch database.DB_PATH + semua sqlite3.connect di guardian
    agar menunjuk ke file tersebut.
    Return path file DB (pathlib.Path).
    """
    db_file = tmp_path / "test_synapse.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(DDL)
    conn.commit()
    conn.close()
    return db_file


@pytest.fixture()
def guardian_module(mem_db):
    """
    Import guardian dengan DB_PATH di-patch ke mem_db.
    Setiap test dapat modul yang bersih.
    """
    # Patch sebelum import supaya guardian.DB_PATH ikut terupdate
    import database as db_mod
    original_path = db_mod.DB_PATH
    db_mod.DB_PATH = mem_db

    # Reload guardian agar _emit tidak memanggil queue asli
    import importlib
    import guardian as g
    # Patch _emit agar tidak butuh SSE queue
    g._emit = MagicMock()
    importlib.reload(g)
    g._emit = MagicMock()

    yield g

    # Teardown
    db_mod.DB_PATH = original_path
