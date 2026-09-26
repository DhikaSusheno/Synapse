"""
database.py — Skema storage Synapse LEGACY (v1) sesuai SYNAPSE.md 4.2.

Skema v2 (entities / relations / actions / decisions / audit_log) ada di
storage.py dan SENGAJA TIDAK digabung di sini:

    modul         file DB          tabel
    ------------   --------------   ------------------------------------------
    database.py   synapse.db       nodes, edges, operations, approvals  (v1)
    storage.py    synapse_v2.db    entities, relations, actions,
                                   decisions, audit_log                 (v2)

Kedua skema hidup berdampingan di file BERBEDA, jadi:
  - init_db() di bawah hanya menyentuh tabel v1; cortex.py, guardian.py, dan
    seluruh test suite tetap querying nodes/edges/operations/approvals apa adanya
  - tidak ada FK atau INDEX silang antar skema
  - v1 -> v2 adalah migrasi yang harus dijadwalkan eksplisit (nama tabel dan
    kolom berubah, dan beberapa nilai status berubah: executing->running,
    executed_unverified->done_unverified, rolled_back->reverted,
    approvals.decision 'denied' -> decisions.result 'rejected')

Override path v2 lewat env var SYNAPSE_DB_PATH (lihat storage.py).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("synapse.db")

# GLITCH-4: get_conn() (thread-local connection) DIHAPUS. Fungsi itu dead code
# — tidak pernah dipanggil dari guardian.py maupun cortex.py, keduanya membuka
# koneksi sendiri per unit kerja. Menghapusnya karena:
#   - koneksi thread-local mengunci DB_PATH saat koneksi pertama dibuat, sehingga
#     override database.DB_PATH di test (conftest.py, test_bugfix.py) jadi bocor
#   - tidak ada connection.close(), jadi koneksi tidak pernah dilepas
# Guardian memakai _db_path() yang membaca DB_PATH ulang tiap panggilan;
# itulah yang membuat test override tetap bekerja.


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
