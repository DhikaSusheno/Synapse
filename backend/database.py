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
        -- Id target (repository/folder) yang aktif ketika operasi ini
        -- dibuat. Operations TIDAK per-target: memindah target akan mengganti
        -- SELURUH isi graph, dan mencampur history approval repo A ke repo B
        -- berbahaya (kebetulan nama file-nya sama). Nilai ini ditulis saat
        -- propose, bukan saat dibaca, jadi history tetap menempel ke repo aslinya
        -- walau target-nya sudah diganti atau dihapus dari registry.
        -- '' = dibuat sebelum fitur ini ada, atau tanpa target aktif.
        target_id            TEXT DEFAULT '',
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

    _add_missing_columns(conn)
    conn.commit()
    conn.close()
    print("[DB] Schema initialised at", DB_PATH)


# Kolom yang ditambahkan SETELAH schema v1 pertama kali rilis. CREATE TABLE IF
# NOT EXISTS tidak pernah menyentuh tabel yang sudah ada, jadi DB lama butuh
# ALTER TABLE terpisah. Dipisah dari skema awal supaya tidak ada yang salah
# baca sebagai "kolom ini selalu ada sejak awal".
_ADDED_COLUMNS = (
    ("operations", "target_id", "TEXT DEFAULT ''"),
)


def _add_missing_columns(conn) -> None:
    """Tambahkan kolom yang belum ada, untuk DB yang dibuat versi lama.

    Dibaca dari PRAGMA table_info, bukan dari metadata, jadi jalan juga untuk
    DB yang tabelnya belum pernah disentuh sama sekali.
    """
    for table, column, decl in _ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing or column in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
