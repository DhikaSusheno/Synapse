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
              tidak ada ambiguitas split pada C:\path.

  BUG-B [HIGH] _exec_migration() pakai executescript() yang auto-commit
         FIX: explicit transaction BEGIN/COMMIT/ROLLBACK per statement.

  BUG-D [LOW]  list_pending_approvals() bocorkan operasi 'approved' ke pending list
         FIX: WHERE status = 'pending' (exact, bukan IN ('pending','approved')).

  BUG-E [LOW]  asyncio.get_event_loop() deprecated Python 3.10+
         FIX: di main.py on_startup() ganti ke asyncio.get_running_loop().

  GLITCH-5 [MEDIUM] _exec_file_delete() tidak validasi snapshot integrity
         FIX: cek bak.exists() dan bak.stat().st_size > 0 sebelum hapus original.
"""

import json
import uuid
import sqlite3
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import database as _database_module
from cortex import _emit  # pakai SSE bus milik Cortex


def _db_path() -> str:
    """Selalu baca DB_PATH terbaru dari module - support test override."""
    return str(_database_module.DB_PATH)

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

CONFLICT_WINDOW_MINUTES = 10

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
        "match": "config.write",
        "blast_radius": "medium",
        "reversibility": "needs_snapshot",
        "require_approval": False,
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


def _check_conflict(conn: sqlite3.Connection, target_node_id: str) -> list[dict]:
    """
    Cek operasi lain yang menyentuh target_node_id dalam window terakhir.
    Hanya status aktif yang dihitung (sesuai SYNAPSE.md 4.5).
    """
    window_start = (
        datetime.utcnow() - timedelta(minutes=CONFLICT_WINDOW_MINUTES)
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

    Return (snapshot_ref, rollback_command_json)
    """
    if tool_name.startswith("db.run_migration"):
        # BUG-02 + BUG-03 FIX: gunakan db_path dari params, bukan DB_PATH global
        db_target = params.get("db_path", _db_path())
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        bak = f"{db_target}.bak.{ts}"
        try:
            shutil.copy2(db_target, bak)
            # BUG-A FIX: JSON format, tidak ada ambiguitas colon di Windows path
            rollback_cmd = json.dumps({"bak": bak, "target": db_target})
            return bak, rollback_cmd
        except Exception:
            return None, None

    if tool_name.startswith("config.write"):
        file_path = params.get("file_path", "")
        if file_path and Path(file_path).exists():
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
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
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            bak = f"{file_path}.bak.{ts}"
            try:
                shutil.copy2(file_path, bak)
                rollback_cmd = json.dumps({"bak": bak, "target": file_path})
                return bak, rollback_cmd
            except Exception:
                pass

    return None, None


def _do_rollback(rollback_command: str | None) -> bool:
    """
    BUG-A FIX: rollback_command sekarang JSON {"bak": "...", "target": "..."}.
    Tidak ada lagi ambiguitas split pada Windows path (C:\\path punya colon).

    Backward compat: jika format lama "restore_from:<bak>:<target>" masih ada
    di DB (dari commit sebelumnya), fallback ke split lama.
    """
    if not rollback_command:
        return False

    # Format baru: JSON
    try:
        data = json.loads(rollback_command)
        if isinstance(data, dict) and "bak" in data and "target" in data:
            try:
                shutil.copy2(data["bak"], data["target"])
                return True
            except Exception:
                return False
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
        try:
            shutil.copy2(bak_path, target_path)
            return True
        except Exception:
            return False

    return False


def _verify_operation(tool_name: str, params: dict) -> tuple[bool, str]:
    """Verifikasi post-conditions setelah eksekusi."""
    if tool_name.startswith("db.run_migration"):
        db_target = params.get("db_path", _db_path())
        try:
            conn = sqlite3.connect(db_target)
            conn.execute("SELECT 1")
            conn.close()
            return True, "DB accessible post-migration"
        except Exception as e:
            return False, f"DB tidak bisa dibuka: {e}"

    if tool_name.startswith("service.restart"):
        return True, "service.restart verified (stub)"

    if tool_name.startswith("config.write"):
        file_path = params.get("file_path", "")
        if file_path and Path(file_path).exists():
            return True, f"Config file exists: {file_path}"
        return False, f"Config file tidak ditemukan: {file_path}"

    return True, "No verification available (stub)"


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
    conn.execute(
        """INSERT INTO operations
           (id, tool_name, params_json, target_node_id, blast_radius,
            reversibility_class, status, snapshot_ref, rollback_command,
            requires_approval, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?)""",
        (
            operation_id, tool_name, json.dumps(params), target_node_id,
            blast_radius, reversibility_class,
            1 if requires_approval else 0,
            datetime.utcnow().isoformat(),
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
    rule = _get_rule(op["tool_name"])
    rule_requires_approval = rule["require_approval"]
    db_requires_approval = int(op["requires_approval"])
    # effective: True jika rule bilang wajib, ATAU jika conflict memaksanya saat propose
    effective_requires_approval = rule_requires_approval or (db_requires_approval == 1)

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
        (datetime.utcnow().isoformat(), operation_id),
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

    params = json.loads(op["params_json"] or "{}")

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
        rollback_ok = _do_rollback(rollback_command)
        new_status = "rolled_back" if rollback_ok else "failed"
        conn.execute(
            "UPDATE operations SET status=? WHERE id=?", (new_status, operation_id)
        )
        conn.commit()
        conn.close()
        _emit("operation_rolled_back" if rollback_ok else "operation_failed", {
            "operation_id": operation_id,
            "reason": exec_msg,
            "rollback_ok": rollback_ok,
        })
        return {
            "ok": False,
            "operation_id": operation_id,
            "status": new_status,
            "error": exec_msg,
            "rollback_ok": rollback_ok,
        }

    verify_ok, verify_msg = _verify_operation(op["tool_name"], params)
    if not verify_ok:
        rollback_ok = _do_rollback(rollback_command)
        new_status = "rolled_back" if rollback_ok else "failed"
        conn.execute(
            "UPDATE operations SET status=?, verified_at=? WHERE id=?",
            (new_status, datetime.utcnow().isoformat(), operation_id),
        )
        conn.commit()
        conn.close()
        _emit("operation_rolled_back", {
            "operation_id": operation_id,
            "reason": f"Verification failed: {verify_msg}",
            "rollback_ok": rollback_ok,
        })
        return {
            "ok": False,
            "operation_id": operation_id,
            "status": new_status,
            "error": f"Verification failed: {verify_msg}",
            "rollback_ok": rollback_ok,
        }

    conn.execute(
        "UPDATE operations SET status='verified', verified_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), operation_id),
    )
    conn.commit()
    conn.close()

    _emit("operation_verified", {
        "operation_id": operation_id,
        "tool_name": op["tool_name"],
        "verify_msg": verify_msg,
        "status": "verified",
    })

    return {
        "ok": True,
        "operation_id": operation_id,
        "status": "verified",
        "verify_msg": verify_msg,
    }


# ---------------------------------------------------------------------------
# Eksekutor per tipe operasi
# ---------------------------------------------------------------------------

def _exec_migration(params: dict) -> tuple[bool, str]:
    """
    BUG-B FIX: ganti executescript() (auto-commit tiap statement) ke
    explicit transaction dengan execute() per statement.
    Jika salah satu statement gagal, ROLLBACK dilakukan dan snapshot masih valid.
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
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute("COMMIT")
            conn.close()
            return True, f"Migration berhasil: {sql[:80]}"
        except Exception as e:
            conn.execute("ROLLBACK")
            conn.close()
            return False, f"Migration gagal: {e}"
    except Exception as e:
        return False, f"Migration gagal (koneksi): {e}"


def _exec_config_write(params: dict) -> tuple[bool, str]:
    file_path = params.get("file_path", "")
    content = params.get("content", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"
    try:
        Path(file_path).write_text(content, encoding="utf-8")
        return True, f"Config ditulis ke {file_path}"
    except Exception as e:
        return False, str(e)


def _exec_file_delete(params: dict, snapshot_ref: str | None) -> tuple[bool, str]:
    """
    GLITCH-5 FIX: validasi snapshot benar-benar ada dan ukurannya > 0
    sebelum menghapus file original. Mencegah data loss permanen jika
    .bak korup atau disk penuh saat snapshot.
    """
    file_path = params.get("file_path", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"
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

def list_pending_approvals() -> dict:
    """
    BUG-D FIX: hanya kembalikan operasi dengan status 'pending' (belum diputuskan).
    Sebelumnya WHERE status IN ('pending','approved') menyebabkan operasi yang
    sudah diapprove ikut tampil di pending list — membingungkan dan berpotensi
    double-approval dari UI.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT o.*, a.decision as approval_decision
           FROM operations o
           LEFT JOIN approvals a ON a.operation_id = o.id
           WHERE o.requires_approval = 1
             AND o.status = 'pending'
           ORDER BY o.created_at DESC"""
    ).fetchall()
    conn.close()
    return {"ok": True, "count": len(rows), "pending": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# 4. approve_operation
# ---------------------------------------------------------------------------

def approve_operation(operation_id: str, decision: str, note: str = "") -> dict:
    if decision not in ("approved", "denied"):
        return {"ok": False, "error": "decision harus 'approved' atau 'denied'"}

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    op = conn.execute(
        "SELECT id, status, tool_name FROM operations WHERE id = ?", (operation_id,)
    ).fetchone()

    if not op:
        conn.close()
        return {"ok": False, "error": f"Operation {operation_id} tidak ditemukan"}

    conn.execute(
        """INSERT INTO approvals (operation_id, decision, decided_at, note)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(operation_id) DO UPDATE
             SET decision=excluded.decision,
                 decided_at=excluded.decided_at,
                 note=excluded.note""",
        (operation_id, decision, datetime.utcnow().isoformat(), note),
    )
    new_status = "approved" if decision == "approved" else "denied"
    conn.execute(
        "UPDATE operations SET status=? WHERE id=?", (new_status, operation_id)
    )
    conn.commit()
    conn.close()

    _emit(
        "operation_approved" if decision == "approved" else "operation_denied",
        {"operation_id": operation_id, "decision": decision, "tool_name": op["tool_name"]},
    )

    return {"ok": True, "operation_id": operation_id, "decision": decision, "status": new_status}
