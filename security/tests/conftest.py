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
    # Skema diambil dari database.SCHEMA, bukan dari salinan di sini. Salinan
    # parsial pernah tertinggal dua kali: menambah operations.target_id ->
    # "no such column", dan menambah tabel kontrak -> invariant
    # db_schema_tables_exist menolak hasil test karena sandbox tidak punya
    # github_connections/repo_refs/llm_providers/project_llm_configs.
    conn.executescript(DDL)
    conn.executescript(db_mod.SCHEMA)
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
