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

Override path:
  - v1 (file ini)  : SYNAPSE_DB_PATH_V1
  - v2 (storage.py) : SYNAPSE_DB_PATH

Dua env itu sengaja terpisah. Kalau keduanya memakai nama yang sama, menyetel
satu untuk tes diam-diam akan mengarahkan kedua skema ke file yang sama dan
menghancurkan pemisahan yang dijaga di atas.
"""
import os
import sqlite3
from pathlib import Path

# Path ABSOLUT, di-anchor ke lokasi file ini - bukan ke direktori kerja proses.
#
# Sebelumnya `Path("synapse.db")` bersifat relatif, jadi file DB dibuat di
# tempat uvicorn dijalankan. Konsekuensinya nyata dan sudah dibuktikan:
# menjalankan backend dari repo root vs dari backend/ menghasilkan DUA
# database kosong yang berbeda, sehingga semua data seolah "hilang" hanya
# karena cara server dijalankan. Diverifikasi dengan menjalankan init_db()
# dari dua CWD berbeda.
#
# Di-anchor ke BASE_DIR supaya hasilnya sama dari mana pun server dijalankan.
# Override lewat env SYNAPSE_DB_PATH_V1 (lihat docstring modul).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = Path(
    os.environ.get("SYNAPSE_DB_PATH_V1", "").strip()
    or os.path.join(BASE_DIR, "synapse.db")
)

# Berapa lama koneksi ini menunggu lock writer lain sebelum menyerah.
# Default sqlite3 adalah 0, jadi begitu DB sedang ditulis "database is locked"
# langsung dilempar. guardian.py menjalankan verifikasi integrity saat
# backlog approval, sementara ingest bisa sedang commit pada saat bersamaan.
# Di sini lewat connect() supaya semua caller konsisten.
BUSY_TIMEOUT_MS = 15_000


def _enable_wal(conn: sqlite3.Connection) -> None:
    """
    Set journal_mode=WAL kalau belum, dan telenkan "database is locked".

    Kenapa tidak bisa asal set: PRAGMA journal_mode=WAL butuh lock eksklusif
    sesaat untuk mengubah header file DB, dan lock eksklusif itu tidak
    dihormati busy_timeout - SQLite mengembalikan SQLITE_BUSY seketika. Efeknya
    terlihat saat approve_operation() (guardian) dan ingest menulis bersamaan:
    satu koneksi melempar OperationalError dari PRAGMA, bukan dari pekerjaan
    yang sebenarnya penting.

    Mode WAL sendiri persisten di dalam file DB. Jadi begitu pertama kali
    berhasil, pemanggilan berikutnya membaca "wal" dan tidak butuh lock
    eksklusif sama sekali. Kegagalan di sini cuma terjadi pada koneksi
    pertama ke file DB baru saat ada writer lain yang sedang aktif; SQLite
    meanwhile memakai mode default, yang tetap menghasilkan DB yang benar -
    hanya tanpa concurrent read yang memberi keuntungan WAL.
    """
    try:
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass


def connect(path=None, **kwargs) -> sqlite3.Connection:
    """
    sqlite3.connect() dengan busy_timeout + WAL + foreign_keys aktif.

    Semua file DB v1 (guardian, ingest) sebaiknya lewat sini, bukan
    sqlite3.connect() langsung, supaya pengaturan ini tidak hilang saat ada
    call site baru.

    kwargs diteruskan ke sqlite3.connect. Yang dipakai saat ini:
    isolation_level=None (mode autocommit) - dibutuhkan approve_operation(),
    yang mengelola BEGIN IMMEDIATE / ROLLBACK-nya sendiri.
    """
    conn = sqlite3.connect(
        str(path if path is not None else DB_PATH),
        timeout=BUSY_TIMEOUT_MS / 1000.0,
        **kwargs,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    _enable_wal(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
    conn = connect()
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

    -- GitHub Integration tables
    CREATE TABLE IF NOT EXISTS github_connections (
        id            TEXT PRIMARY KEY,
        type          TEXT NOT NULL,          -- 'oauth' | 'pat'
        access_token  TEXT NOT NULL,          -- encrypted
        scope         TEXT,                   -- comma-separated scopes
        user_login    TEXT,
        user_avatar   TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS repo_refs (
        id              TEXT PRIMARY KEY,          -- 'github:owner/repo#branch' or 'local:path'
        source          TEXT NOT NULL,             -- 'github' | 'local'
        github_owner    TEXT,
        github_repo     TEXT,
        github_branch   TEXT,
        local_path      TEXT,
        name            TEXT NOT NULL,
        last_synced     TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    -- LLM Provider registry
    CREATE TABLE IF NOT EXISTS llm_providers (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,             -- 'openai', 'anthropic', 'ibm', 'nvidia', 'deepseek', 'ollama', 'custom'
        type            TEXT NOT NULL,             -- 'openai', 'anthropic', 'ibm', 'nvidia', 'deepseek', 'ollama', 'openai-compatible'
        base_url        TEXT,                      -- for custom/ollama
        api_key         TEXT,                      -- encrypted
        models          TEXT,                      -- JSON array of model names
        default_model   TEXT,
        max_tokens      INTEGER DEFAULT 4096,
        supports_tools  INTEGER DEFAULT 1,
        supports_vision INTEGER DEFAULT 0,
        enabled         INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS project_llm_configs (
        project_id      TEXT PRIMARY KEY,
        provider_id     TEXT NOT NULL,
        model           TEXT NOT NULL,
        temperature     REAL DEFAULT 0.2,
        max_tokens      INTEGER DEFAULT 4096,
        system_prompt   TEXT,
        rag_enabled     INTEGER DEFAULT 1,
        rag_top_k       INTEGER DEFAULT 5,
        updated_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (provider_id) REFERENCES llm_providers(id)
    );
    """)

    conn.commit()
    conn.close()
    print("[DB] Schema initialised at", DB_PATH)
