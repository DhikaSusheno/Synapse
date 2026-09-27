"""
guardian.py - BE-1 DhikaSusheno + fix BUG-01..BUG-04 oleh Masrendra
                 + fix BUG-A..BUG-E + GLITCH-5 oleh DhikaSusheno
Tanggung jawab:
  - propose_operation()     : klasifikasi risiko + conflict check + plan rollback
  - execute_operation()     : snapshot -> jalankan -> verifikasi -> auto-rollback
  - list_pending_approvals(): daftar operasi pending approval
  - approve_operation()     : approve / deny operasi

Bug fixes (dari security/TEST_SCENARIOS.md Bug Findings Log):
  BUG-01 [CRITICAL] execute_operation bypass approval via direct DB manipulation
         FIX: re-derive requires_approval dari RULE ENGINE (tool_name yang immutable),
              BUKAN dari kolom requires_approval di DB yang bisa di-inject attacker.

  BUG-02 [HIGH] _do_rollback hardcoded ke DB_PATH, bukan ke target DB dari params
         FIX: rollback_command sekarang menyimpan JSON {"bak": ..., "target": ...}
              sehingga restore ke file yang benar bahkan di Windows path.

  BUG-03 [HIGH] rollback db.run_migration restore seluruh file DB - operasi
         verified lain yang dibuat SETELAH snapshot ikut terhapus.
         FIX: snapshot hanya berlaku per-operasi.

  BUG-04 [MEDIUM] _make_snapshot dipanggil terlalu awal di propose()
         FIX: snapshot dipindahkan ke execute_operation() tepat sebelum eksekusi.

  BUG-A [HIGH] _do_rollback() gagal pada Windows path dengan drive letter (colon)
         FIX: rollback_command sekarang JSON {"bak": "...", "target": "..."},
              tidak ada ambiguitas split pada C:\\path.

  BUG-B [HIGH] _exec_migration() pakai executescript() yang auto-commit
         FIX: explicit transaction BEGIN/COMMIT/ROLLBACK per statement.

  ISSUE-34 [HIGH] _exec_migration() memecah SQL dengan split(";") secara naif
         Gejala: `;` di dalam string literal (''), identifier ("", ``, []),
                 atau komentar membuat SQL terpotong jadi statement invalid →
                 data corruption atau ROLLBACK yang menyesatkan.
         FIX: _split_sql_statements() — lexer yang menghormati quoting dan
              komentar. Tanpa dependensi baru (sqlparse tidak dipakai supaya
              requirements.txt tetap ringan).

  BUG-D [LOW]  list_pending_approvals() bocorkan operasi 'approved' ke pending list
         FIX: WHERE status = 'pending' (exact, bukan IN ('pending','approved')).

  BUG-E [LOW]  asyncio.get_event_loop() deprecated Python 3.10+
         FIX: di main.py on_startup() ganti ke asyncio.get_running_loop().

  GLITCH-5 [MEDIUM] _exec_file_delete() tidak validasi snapshot integrity
         FIX: cek bak.exists() dan bak.stat().st_size > 0 sebelum hapus original.

  GLITCH-3 [MEDIUM] synapse.invariants.yaml tidak pernah dibaca
         FIX: guardian.py sekarang MEMUAT dan MENJALANKAN invariant dari
               synapse.invariants.yaml lewat _load_invariants()/_run_invariants(),
               menggantikan if/else hardcoded di _verify_operation().
               Setelah fix ini, klaim SYNAPSE.md section 1 ("runs the verification
               checks from synapse.invariants.yaml") benar-benar terpenuhi.

  GLITCH-4 [MEDIUM] get_conn() di database.py dead code
         FIX: dihapus. Guardian/Cortex tetap membuka koneksi per unit kerja
               lewat _db_path() yang dibaca ulang tiap panggilan.

  BUG-F [HIGH] rollback diam-diam tidak mengubah apa pun (ditemukan saat verifikasi GLITCH-3)
         Gejala: _do_rollback() mengembalikan True, tapi file DB tetap rusak.
         Penyebab: Synapse DB jalan di mode WAL. shutil.copy2() hanya menyalin file
               utama, sedangkan commit terbaru masih hidup di file -wal; lalu
               koneksi execute_operation yang masih terbuka akan men-checkpoint
               WAL basi itu kembali ke file utama setelah restore.
         FIX: snapshot pakai sqlite3.Connection.backup() (salinan lengkap &
               konsisten termasuk isi WAL), file -wal/-shm stale dihapus setelah
               restore, dan koneksi ditutup sebelum _do_rollback() dijalankan.
"""

import json
import os
import uuid
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import database as _database_module
import settings as _settings
from cortex import _emit  # pakai SSE bus milik Cortex


def _db_path() -> str:
    """Selalu baca DB_PATH terbaru dari module - support test override."""
    return str(_database_module.DB_PATH)


def active_target_id() -> str:
    """Id target aktif, atau "" kalau belum ada / registry tidak terbaca.

    Import dilakukan di dalam fungsi supaya guardian.py tetap bisa diimpor
    tanpa projects.py (test lama, dan skrip yang memakainya sebagai library),
    dan supaya kegagalan registry tidak menjatuhkan operasi: tanpa target
    yang terbaca, operasi tetap dicatat - hanya tidak dikelompokkan.
    """
    try:
        import projects
    except ImportError:
        return ""
    try:
        active = projects.get_active()
    except (OSError, ValueError):
        return ""
    if not isinstance(active, dict):
        return ""
    target_id = active.get("id")
    return target_id if isinstance(target_id, str) else ""


def _utcnow_iso() -> str:
    """
    Timestamp UTC dalam format ISO - pengganti API naive-UTC yang dihapus di
    Python 3.12.

    `tzinfo` sengaja dibuang agar hasil string-nya PERSIS sama dengan yang
    lama ("2026-09-27T02:00:00", tanpa suffix "+00:00"). Ini penting karena
    timestamp ini dibandingkan sebagai TEKS di SQL, bukan sebagai tipe
    tanggal - lihat _check_conflict() yang memakai `created_at > ?`. Kalau
    format berubah, perbandingan string itu diam-diam jadi salah.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _utcnow_naive() -> datetime:
    """UTC naive sebagai datetime - untuk perhitungan offset window."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ---------------------------------------------------------------------------
# ISSUE-46: status terminal operations
# ---------------------------------------------------------------------------

# Status dari mana tidak ada lagi transisi valid yang boleh terjadi.
# approve_operation() sebelumnya hanya mengecek "operasi ini ada?" — tidak
# mengecek status. Akibatnya operasi yang sudah selesai bisa di-approve ulang,
# status-nya di-reset ke 'approved', lalu CAS di execute_operation()
# (status IN ('pending','approved')) lolos dan operasinya dieksekusi untuk
# kedua kalinya.
#
# Diverifikasi di repo ini: propose -> execute (verified) -> approve (approved)
# -> execute menghasilkan status verified -> approved -> verified, yaitu efek
# sampingnya berjalan dua kali.
#
# 'denied' juga terminal: operator sudah menolak, dan tidak ada jalur reopen.
# 'executed_unverified' sengaja TIDAK terminal — status itu justru sedang
# menunggu verifikasi (guardian.py menulis 'verified' setelah
# _verify_operation()), jadi masih boleh disettle.
TERMINAL_STATUSES = frozenset({"verified", "rolled_back", "failed", "denied"})

# BUG-09 FIX: status yang BOLEH diubah oleh approve_operation/deny_operation.
#
# Guard sebelumnya hanya menolak TERMINAL_STATUSES, sehingga 'executing' dan
# 'executed_unverified' masih lolos. Rantai exploit yang diverifikasi:
#   propose -> execute (status='executing') -> approve (status='approved')
#          -> execute lagi (CAS Izinkan 'approved') = double execution.
# Guard CAS di execute_operation tidak bisa menyelamatkan karena 'approved'
# memang status yang diizinkannya.
#
# Jadi approvable harus jadi ALLOWLIST, bukan denylist terminal:
#   pending  -> approve / deny   (jalur normal)
#   approved -> deny             (revoque approval sebelum dieksekusi)
#   approved -> approve          (idempoten)
# Sisanya (executing, executed_unverified, verified, rolled_back, failed,
# denied) tidak boleh disentuh approval karena operasinya sudah berjalan,
# sudah dijalankan, atau sudah selesai.
APPROVABLE_STATUSES = frozenset({"pending", "approved"})


# ---------------------------------------------------------------------------
# GLITCH-3 FIX: pemuat synapse.invariants.yaml
# ---------------------------------------------------------------------------

INVARIANTS_PATH = Path(__file__).with_name("synapse.invariants.yaml")

_invariants_cache: list[dict] | None = None


def _load_invariants() -> list[dict]:
    """
    GLITCH-3 FIX: muat invariant dari synapse.invariants.yaml (di-cache per proses).

    Fail-closed: kalau file hilang / YAML rusak / tidak berisi daftar invariant,
    fungsi ini tetap mengembalikan daftar kosong (bukan crash), dan
    _verify_operation() akan menolak operasi karena tidak ada check yang
    terdefinisi. Keamanan jangan bergantung pada file spec yang bisa hilang.
    """
    global _invariants_cache
    if _invariants_cache is not None:
        return _invariants_cache

    try:
        raw = yaml.safe_load(INVARIANTS_PATH.read_text(encoding="utf-8")) or {}
        items = raw.get("invariants") or []
        _invariants_cache = [i for i in items if isinstance(i, dict) and i.get("check")]
    except Exception:
        _invariants_cache = []

    return _invariants_cache


def _invariant_applies(inv: dict, tool_name: str) -> bool:
    """
    Cocokkan applies_to dengan tool_name memakai dot-boundary prefix, sama seperti
    _get_rule(): 'db.run_migration' juga match 'db.run_migration.v2'.
    Arah ini aman untuk verifikasi (lebih banyak check, bukan lebih sedikit).
    """
    applies_to = str(inv.get("applies_to", "*"))
    if applies_to == "*":
        return True
    return tool_name == applies_to or tool_name.startswith(applies_to + ".")


def _resolve_path_from(inv_params: dict, op_params: dict) -> str:
    """
    Ambil path dari params operasi sesuai 'path_from: params.<key>' di YAML.
    Key di YAML harus sama dengan key yang dipakai eksekutor ('file_path').
    """
    path_from = str(inv_params.get("path_from", ""))
    if path_from.startswith("params."):
        return str(op_params.get(path_from[len("params."):], "") or "")
    return path_from


def _resolve_db_path(inv_params: dict, op_params: dict) -> str:
    """
    Prioritas: params['db_path'] dari operasi > db_path default di YAML > DB_PATH.
    params operasi menang supaya test override & multi-DB tetap benar.

    H5 FIX: path RELATIF tidak lagi di-resolve terhadap CWD proses.

    `synapse.invariants.yaml` menyimpan `db_path: "synapse.db"` — relatif.
    Python men-resolve path relatif terhadap direktori kerja saat ini, jadi
    verifier mengecek file yang berbeda tergantung dari mana uvicorn/pytest
    dijalankan. Terbukti nyata di checkout ini:

        C:\\...\\Synapse\\synapse.db        0 baris   <- shell kosong, dibuat
                                                         di CWD oleh bug path lama
        C:\\...\\Synapse\\backend\\synapse.db  1 node  <- DB yang benar-benar
                                                         ditulis guardian

    Akibatnya verifier memeriksa database yang TIDAK PERNAH disentuh
    migration — ia lolos dengan semua tabel utuh, sementara DB aslinya
    justru rusak dan tidak pernah di-rollback. Path relatif kini selalu
    di-anchor ke direktori DB kanonik, sehingga hasilnya tidak lagi
    bergantung pada CWD.
    """
    raw = op_params.get("db_path") or inv_params.get("db_path")
    if not raw:
        return str(_db_path())
    candidate = Path(str(raw))
    if not candidate.is_absolute():
        candidate = Path(_db_path()).parent / candidate
    return str(candidate)


# ---------------------------------------------------------------------------
# GLITCH-3 FIX: implementasi tiap jenis check
# ---------------------------------------------------------------------------

def _check_sqlite_tables_exist(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    db_path = _resolve_db_path(inv_params, op_params)
    required = [str(t) for t in (inv_params.get("tables") or [])]
    if not required:
        return True, "tidak ada tabel yang diminta"
    if not Path(db_path).exists():
        return False, f"DB tidak ada: {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        try:
            present = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except Exception as e:
        return False, f"DB tidak bisa dibaca: {e}"
    missing = [t for t in required if t not in present]
    if missing:
        return False, f"tabel kontrak hilang: {missing}"
    return True, f"{len(required)} tabel kontrak ada"


def _check_sqlite_pragma(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    db_path = _resolve_db_path(inv_params, op_params)
    pragma = str(inv_params.get("pragma", ""))
    expected = str(inv_params.get("expected_value", ""))
    if not pragma:
        return True, "pragma tidak diminta"
    if not pragma.replace("_", "").isalnum():
        return False, f"nama pragma tidak valid: {pragma!r}"
    # H5 FIX: sqlite3.connect(path) pada path yang belum ada MEMBUAT file
    # database kosong di sana. Karena itu langkah "verifikasi" berubah jadi
    # langkah yang MENULIS — melempar file DB baru ke filesystem tiap kali
    # eksekusi gagal menemukan DB-nya. Cek dulu keberadaannya, sama seperti
    # _check_sqlite_tables_exist sudah lakukan.
    if not Path(db_path).exists():
        return False, f"DB tidak ada: {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        try:
            actual = str(conn.execute(f"PRAGMA {pragma}").fetchone()[0])
        finally:
            conn.close()
    except Exception as e:
        return False, f"pragma '{pragma}' gagal dibaca: {e}"
    if actual.strip().lower() != expected.strip().lower():
        return False, f"pragma {pragma}={actual!r} (hope {expected!r})"
    return True, f"pragma {pragma}={actual}"


def _check_sqlite_row_count_gte(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    db_path = _resolve_db_path(inv_params, op_params)
    table = str(inv_params.get("table", ""))
    min_count = int(inv_params.get("min_count", 0) or 0)
    if not table:
        return True, "tabel tidak diminta"
    if not table.replace("_", "").isalnum():
        return False, f"nama tabel tidak valid: {table!r}"
    # H5 FIX: sama seperti check pragma — sqlite3.connect() membuat file
    # kosong kalau DB-nya belum ada, sehingga verifikasi ikut menulis.
    if not Path(db_path).exists():
        return False, f"DB tidak ada: {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()
    except Exception as e:
        return False, f"tabel '{table}' tidak bisa di-query: {e}"
    if count < min_count:
        return False, f"tabel '{table}' punya {count} baris (min {min_count})"
    return True, f"tabel '{table}' = {count} baris"


def _check_file_exists(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    file_path = _resolve_path_from(inv_params, op_params)
    if not file_path:
        return False, "path tidak ada di params operasi"
    if not Path(file_path).is_file():
        return False, f"file tidak ditemukan: {file_path}"
    return True, f"file ada: {file_path}"


def _check_file_size_gte(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    file_path = _resolve_path_from(inv_params, op_params)
    min_bytes = int(inv_params.get("min_bytes", 0) or 0)
    if not file_path:
        return False, "path tidak ada di params operasi"
    try:
        size = Path(file_path).stat().st_size
    except OSError as e:
        return False, f"file tidak bisa di-stat: {e}"
    if size < min_bytes:
        return False, f"file {size} byte (min {min_bytes}): {file_path}"
    return True, f"file {size} byte: {file_path}"


def _check_file_not_exists(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    file_path = _resolve_path_from(inv_params, op_params)
    if not file_path:
        return False, "path tidak ada di params operasi"
    if Path(file_path).exists():
        return False, f"file masih ada setelah delete: {file_path}"
    return True, f"file sudah dihapus: {file_path}"


def _check_always_pass(inv_params: dict, op_params: dict) -> tuple[bool, str]:
    return True, "selalu lolos (stub)"


def _check_operation_status_not(inv_params: dict, op_params: dict,
                                operation_id: str | None) -> tuple[bool, str]:
    forbidden = str(inv_params.get("forbidden_status", ""))
    if not operation_id:
        return True, "tanpa operation_id - dilewati"
    try:
        conn = sqlite3.connect(_db_path())
        try:
            row = conn.execute(
                "SELECT status FROM operations WHERE id = ?", (operation_id,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        return False, f"status operasi tidak bisa dibaca: {e}"
    if not row:
        return True, "operasi tidak ada (sudah dibersihkan)"
    if row[0] == forbidden:
        return False, f"status operasi masih '{forbidden}'"
    return True, f"status operasi = {row[0]!r}"


_INVARIANT_CHECKS = {
    "sqlite_tables_exist": _check_sqlite_tables_exist,
    "sqlite_pragma": _check_sqlite_pragma,
    "sqlite_row_count_gte": _check_sqlite_row_count_gte,
    "file_exists": _check_file_exists,
    "file_size_gte": _check_file_size_gte,
    "file_not_exists": _check_file_not_exists,
    "always_pass": _check_always_pass,
}


def _run_invariants(tool_name: str, params: dict) -> list[dict]:
    """
    GLITCH-3 FIX: jalankan semua invariant yang berlaku untuk tool_name.

    Return list {id, check, passed, on_fail, message}. Invariant global
    (applies_to='*') TIDAK dievaluasi di sini — lihat _run_global_invariants().
    """
    results: list[dict] = []
    for inv in _load_invariants():
        if str(inv.get("applies_to", "*")) == "*":
            continue
        if not _invariant_applies(inv, tool_name):
            continue

        inv_id = str(inv.get("id", "?"))
        check_name = str(inv.get("check", ""))
        on_fail = str(inv.get("on_fail", "rollback"))
        handler = _INVARIANT_CHECKS.get(check_name)

        if handler is None:
            # Tipe check tidak dikenal -> jangan diabaikan diam-diam.
            results.append({
                "id": inv_id, "check": check_name, "passed": False,
                "on_fail": "rollback",
                "message": f"tipe check '{check_name}' tidak dikenal (fail-closed)",
            })
            continue

        try:
            passed, message = handler(inv.get("params") or {}, params)
        except Exception as e:
            passed, message = False, f"invariant error: {e}"

        results.append({
            "id": inv_id, "check": check_name, "passed": bool(passed),
            "on_fail": on_fail, "message": message,
        })

    return results


def _run_global_invariants(operation_id: str) -> list[dict]:
    """
    Jalankan invariant applies_to='*' SESUDAH status terminal ditulis.
    Invariant global menilai kebocoran state (mis. status masih 'executing'),
    sehingga hanya bermakna setelah execute_operation selesai — kalau dijalankan
    lebih awal, 'operation_status_not_executing' akan false-positive terus.
    """
    results: list[dict] = []
    for inv in _load_invariants():
        if str(inv.get("applies_to", "*")) != "*":
            continue
        inv_id = str(inv.get("id", "?"))
        check_name = str(inv.get("check", ""))
        on_fail = str(inv.get("on_fail", "warn"))
        inv_params = inv.get("params") or {}

        # 'operation_status_not' butuh operation_id, jadi tidak cocok dengan
        # signature 2-argumen yang dipakai _INVARIANT_CHECKS.
        if check_name == "operation_status_not":
            handler = lambda p, _op: _check_operation_status_not(p, _op, operation_id)
        else:
            base = _INVARIANT_CHECKS.get(check_name)
            handler = None if base is None else (lambda p, _op, _f=base: _f(p, _op))

        if handler is None:
            results.append({
                "id": inv_id, "check": check_name, "passed": False,
                "on_fail": "warn",
                "message": f"tipe check '{check_name}' tidak dikenal",
            })
            continue

        try:
            passed, message = handler(inv_params, {})
        except Exception as e:
            passed, message = False, f"invariant error: {e}"

        results.append({
            "id": inv_id, "check": check_name, "passed": bool(passed),
            "on_fail": on_fail, "message": message,
        })
    return results

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

CONFLICT_WINDOW_MINUTES = 10

# H4: batas panjang `target` yang dijadikan id + nama node graph.
# Harus sama dengan batas pydantic di main.ProposeOperationRequest.target
# supaya klien yang lolos HTTP juga lolos di guardian (dan sebaliknya).
_MAX_TARGET_LEN = 512

# M18: batas ukuran `params` setelah diserialisasi.
#
# params disimpan sebagai kolom TEXT di `operations` lalu dibaca kembali oleh
# execute_operation(). Dulu tidak ada batas sama sekali, jadi satu propose
# bisa menulis baris sebesar yang diminta pemanggil — payload itu lalu ikut
# di-parse ulang, dan diambil lagi tiap kali eksekusi, snapshot, atau
# riwayat operasi dibuka. 64 KiB jauh melampaui params migrasi/query yang
# wajar, sekaligus masih kecil dibanding batas body request (32 MiB) yang
# membatasi nilainya di lapis HTTP.
_MAX_PARAMS_BYTES = 64 * 1024

RULES = [
    {
        "match": "db.run_migration",
        "blast_radius": "high",
        "reversibility": "needs_snapshot",
        "require_approval": True,
        "prefix_match": True,   # db.run_migration.v2 juga match
    },
    {
        "match": "service.restart",
        "blast_radius": "medium",
        "reversibility": "needs_snapshot",
        "require_approval": False,
        "prefix_match": True,   # service.restart.graceful juga match
    },
    {
        # H2 FIX: dulu require_approval=False.
        #
        # config.write adalah primitive TULIS FILE PALING UMUM di guardian dan
        # eksekusinya menulis ke path apa pun yang diberikan lewat params —
        # tanpa approval, agent yang boleh propose operasi justru bisa menulis
        # .ssh/authorized_keys, .env (berisi SYNAPSE_API_TOKEN + FERNET_KEY),
        # hook git, atau file source lalu mendapatkan code execution tanpa
        # satu pun persetujuan manusia. Itu bertentangan langsung dengan
        # janji Synapse: approval_mode "Manual (human required)".
        # Kecocokan kasusnya persis seperti file.delete (yang sudah
        # require_approval=True) — keduanya mengubah state disk.
        "match": "config.write",
        "blast_radius": "medium",
        "reversibility": "needs_snapshot",
        "require_approval": True,
        "prefix_match": False,  # exact only: config.write.as.root harus fail-closed
    },
    {
        "match": "file.delete",
        "blast_radius": "high",
        "reversibility": "needs_snapshot",
        "require_approval": True,
        "prefix_match": False,  # exact only
    },
    # fail-closed default - harus di paling bawah
    {
        "match": "*",
        "blast_radius": "unknown",
        "reversibility": "irreversible_suspected",
        "require_approval": True,
        "prefix_match": False,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rule(tool_name: str) -> dict:
    """
    Cari rule yang cocok. Default: fail-closed (*).
    Setiap rule punya flag prefix_match:
      - True : tool_name cocok jika sama persis ATAU dimulai dengan match + '.'
               Contoh: db.run_migration.v2 cocok dengan db.run_migration
      - False: tool_name harus sama persis (exact match)
               Contoh: config.write.as.root TIDAK cocok dengan config.write
    """
    if not tool_name or not tool_name.strip():
        return RULES[-1]  # fail-closed untuk empty/whitespace
    for rule in RULES:
        if rule["match"] == "*":
            continue
        match = rule["match"]
        if rule.get("prefix_match", False):
            # prefix dengan dot-boundary
            if tool_name == match or tool_name.startswith(match + "."):
                return rule
        else:
            # exact match only
            if tool_name == match:
                return rule
    return RULES[-1]


def _effective_requires_approval(op) -> bool:
    """
    BUG-10 FIX: satu sumber kebenaran untuk 'apakah operasi ini butuh approval'.

    Sebelumnya derive-nya diduplikasi di dua tempat dengan cara berbeda:
      - execute_operation()  -> re-derive dari rule engine + kolom DB
      - list_pending_approvals() -> HANYA baca kolom requires_approval
    Kalau rule berubah setelah propose (mis. config diedit lalu restart), kolom
    DB masih menyimpan nilai lama. Akibatnya operasi muncul requiring-approval
    di execute tapi TIDAK pernah muncul di daftar pending: dead-end yang tidak
    bisa di-approve dan tidak bisa di-execute.

    Nowdef: rule engine adalah live truth, kolom DB hanya remembers bahwa
    conflict pernah memaksa approval. Keduanya di-OR.
    """
    rule = _get_rule(op["tool_name"])
    rule_requires_approval = bool(rule["require_approval"])
    try:
        db_requires_approval = int(op["requires_approval"] or 0) == 1
    except (TypeError, ValueError):
        db_requires_approval = bool(op["requires_approval"])
    return rule_requires_approval or db_requires_approval


def _check_conflict(conn: sqlite3.Connection, target_node_id: str) -> list[dict]:
    """
    Cek operasi lain yang menyentuh target_node_id dalam window terakhir.
    Hanya status aktif yang dihitung (sesuai SYNAPSE.md 4.5).
    """
    window_start = (
        _utcnow_naive() - timedelta(minutes=CONFLICT_WINDOW_MINUTES)
    ).isoformat()

    rows = conn.execute(
        """
        SELECT o.id, o.tool_name, o.status, o.created_at
        FROM operations o
        WHERE o.target_node_id = ?
          AND o.status IN ('pending','approved','executing','executed_unverified')
          AND o.created_at > ?
        """,
        (target_node_id, window_start),
    ).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# BUG-03 FIX: snapshot berbasis SQL inverse, bukan file copy
# ---------------------------------------------------------------------------

def _make_snapshot_plan(tool_name: str, params: dict) -> tuple[str, str]:
    """
    BUG-04 FIX: hanya buat RENCANA snapshot (string deskripsi),
    tidak mengeksekusi snapshot di sini.
    Snapshot nyata dilakukan di execute_operation() tepat sebelum eksekusi.

    Return (snapshot_strategy_description, rollback_strategy_description)
    """
    if tool_name.startswith("db.run_migration"):
        db_path = params.get("db_path", _db_path())
        return (
            f"Catat SQL inverse migration dari '{db_path}'",
            f"Jalankan SQL inverse untuk membalik migration",
        )
    if tool_name.startswith("config.write"):
        file_path = params.get("file_path", "")
        return (
            f"Backup '{file_path}' -> .bak sebelum overwrite",
            f"Restore '{file_path}' dari .bak",
        )
    if tool_name.startswith("file.delete"):
        file_path = params.get("file_path", "")
        return (
            f"Backup '{file_path}' -> .bak sebelum hapus",
            f"Restore '{file_path}' dari .bak",
        )
    return ("Tidak ada snapshot (stub)", "Manual rollback diperlukan")


def _take_snapshot(tool_name: str, params: dict) -> tuple[str | None, str | None]:
    """
    BUG-04 FIX: eksekusi snapshot NYATA dilakukan di sini,
    dipanggil dari execute_operation() tepat sebelum eksekusi.

    BUG-A FIX: rollback_command disimpan sebagai JSON {"bak": ..., "target": ...}
    sehingga tidak ada ambiguitas split pada Windows path dengan drive letter.

    BUG-F FIX: untuk SQLite, snapshot memakai sqlite3.Connection.backup() dan
    bukan shutil.copy2(). Synapse DB jalan di mode WAL, jadi commit terbaru bisa
    masih hidup di file -wal dan belum masuk file DB utama. shutil.copy2() hanya
    menyalin file utama sehingga .bak bisa kosong dari perubahan terakhir, dan
    restore-nya tidak pernah mengembalikan data. Backup API menghasilkan salinan
    yang lengkap & konsisten.

    Return (snapshot_ref, rollback_command_json)
    """
    if tool_name.startswith("db.run_migration"):
        # BUG-02 + BUG-03 FIX: gunakan db_path dari params, bukan DB_PATH global
        db_target = params.get("db_path", _db_path())
        ts = _utcnow_naive().strftime("%Y%m%dT%H%M%S")
        bak = f"{db_target}.bak.{ts}"
        try:
            src = sqlite3.connect(db_target)
            try:
                dst = sqlite3.connect(bak)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            # BUG-A FIX: JSON format, tidak ada ambiguitas colon di Windows path
            rollback_cmd = json.dumps({"bak": bak, "target": db_target})
            return bak, rollback_cmd
        except Exception:
            return None, None

    if tool_name.startswith("config.write"):
        file_path = params.get("file_path", "")
        if file_path and Path(file_path).exists():
            ts = _utcnow_naive().strftime("%Y%m%dT%H%M%S")
            bak = f"{file_path}.bak.{ts}"
            try:
                shutil.copy2(file_path, bak)
                rollback_cmd = json.dumps({"bak": bak, "target": file_path})
                return bak, rollback_cmd
            except Exception:
                pass

    if tool_name.startswith("file.delete"):
        file_path = params.get("file_path", "")
        if file_path and Path(file_path).exists():
            ts = _utcnow_naive().strftime("%Y%m%dT%H%M%S")
            bak = f"{file_path}.bak.{ts}"
            try:
                shutil.copy2(file_path, bak)
                rollback_cmd = json.dumps({"bak": bak, "target": file_path})
                return bak, rollback_cmd
            except Exception:
                pass

    return None, None


def _is_sqlite_file(path: str) -> bool:
    """Cek magic header SQLite ('SQLite format 3\\0')."""
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _restore_file(bak_path: str, target_path: str) -> bool:
    """
    BUG-F FIX: restore file lalu buang artefak WAL stale.

    Kalau target berupa database SQLite, file -wal/-shm yang tersisa dari kondisi
    SEBELUM rollback harus dihapus. Kalau tidak, SQLite akan me-replay WAL lama
    saat file dibuka berikutnya dan menerapkan kembali perubahan yang seharusnya
    sudah dibatalkan — restore terlihat sukses tapi datanya tetap rusak.
    """
    try:
        shutil.copy2(bak_path, target_path)
    except Exception:
        return False

    if _is_sqlite_file(target_path):
        for suffix in ("-wal", "-shm"):
            try:
                Path(target_path + suffix).unlink()
            except OSError:
                pass
    return True


def _do_rollback(rollback_command: str | None) -> bool:
    """
    BUG-A FIX: rollback_command sekarang JSON {"bak": "...", "target": "..."}.
    Tidak ada lagi ambiguitas split pada Windows path (C:\\path punya colon).

    BUG-F FIX: setelah file direstore, artefak -wal/-shm stale dibuang supaya
    SQLite tidak me-replay perubahan lama di atas file yang sudah dipulihkan.

    Backward compat: jika format lama "restore_from:<bak>:<target>" masih ada
    di DB (dari commit sebelumnya), fallback ke split lama.
    """
    if not rollback_command:
        return False

    # Format baru: JSON
    try:
        data = json.loads(rollback_command)
        if isinstance(data, dict) and "bak" in data and "target" in data:
            return _restore_file(data["bak"], data["target"])
    except (json.JSONDecodeError, ValueError):
        pass  # bukan JSON, coba format lama

    # Format lama (backward compat): "restore_from:<bak_path>:<target_path>"
    if rollback_command.startswith("restore_from:"):
        parts = rollback_command.split(":", 2)
        if len(parts) < 3:
            bak_path = parts[1]
            target_path = _db_path()
        else:
            bak_path = parts[1]
            target_path = parts[2]
        return _restore_file(bak_path, target_path)

    return False


def _rollback_and_finalize(conn: sqlite3.Connection, operation_id: str,
                           rollback_command: str | None,
                           mark_verified_at: bool) -> bool:
    """
    BUG-F FIX: tutup koneksi ke Synapse DB SEBELUM restore file, lalu tulis status
    terminal lewat koneksi BARU.

    Kenapa urutan ini wajib: kalau file .bak direstore sementara `conn` masih
    terbuka, koneksi itu masih memegang WAL lama. Commit berikutnya (penulisan
    status terminal) akan men-checkpoint WAL stale itu ke file utama dan
    MENERAPKAN KEMBALI perubahan yang baru saja dibatalkan. Akibatnya
    _do_rollback() mengembalikan True padahal data tidak pernah pulih — rollback
    gagal diam-diam. Ini terpicu karena operasi demo memigrasikan Synapse DB itu
    sendiri, jadi target rollback == DB yang sedang di-commit.

    Catatan: snapshot diambil SETELAH status 'executing' ditulis, jadi baris
    operations untuk operasi ini ada di .bak dan status terminal bisa ditimpa
    sesudah restore.

    Return rollback_ok.
    """
    try:
        conn.commit()
    except Exception:
        pass
    conn.close()

    rollback_ok = _do_rollback(rollback_command)
    new_status = "rolled_back" if rollback_ok else "failed"

    try:
        conn2 = sqlite3.connect(_db_path())
        if mark_verified_at:
            conn2.execute(
                "UPDATE operations SET status=?, verified_at=? WHERE id=?",
                (new_status, _utcnow_iso(), operation_id),
            )
        else:
            conn2.execute(
                "UPDATE operations SET status=? WHERE id=?",
                (new_status, operation_id),
            )
        conn2.commit()
        conn2.close()
    except Exception:
        # Status tidak bisa ditulis (mis. file DB rusak total). Rollback file
        # tetap dianggap berhasil; kegagalan ada di log server.
        pass

    return rollback_ok


def _verify_operation(tool_name: str, params: dict) -> tuple[bool, str, list[str]]:
    """
    GLITCH-3 FIX: verifikasi post-condition sekarang dijalankan dari
    synapse.invariants.yaml, bukan dari if/else hardcoded.

    Return (ok, message, warnings):
      - ok=False  -> ada invariant 'on_fail: rollback' yang gagal, pemanggil
                     harus auto-rollback.
      - warnings  -> invariant 'on_fail: warn' yang gagal. TIDAK membatalkan
                     operasi, hanya dilaporkan (mis. file 0 byte).
    Fail-closed: tool yang tidak punya satu pun invariant di YAML ditolak,
    karena 'tidak ada check' bukan berarti 'aman'.
    """
    results = _run_invariants(tool_name, params)

    if not results:
        return (
            False,
            f"Tidak ada invariant yang terdefinisi untuk tool '{tool_name}' "
            f"di synapse.invariants.yaml (fail-closed)",
            [],
        )

    failures = [r for r in results if not r["passed"]]
    blocking = [r for r in failures if r["on_fail"] == "rollback"]
    warnings = [f"{r['id']}: {r['message']}" for r in failures
                if r["on_fail"] != "rollback"]

    if blocking:
        detail = "; ".join(f"{r['id']}: {r['message']}" for r in blocking)
        return False, f"Invariant gagal: {detail}", warnings

    passed = [r["id"] for r in results if r["passed"]]
    message = f"{len(passed)}/{len(results)} invariant lolos ({', '.join(passed)})"
    if warnings:
        message += " | warning: " + "; ".join(warnings)
    return True, message, warnings


# ---------------------------------------------------------------------------
# 1. propose_operation
# ---------------------------------------------------------------------------

def propose_operation(tool_name: str, params: dict, target: str) -> dict:
    """
    Langkah 1 Guardian:
      1. Klasifikasi blast_radius via rule table (case-sensitive, fail-closed)
      2. Conflict check
      3. Buat RENCANA snapshot (BUG-04 FIX: tidak eksekusi snapshot di sini)
      4. Simpan ke operations dengan status 'pending'
      5. Emit SSE operation_proposed
    """
    # H4 FIX: `target` dipakai mentah sebagai id sekaligus nama node graph
    # (baris `target_node_id = f"operation_target::{target}"` di bawah).
    # Guardian adalah lapis keamanan, jadi validasinya juga ada di sini —
    # bukan hanya di pydantic main.py — karena fungsi ini dipanggil langsung
    # oleh skrip, tool, dan test, tanpa melewati HTTP sama sekali.
    #
    # Ditolaknya juga di sini berarti string kosong / terlalu panjang /
    # berisi karakter kontrol tidak pernah masuk ke database sebagai node
    # yang selanjutnya disebarkan ke seluruh endpoint /graph/*.
    target_text = "" if target is None else str(target).strip()
    if not target_text:
        return {
            "ok": False,
            "error": "target wajib berisi teks (tidak boleh kosong/whitespace)",
        }
    if len(target_text) > _MAX_TARGET_LEN:
        return {
            "ok": False,
            "error": (
                f"target terlalu panjang: {len(target_text)} karakter "
                f"(maksimal {_MAX_TARGET_LEN})"
            ),
        }
    if any(ord(ch) < 32 for ch in target_text):
        # NUL/kontrol merambat ke SQLite TEXT dan ke JSON respons, di mana
        # pemotongan di tengah karakter bisa merusak parsing di klien.
        return {
            "ok": False,
            "error": "target mengandung karakter kontrol yang tidak diizinkan",
        }
    target = target_text

    # M18 FIX: params divalidasi dan dibatasi SEBELIMENYENTUH database.
    #
    # Tiga kegagalan lama, semuanya jatuh sebagai 500 tanpa konteks:
    #   1. params bukan dict            -> json.dumps tetap jalan, tapi
    #                                      eksekutor mengharapkan dict;
    #   2. params tidak serialisabel    -> TypeError dari json.dumps;
    #   3. params mengandung NaN/Inf    -> json.dumps menghasilkan "NaN",
    #                                      yaitu JSON yang TIDAK VALID
    #                                      (lihat allow_nan=False di bawah).
    # Ditambah ukuran yang tidak dibatasi sama sekali: satu propose bisa
    # menulis baris sebesar yang diminta pemanggil.
    if not isinstance(params, dict):
        return {
            "ok": False,
            "error": "params harus berupa objek JSON (dict), bukan "
                     f"{type(params).__name__}",
        }
    try:
        params_json = json.dumps(params, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return {
            "ok": False,
            "error": "params tidak bisa diserialisasi ke JSON "
                     "(nilai non-JSON seperti NaN/Infinity atau objek kustom)",
        }
    params_bytes = len(params_json.encode("utf-8"))
    if params_bytes > _MAX_PARAMS_BYTES:
        return {
            "ok": False,
            "error": (
                f"params terlalu besar: {params_bytes} byte "
                f"(maksimal {_MAX_PARAMS_BYTES})"
            ),
        }

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    rule = _get_rule(tool_name)
    blast_radius = rule["blast_radius"]
    reversibility_class = rule["reversibility"]
    requires_approval = rule["require_approval"]

    target_node_id = f"operation_target::{target}"
    conn.execute(
        """INSERT INTO nodes (id, type, name, meta_json)
           VALUES (?, 'operation', ?, '{}')
           ON CONFLICT(id) DO NOTHING""",
        (target_node_id, target),
    )

    conflicts = _check_conflict(conn, target_node_id)
    if conflicts:
        requires_approval = True

    # BUG-04 FIX: hanya buat rencana, tidak eksekusi snapshot
    snapshot_strategy, rollback_strategy = _make_snapshot_plan(tool_name, params)

    operation_id = str(uuid.uuid4())
    # Target dicap saat propose, bukan saat dibaca. Kalau dicap di saat baca,
    # history approval ikut pindah ke target berikutnya - dan karena nama file
    # antar repo sering sama, user bisa menyetujui perubahan yang salah repo.
    target_id = active_target_id()
    conn.execute(
        """INSERT INTO operations
           (id, tool_name, params_json, target_node_id, target_id,
            blast_radius,
            reversibility_class, status, snapshot_ref, rollback_command,
            requires_approval, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?)""",
        (
            operation_id, tool_name, params_json, target_node_id,
            target_id,
            blast_radius, reversibility_class,
            1 if requires_approval else 0,
            _utcnow_iso(),
        ),
    )

    conn.execute(
        """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
           VALUES (?, ?, ?, 'TARGETS', 1.0)
           ON CONFLICT(id) DO NOTHING""",
        (f"{operation_id}::TARGETS::{target_node_id}", operation_id, target_node_id),
    )

    for conflict in conflicts:
        conn.execute(
            """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
               VALUES (?, ?, ?, 'CONFLICTS_WITH', 1.0)
               ON CONFLICT(id) DO NOTHING""",
            (
                f"{operation_id}::CONFLICTS_WITH::{conflict['id']}",
                operation_id, conflict["id"],
            ),
        )

    conn.commit()
    conn.close()

    plan = {
        "snapshot_strategy": snapshot_strategy,
        "rollback_strategy": rollback_strategy,
        "verification": "post-execution DB/file integrity check",
        "note": "Snapshot akan diambil tepat sebelum eksekusi (bukan sekarang)",
    }

    _emit("operation_proposed", {
        "operation_id": operation_id,
        "tool_name": tool_name,
        "target": target,
        "target_id": target_id,
        "blast_radius": blast_radius,
        "requires_approval": requires_approval,
        "conflicts_count": len(conflicts),
        "status": "pending",
    })

    return {
        "ok": True,
        "operation_id": operation_id,
        "tool_name": tool_name,
        "target": target,
        "target_id": target_id,
        "blast_radius": blast_radius,
        "reversibility_class": reversibility_class,
        "requires_approval": requires_approval,
        "conflicts": conflicts,
        "plan": plan,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# 2. execute_operation
# ---------------------------------------------------------------------------

def execute_operation(operation_id: str) -> dict:
    """
    Langkah 2 Guardian.
    BUG-01 FIX: requires_approval di-derive dari RULE ENGINE (tool_name immutable),
    BUKAN dari kolom requires_approval di DB yang bisa di-inject attacker.
    BUG-04 FIX: snapshot diambil di sini, tepat sebelum eksekusi.
    RACE FIX: atomic CAS UPDATE mencegah concurrent double-execute.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT * FROM operations WHERE id = ?", (operation_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": f"Operation {operation_id} tidak ditemukan"}

    op = dict(row)

    # BUG-01 FIX:
    # Masalah: penyerang inject requires_approval=0 langsung ke DB untuk bypass approval check.
    # Fix: re-derive requires_approval dari rule engine (tool_name adalah TEXT yang tidak berubah),
    # bukan dari kolom requires_approval integer yang bisa dimanipulasi.
    # Jika rule bilang require_approval=True -> WAJIB ada 'approved' di tabel approvals.
    # Selain itu, jika op di-force approved karena conflict saat propose (DB kolom=1 tapi rule=False),
    # kita tetap menghormati itu.
    # BUG-10 FIX: helper bersama, bukan derive ulang di tempat.
    effective_requires_approval = _effective_requires_approval(op)

    approval_row = conn.execute(
        "SELECT decision FROM approvals WHERE operation_id = ?", (operation_id,)
    ).fetchone()

    if effective_requires_approval:
        # Operasi butuh approval - cek tabel approvals
        if not approval_row or approval_row["decision"] != "approved":
            conn.close()
            return {
                "ok": False,
                "error": "Operasi ini butuh approval manusia sebelum dieksekusi",
                "status": op["status"],
            }
    else:
        # Tidak butuh approval - cek apakah di-deny
        if approval_row and approval_row["decision"] == "denied":
            conn.close()
            return {
                "ok": False,
                "error": "Operasi ini telah di-deny dan tidak bisa dieksekusi",
                "status": op["status"],
            }

    # RACE FIX: atomic Compare-And-Swap (CAS) — set status='executing' HANYA jika
    # status masih 'pending' atau 'approved' pada saat UPDATE dieksekusi.
    # SQLite menjamin UPDATE ini bersifat atomik: jika dua request concurrent sampai
    # di sini bersamaan, hanya satu yang akan berhasil mengubah row (rowcount=1).
    # Request kedua akan mendapat rowcount=0 dan langsung ditolak — mencegah
    # double-execution dan replay attack tanpa perlu distributed lock.
    cas_cursor = conn.execute(
        """UPDATE operations
           SET status='executing', executed_at=?
           WHERE id=? AND status IN ('pending', 'approved')""",
        (_utcnow_iso(), operation_id),
    )
    conn.commit()

    if cas_cursor.rowcount == 0:
        # Kalah race atau status sudah bukan pending/approved
        current = conn.execute(
            "SELECT status FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
        conn.close()
        current_status = current["status"] if current else "unknown"
        return {
            "ok": False,
            "error": f"Status operasi '{current_status}' tidak bisa dieksekusi (sudah dieksekusi atau sedang berjalan)",
        }

    # M18 FIX: parsing params yang defensif.
    #
    # Baris ini dulunya `json.loads(...)` polos, di LUAR try/except eksekusi
    # yang ada di bawah. Dua akibatnya kalau kolomnya rusak (ditulis lama,
    # diubah manual lewat sqlite3, atau korup): exception melesat keluar
    # sebagai 500 tanpa konteks, DAN — yang lebih penting — operasi sudah
    # berstatus 'executing' serta sudah commit di CAS di atas, jadi ia
    # tersangkut di sana selamanya dan menutup antrean untuk id itu.
    # Sekarang kegagalan parsing menandai baris 'failed' lalu kembali dengan
    # error yang jelas, sehingga statusnya konsisten dengan hasilnya.
    try:
        params = json.loads(op["params_json"] or "{}")
    except (TypeError, ValueError) as exc:
        conn.execute(
            "UPDATE operations SET status='failed' WHERE id=?",
            (operation_id,),
        )
        conn.commit()
        conn.close()
        return {
            "ok": False,
            "error": (
                f"params operasi tidak bisa dibaca sebagai JSON ({exc}); "
                "operasi ditandai gagal"
            ),
        }
    if not isinstance(params, dict):
        conn.execute(
            "UPDATE operations SET status='failed' WHERE id=?",
            (operation_id,),
        )
        conn.commit()
        conn.close()
        return {
            "ok": False,
            "error": "params operasi bukan objek JSON (dict); operasi ditandai gagal",
        }

    # BUG-04 FIX: ambil snapshot SEKARANG (tepat sebelum eksekusi)
    snapshot_ref, rollback_command = _take_snapshot(op["tool_name"], params)

    # Simpan snapshot_ref & rollback_command ke DB
    conn.execute(
        "UPDATE operations SET snapshot_ref=?, rollback_command=? WHERE id=?",
        (snapshot_ref, rollback_command, operation_id),
    )
    conn.commit()

    _emit("operation_executing", {
        "operation_id": operation_id, "tool_name": op["tool_name"]
    })

    # Eksekusi
    exec_ok, exec_msg = True, ""
    try:
        if op["tool_name"].startswith("db.run_migration"):
            exec_ok, exec_msg = _exec_migration(params)
        elif op["tool_name"].startswith("service.restart"):
            exec_ok, exec_msg = True, "service.restart stub - OK"
        elif op["tool_name"].startswith("config.write"):
            exec_ok, exec_msg = _exec_config_write(params)
        elif op["tool_name"].startswith("file.delete"):
            exec_ok, exec_msg = _exec_file_delete(params, snapshot_ref)
        else:
            exec_ok, exec_msg = False, f"Tool '{op['tool_name']}' tidak dikenal - fail-closed"
    except Exception as e:
        exec_ok, exec_msg = False, str(e)

    if not exec_ok:
        rollback_ok = _rollback_and_finalize(
            conn, operation_id, rollback_command, mark_verified_at=False)
        _emit("operation_rolled_back" if rollback_ok else "operation_failed", {
            "operation_id": operation_id,
            "reason": exec_msg,
            "rollback_ok": rollback_ok,
        })
        return {
            "ok": False,
            "operation_id": operation_id,
            "status": "rolled_back" if rollback_ok else "failed",
            "error": exec_msg,
            "rollback_ok": rollback_ok,
        }

    verify_ok, verify_msg, verify_warnings = _verify_operation(op["tool_name"], params)
    if not verify_ok:
        rollback_ok = _rollback_and_finalize(
            conn, operation_id, rollback_command, mark_verified_at=True)
        _emit("operation_rolled_back" if rollback_ok else "operation_failed", {
            "operation_id": operation_id,
            "reason": f"Verification failed: {verify_msg}",
            "rollback_ok": rollback_ok,
        })
        return {
            "ok": False,
            "operation_id": operation_id,
            "status": "rolled_back" if rollback_ok else "failed",
            "error": f"Verification failed: {verify_msg}",
            "rollback_ok": rollback_ok,
        }

    conn.execute(
        "UPDATE operations SET status='verified', verified_at=? WHERE id=?",
        (_utcnow_iso(), operation_id),
    )
    conn.commit()

    # GLITCH-3 FIX: invariant global (applies_to='*') dievaluasi SESUDAH status
    # terminal ditulis — invariant ini menilai state akhir operasi, jadi
    # menjalankannya sebelum commit akan menghasilkan false-positive.
    global_failures = [
        f"{r['id']}: {r['message']}"
        for r in _run_global_invariants(operation_id) if not r["passed"]
    ]
    conn.close()

    _emit("operation_verified", {
        "operation_id": operation_id,
        "tool_name": op["tool_name"],
        "verify_msg": verify_msg,
        "status": "verified",
    })

    all_warnings = verify_warnings + global_failures
    if all_warnings:
        _emit("operation_warning", {
            "operation_id": operation_id,
            "tool_name": op["tool_name"],
            "warnings": all_warnings,
        })

    return {
        "ok": True,
        "operation_id": operation_id,
        "status": "verified",
        "verify_msg": verify_msg,
        "verify_warnings": all_warnings,
    }


# ---------------------------------------------------------------------------
# Eksekutor per tipe operasi
# ---------------------------------------------------------------------------

def _split_sql_statements(sql: str) -> list[str]:
    """
    ISSUE-34 FIX: pecah SQL menjadi statement dengan LEXER, bukan split(";").

    Yang harus dihormati:
      - string literal  '...'   dengan escape '' (dua kutip)
      - identifier     "..."   dengan escape ""
      - identifier     `...`    (SQLite/MySQL)
      - identifier     [...]    (SQL Server)
      - komentar baris  -- ... hingga akhir baris
      - komentar blok  /* ... */

    Karakter ';' di dalam salah satu quoting/komentar di atas TIDAK boleh
    memotong statement. Contoh yang rusak kalau tetap split(";"):

        INSERT INTO config VALUES ('key', 'value;with;semicolons');

    Akan jadi 2 statement, dan statement pertama berisi SQL terpotong yang
    tidak valid — data tersimpan tidak lengkap atau ROLLBACK menyesatkan.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        # --- komentar blok: /* ... */ -------------------------------------
        if ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        # --- komentar baris: -- ... ---------------------------------------
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            continue

        # --- string literal '...' dengan escape '' ------------------------
        if ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                if sql[i] == "'":
                    # '' di dalam string = literal kutip tunggal
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("''")
                        i += 2
                        continue
                    buf.append("'")
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            continue

        # --- identifier/quoted: "..." atau `...` -------------------------
        if ch in ('"', "`"):
            closer = ch
            buf.append(ch)
            i += 1
            while i < n:
                if sql[i] == closer:
                    if i + 1 < n and sql[i + 1] == closer:
                        buf.append(closer * 2)
                        i += 2
                        continue
                    buf.append(closer)
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            continue
        if ch == "[":
            end = sql.find("]", i)
            if end == -1:
                buf.append(sql[i:])
                i = n
                continue
            buf.append(sql[i : end + 1])
            i = end + 1
            continue

        # --- statement terminator ----------------------------------------
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _exec_migration(params: dict) -> tuple[bool, str]:
    """
    BUG-B FIX: ganti executescript() (auto-commit tiap statement) ke
    explicit transaction dengan execute() per statement.
    Jika salah satu statement gagal, ROLLBACK dilakukan dan snapshot masih valid.

    ISSUE-34 FIX: statement dipecah dengan _split_sql_statements() yang
    menghormati string literal dan komentar, bukan split(";").
    """
    sql = params.get("sql", "")
    db_path = params.get("db_path", _db_path())
    if not sql:
        return False, "Tidak ada SQL di params['sql']"
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None  # autocommit off, kita kelola sendiri
        conn.execute("BEGIN")
        try:
            statements = _split_sql_statements(sql)
            if not statements:
                conn.execute("ROLLBACK")
                conn.close()
                return False, "Tidak ada statement SQL yang bisa dieksekusi"
            for statement in statements:
                conn.execute(statement)
            conn.execute("COMMIT")
            conn.close()
            return True, f"Migration berhasil ({len(statements)} statement): {sql[:80]}"
        except Exception as e:
            conn.execute("ROLLBACK")
            conn.close()
            return False, f"Migration gagal: {e}"
    except Exception as e:
        return False, f"Migration gagal (koneksi): {e}"


def _exec_config_write(params: dict) -> tuple[bool, str]:
    """
    Tulis file konfigurasi.

    H7 FIX — dua cacat sekaligus di versi lama:

    1. TIDAK ADA validasi path sama sekali. `Path(file_path).write_text(...)`
       menerima path absolut apa pun, jadi operasi yang lolos guardian bisa
       menulis di luar repo: ~/.ssh/authorized_keys, file sistem, .env,
       atau base64 payload apa pun. Padahal settings.py sudah punya
       guard dua-lapis (allowed_roots + anti-sensitif) yang dipakai endpoint
       lain; guardian adalah satu-satunya yang tidak memakainya.

    2. write_text() meng-truncate lalu menulis — bukan atomik. Proses mati di
       tengah (crash, disk penuh, Ctrl-C) menyisakan file config KOSONG atau
       setengah tulis, dan karena file ini bisa jadi konfigurasi yang dipakai
       saat boot, dampaknya boot loop yang tidak bisa dijelaskan dari log.

    Sekarang: guard dulu, lalu tulis lewat file tempurung di direktori yang
    sama + os.replace() yang atomik di filesystem yang sama. Mode file asli
    dipertahankan (mkstemp default 0600 akan menurunkan permission config
    yang semestinya 0644).
    """
    file_path = params.get("file_path", "")
    content = params.get("content", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"

    # Guard 1: path harus di dalam workspace dan bukan file sensitif.
    if not _settings.is_writable_path(file_path):
        return False, (
            f"Path ditolak guardian: '{file_path}' berada di luar workspace "
            f"yang diizinkan atau menunjuk file kredensial/database"
        )

    # Guard 2: direktori induk harus ada. os.replace() akan gagal kalau tidak,
    # tapi cek eksplisit supaya pesannya bisa ditindaklanjuti dan supaya
    # direktori baru tidak pernah dibuat diam-diam di luar ekspektasi.
    target = Path(os.path.realpath(os.path.expanduser(str(file_path))))
    parent = target.parent
    if not parent.is_dir():
        return False, f"Direktori induk tidak ada: {parent}"

    # Pertahankan permission file yang lama; file baru memakai 0644.
    try:
        mode = target.stat().st_mode & 0o7777
    except OSError:
        mode = 0o644

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)  # atomik: pembaca tidak pernah lihat separuh
        tmp_path = None
    except OSError as e:
        return False, f"Gagal menulis '{target}': {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return True, f"Config ditulis ke {file_path}"


def _exec_file_delete(params: dict, snapshot_ref: str | None) -> tuple[bool, str]:
    """
    GLITCH-5 FIX: validasi snapshot benar-benar ada dan ukurannya > 0
    sebelum menghapus file original. Mencegah data loss permanen jika
    .bak korup atau disk penuh saat snapshot.
    """
    file_path = params.get("file_path", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"
    # Validasi path SEBELAMANYA menolak di sini juga (lihat _exec_config_write):
    # tanpa ini guardian bisa menghapus file apa pun yang bisa dihapus proses,
    # termasuk yang berada jauh di luar repo — dan snapshot yang disimpan
    # sebagai .bak akan berada di lokasi yang sama di luar workspace.
    if not _settings.is_writable_path(file_path):
        return False, (
            f"Path ditolak guardian: '{file_path}' berada di luar workspace "
            f"yang diizinkan atau menunjuk file kredensial/database"
        )
    if not snapshot_ref:
        return False, "Tidak ada snapshot - file delete dibatalkan (fail-safe)"
    # GLITCH-5 FIX: pastikan file .bak benar-benar ada dan tidak kosong
    bak = Path(snapshot_ref)
    if not bak.exists() or bak.stat().st_size == 0:
        return False, f"Snapshot tidak valid atau kosong: {snapshot_ref} — file delete dibatalkan"
    try:
        Path(file_path).unlink()
        return True, f"File {file_path} dihapus"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# 3. list_pending_approvals
# ---------------------------------------------------------------------------

def list_pending_approvals(target_id: "str | None" = None) -> dict:
    """
    BUG-D FIX: hanya kembalikan operasi dengan status 'pending' (belum diputuskan).
    Sebelumnya WHERE status IN ('pending','approved') menyebabkan operasi yang
    sudah diapprove ikut tampil di pending list — membingungkan dan berpotensi
    double-approval dari UI.

    BUG-10 FIX: filter "butuh approval" TIDAK lagi pakai kolom
    operations.requires_approval, tapi helper yang sama dengan execute_operation
    (_effective_requires_approval). Kolom DB cuma snapshot aturan saat propose,
    jadi ia bisa basi kalau aturannya berubah. Kalau tidak disamakan di sini,
    operasi bisa requiring-approval saat execute tapi tidak pernah muncul di
    daftar ini — dead-end yang mustahil di-approve.

    `target_id` (default None = semua target) menyaring operasi per repository
    atau folder. Tanpa itu, approval repo A muncul di daftar repo B dan user
    bisa menyetujui operasi yang salah target hanya karena namanya mirip.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    sql = """SELECT o.*, a.decision as approval_decision
             FROM operations o
             LEFT JOIN approvals a ON a.operation_id = o.id
             WHERE o.status = 'pending'"""
    params: tuple = ()
    if target_id is not None:
        sql += " AND COALESCE(o.target_id, '') = ?"
        params = (target_id,)
    rows = conn.execute(sql + " ORDER BY o.created_at DESC", params).fetchall()
    conn.close()

    pending = [dict(r) for r in rows if _effective_requires_approval(r)]
    return {"ok": True, "count": len(pending), "pending": pending}


# ---------------------------------------------------------------------------
# 4. approve_operation
# ---------------------------------------------------------------------------

def approve_operation(operation_id: str, decision: str, note: str = "") -> dict:
    if decision not in ("approved", "denied"):
        return {"ok": False, "error": "decision harus 'approved' atau 'denied'"}

    conn = sqlite3.connect(_db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        # BEGIN IMMEDIATE mengambil lock RESERVED sekarang, bukan saat commit,
        # jadi hanya satu writer yang boleh masuk ke bagian check-then-write
        # di bawah ini. Tanpa ini, N request approve/deny bersamaan semuanya
        # membaca status lama, semuanya lolos guard, lalu saling menimpa.
        # Diletakkan DI DALAM try supaya connection tetap di-close kalau
        # lock-nya gagal dibuat (mis. database sedang terkunci).
        conn.execute("BEGIN IMMEDIATE")
        op = conn.execute(
            "SELECT id, status, tool_name FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()

        if not op:
            conn.execute("ROLLBACK")
            return {"ok": False, "error": f"Operation {operation_id} tidak ditemukan"}

        new_status = "approved" if decision == "approved" else "denied"

        # BUG-09 FIX: guard pakai ALLOWLIST (APPROVABLE_STATUSES), bukan
        # sekadar "bukan terminal". Listrik versioning:
        #   - 'executing'              : operasi sedang berjalan, menimpanya
        #                                 jadi 'approved' membuka celah re-execute
        #                                 karena CAS execute mengizinkan 'approved'.
        #   - 'executed_unverified'    : sudah dijalankan, approve lagi = replay.
        #_denied_ tetap bisa muncul sebagai 'denied' setelah deny normal.
        cur = conn.execute(
            "UPDATE operations SET status=? WHERE id=? AND status IN "
            f"({','.join('?' * len(APPROVABLE_STATUSES))})",
            (new_status, operation_id, *sorted(APPROVABLE_STATUSES)),
        )

        if cur.rowcount == 0:
            # Baris tidak berubah: entah statusnya tidak approvable, atau
            # request lain menang duluan. Baca status terbaru untuk pesan akurat.
            current = conn.execute(
                "SELECT status FROM operations WHERE id = ?", (operation_id,)
            ).fetchone()
            conn.execute("ROLLBACK")
            now = current["status"] if current else "unknown"
            return {
                "ok": False,
                "error": (
                    f"Operasi berstatus '{now}' tidak bisa diubah statusnya "
                    f"lewat approval (hanya 'pending'/'approved' yang boleh)."
                ),
                "status": now,
                "terminal": now in TERMINAL_STATUSES,
            }

        conn.execute(
            """INSERT INTO approvals (operation_id, decision, decided_at, note)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(operation_id) DO UPDATE
                 SET decision=excluded.decision,
                     decided_at=excluded.decided_at,
                     note=excluded.note""",
            (operation_id, decision, _utcnow_iso(), note),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        raise
    conn.close()

    _emit(
        "operation_approved" if decision == "approved" else "operation_denied",
        {"operation_id": operation_id, "decision": decision, "tool_name": op["tool_name"]},
    )

    return {"ok": True, "operation_id": operation_id, "decision": decision, "status": new_status, "new_status": new_status}
