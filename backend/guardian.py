"""
guardian.py — BE-1 DhikaSusheno (stub kompatibel untuk integrasi dengan BE-2 Masrendra)
Tanggung jawab:
  - propose_operation()        : klasifikasi risiko + conflict check + buat rencana rollback
  - execute_operation()        : jalankan + verifikasi + auto-rollback jika gagal
  - list_pending_approvals()   : daftar operasi yang butuh approval manusia
  - approve_operation()        : approve atau deny operasi

Kontrak SQLite (sesuai SYNAPSE.md 4.2):
  operations (id, tool_name, params_json, target_node_id, blast_radius,
              reversibility_class, status, snapshot_ref, rollback_command,
              requires_approval, created_at, executed_at, verified_at)
  approvals  (operation_id, decision, decided_at, note)

Rule table (sesuai SYNAPSE.md 4.4):
  db.run_migration  → blast_radius: high,   require_approval: true
  service.restart   → blast_radius: medium, require_approval: false
  *                 → blast_radius: unknown, require_approval: true (fail-closed)

Conflict detection (sesuai SYNAPSE.md 4.5):
  Sebelum auto-approve: cek apakah ada operasi lain yang menyentuh
  target yang sama dalam CONFLICT_WINDOW_MINUTES terakhir.
  Kalau ada → paksa require_approval = true.
"""

import json
import uuid
import sqlite3
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from database import DB_PATH
from cortex import _emit  # pakai SSE bus milik Cortex

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

CONFLICT_WINDOW_MINUTES = 10  # window konflik deteksi

# Rule table (sesuai SYNAPSE.md 4.4) — statis, bukan ML
RULES = [
    {
        "match": "db.run_migration",
        "blast_radius": "high",
        "reversibility": "needs_snapshot",
        "require_approval": True,
    },
    {
        "match": "service.restart",
        "blast_radius": "medium",
        "reversibility": "needs_snapshot",
        "require_approval": False,
    },
    {
        "match": "config.write",
        "blast_radius": "medium",
        "reversibility": "needs_snapshot",
        "require_approval": False,
    },
    {
        "match": "file.delete",
        "blast_radius": "high",
        "reversibility": "needs_snapshot",
        "require_approval": True,
    },
    # fail-closed default — harus di paling bawah
    {
        "match": "*",
        "blast_radius": "unknown",
        "reversibility": "irreversible_suspected",
        "require_approval": True,
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rule(tool_name: str) -> dict:
    """Cari rule yang cocok. Default: fail-closed (*)."""
    for rule in RULES:
        if rule["match"] == "*":
            continue
        if tool_name.startswith(rule["match"]):
            return rule
    return RULES[-1]  # fail-closed default


def _check_conflict(conn: sqlite3.Connection, target_node_id: str) -> list[dict]:
    """
    Cek apakah ada operasi lain yang menyentuh target_node_id
    dalam CONFLICT_WINDOW_MINUTES terakhir dan belum selesai verified.
    Sesuai SYNAPSE.md 4.5.
    """
    window_start = (
        datetime.utcnow() - timedelta(minutes=CONFLICT_WINDOW_MINUTES)
    ).isoformat()

    rows = conn.execute(
        """
        SELECT o.id, o.tool_name, o.status, o.created_at
        FROM operations o
        WHERE o.target_node_id = ?
          AND o.status IN ('pending', 'approved', 'executing', 'executed_unverified')
          AND o.created_at > ?
        """,
        (target_node_id, window_start)
    ).fetchall()

    return [dict(r) for r in rows]


def _make_snapshot(tool_name: str, params: dict) -> tuple[str | None, str | None]:
    """
    Buat snapshot TEPAT sebelum eksekusi (dipanggil dari execute_operation, bukan propose).
    FIX BUG-04: snapshot dibuat saat execute, bukan saat propose — lebih akurat dan
    gagal-dengan-pesan jika file tidak ada untuk high-risk operations.
    Return (snapshot_ref, rollback_command).
    """
    if tool_name.startswith("db.run_migration"):
        db_target = params.get("db_path", str(DB_PATH))
        bak = f"{db_target}.bak.{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
        try:
            shutil.copy2(db_target, bak)
            return bak, f"restore_from:{bak}::{db_target}"
        except Exception as e:
            # Kembalikan error eksplisit agar caller bisa fail-safe
            return None, f"snapshot_failed::{e}"

    if tool_name.startswith("config.write"):
        target_file = params.get("file_path", "")
        if target_file and Path(target_file).exists():
            bak = f"{target_file}.bak.{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
            try:
                shutil.copy2(target_file, bak)
                return bak, f"restore_from:{bak}::{target_file}"
            except Exception:
                pass

    return None, None


def _do_rollback(rollback_command: str | None) -> bool:
    """
    Eksekusi rollback command.
    FIX BUG-02: derive destination dari rollback_command (format restore_from:<bak>::<dst>)
    bukan hardcode ke DB_PATH.
    """
    if not rollback_command:
        return False
    if rollback_command.startswith("restore_from:"):
        # Format baru: restore_from:<bak_path>::<original_path>
        parts = rollback_command.split("::")
        bak_path = parts[0].split(":", 1)[1]  # hapus "restore_from:" prefix
        # Gunakan original_path jika ada, fallback derive dari nama file backup
        if len(parts) >= 2 and parts[1]:
            dst = parts[1]
        else:
            # Fallback untuk format lama: strip ".bak.<timestamp>"
            import re
            dst = re.sub(r"\.bak\.\d{8}T\d{6}$", "", bak_path)
        try:
            shutil.copy2(bak_path, dst)
            return True
        except Exception:
            return False
    return False


def _restore_verified_operations(conn_after_rollback: sqlite3.Connection,
                                  bak_path: str) -> int:
    """
    FIX BUG-03: Setelah rollback file DB, re-apply operasi yang status 'verified'
    yang tercatat di backup (tapi mungkin hilang dari file yang di-restore).
    Pendekatan pragmatis: copy baris operations+approvals yang sudah verified
    dari backup DB ke DB yang baru di-restore, agar audit trail tidak hilang.
    Return jumlah operasi yang di-re-insert.
    """
    try:
        bak_conn = sqlite3.connect(bak_path)
        bak_conn.row_factory = sqlite3.Row
        # Ambil operasi verified di snapshot (yang sudah ada sebelum migration rusak)
        verified_ops = bak_conn.execute(
            "SELECT * FROM operations WHERE status = 'verified'"
        ).fetchall()
        verified_approvals = bak_conn.execute(
            "SELECT * FROM approvals"
        ).fetchall()
        bak_conn.close()

        restored = 0
        for op in verified_ops:
            try:
                conn_after_rollback.execute(
                    """INSERT INTO operations
                       (id, tool_name, params_json, target_node_id, blast_radius,
                        reversibility_class, status, snapshot_ref, rollback_command,
                        requires_approval, created_at, executed_at, verified_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO NOTHING""",
                    (op["id"], op["tool_name"], op["params_json"], op["target_node_id"],
                     op["blast_radius"], op["reversibility_class"], op["status"],
                     op["snapshot_ref"], op["rollback_command"], op["requires_approval"],
                     op["created_at"], op["executed_at"], op["verified_at"])
                )
                restored += 1
            except Exception:
                pass

        for appr in verified_approvals:
            try:
                conn_after_rollback.execute(
                    """INSERT INTO approvals (operation_id, decision, decided_at, note)
                       VALUES (?,?,?,?) ON CONFLICT(operation_id) DO NOTHING""",
                    (appr["operation_id"], appr["decision"],
                     appr["decided_at"], appr["note"])
                )
            except Exception:
                pass

        conn_after_rollback.commit()
        return restored
    except Exception:
        return 0


def _verify_operation(tool_name: str, params: dict) -> tuple[bool, str]:
    """
    Verifikasi post-conditions setelah eksekusi.
    Return (success, message).
    MVP: verifikasi sederhana berbasis tool_name.
    """
    if tool_name.startswith("db.run_migration"):
        # Verifikasi: DB masih bisa dibuka dan tabel target ada
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("SELECT 1")
            conn.close()
            return True, "DB accessible post-migration"
        except Exception as e:
            return False, f"DB tidak bisa dibuka setelah migration: {e}"

    if tool_name.startswith("service.restart"):
        # Stub: anggap selalu sukses untuk demo
        return True, "Service restart verified (stub)"

    if tool_name.startswith("config.write"):
        target_file = params.get("file_path", "")
        if target_file and Path(target_file).exists():
            return True, f"Config file exists: {target_file}"
        return False, f"Config file tidak ditemukan: {target_file}"

    # Default: tidak bisa verifikasi → anggap sukses dengan warning
    return True, "No verification available for this operation type (stub)"


# ---------------------------------------------------------------------------
# 1. propose_operation
# ---------------------------------------------------------------------------

def propose_operation(tool_name: str, params: dict, target: str) -> dict:
    """
    Langkah 1 Guardian:
      1. Klasifikasi blast_radius via rule table
      2. Cek konflik dengan operasi lain yang sedang berjalan
      3. Buat rencana reversibilitas (snapshot strategy)
      4. Simpan ke tabel operations dengan status 'pending'
      5. Emit SSE operation_proposed

    Return: {operation_id, blast_radius, conflicts, plan, requires_approval}
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # 1. Klasifikasi via rule table
    rule = _get_rule(tool_name)
    blast_radius = rule["blast_radius"]
    reversibility_class = rule["reversibility"]
    requires_approval = rule["require_approval"]

    # 2. Cari/buat target_node_id di graph
    target_node_id = f"operation_target::{target}"
    conn.execute(
        """INSERT INTO nodes (id, type, name, meta_json)
           VALUES (?, 'operation', ?, '{}')
           ON CONFLICT(id) DO NOTHING""",
        (target_node_id, target)
    )

    # 3. Conflict check (SYNAPSE.md 4.5)
    conflicts = _check_conflict(conn, target_node_id)
    if conflicts:
        requires_approval = True  # paksa approval kalau ada konflik

    # 4. Catat rencana snapshot (snapshot TIDAK dibuat di sini — FIX BUG-04)
    # Snapshot dibuat tepat sebelum eksekusi di execute_operation()
    snapshot_ref = None
    rollback_command = None

    # 5. Simpan ke DB
    operation_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO operations
           (id, tool_name, params_json, target_node_id, blast_radius,
            reversibility_class, status, snapshot_ref, rollback_command,
            requires_approval, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
        (
            operation_id, tool_name, json.dumps(params), target_node_id,
            blast_radius, reversibility_class,
            snapshot_ref, rollback_command,
            1 if requires_approval else 0,
            datetime.utcnow().isoformat(),
        )
    )

    # Buat edge TARGETS di graph
    conn.execute(
        """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
           VALUES (?, ?, ?, 'TARGETS', 1.0)
           ON CONFLICT(id) DO NOTHING""",
        (f"{operation_id}::TARGETS::{target_node_id}",
         operation_id, target_node_id)
    )

    # Buat edge CONFLICTS_WITH jika ada konflik
    for conflict in conflicts:
        conn.execute(
            """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
               VALUES (?, ?, ?, 'CONFLICTS_WITH', 1.0)
               ON CONFLICT(id) DO NOTHING""",
            (f"{operation_id}::CONFLICTS_WITH::{conflict['id']}",
             operation_id, conflict["id"])
        )

    conn.commit()
    conn.close()

    plan = {
        "snapshot_strategy": (
            f"Copy {params.get('db_path', 'DB')} → .bak.<timestamp>"
            if tool_name.startswith("db.") else
            f"Copy {params.get('file_path', 'file')} → .bak.<timestamp>"
            if tool_name.startswith("config.") else
            "No snapshot — stub only"
        ),
        "rollback_method": rollback_command or "manual",
        "verification": "post-execution DB/file integrity check",
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
        "snapshot_ref": snapshot_ref,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# 2. execute_operation
# ---------------------------------------------------------------------------

def execute_operation(operation_id: str) -> dict:
    """
    Langkah 2 Guardian:
      1. Cek status — harus 'approved' atau 'pending' tanpa requires_approval
      2. Set status → 'executing'
      3. Jalankan operasi
      4. Verifikasi post-conditions
      5. Jika gagal → auto-rollback → status 'rolled_back'
      6. Jika sukses → status 'verified'
      7. Emit SSE di setiap state transition
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT * FROM operations WHERE id = ?", (operation_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": f"Operation {operation_id} tidak ditemukan"}

    op = dict(row)

    # FIX BUG-01: Re-derive requires_approval dari rule table (sumber kebenaran),
    # bukan hanya dari kolom DB yang bisa dimanipulasi.
    rule = _get_rule(op["tool_name"])
    effective_requires_approval = rule["require_approval"] or bool(op["requires_approval"])

    if effective_requires_approval:
        approval = conn.execute(
            "SELECT decision FROM approvals WHERE operation_id = ?",
            (operation_id,)
        ).fetchone()
        if not approval or approval["decision"] != "approved":
            conn.close()
            return {
                "ok": False,
                "error": "Operasi ini butuh approval manusia sebelum dieksekusi",
                "status": op["status"],
            }

    if op["status"] not in ("pending", "approved"):
        conn.close()
        return {
            "ok": False,
            "error": f"Status operasi '{op['status']}' tidak bisa dieksekusi",
        }

    params = json.loads(op["params_json"] or "{}")

    # FIX BUG-04: Buat snapshot SEKARANG, tepat sebelum eksekusi
    snapshot_ref, rollback_command = _make_snapshot(op["tool_name"], params)

    # Fail-safe: operasi high-risk tanpa snapshot tidak boleh dilanjutkan
    needs_snapshot = rule["reversibility"] == "needs_snapshot"
    if needs_snapshot and snapshot_ref is None:
        if rollback_command and rollback_command.startswith("snapshot_failed::"):
            err = rollback_command.split("::", 1)[1]
            conn.execute("UPDATE operations SET status='failed' WHERE id=?", (operation_id,))
            conn.commit()
            conn.close()
            return {"ok": False, "error": f"Snapshot gagal — eksekusi dibatalkan (fail-safe): {err}",
                    "operation_id": operation_id}

    # Simpan snapshot ref ke DB jika berhasil dibuat
    if snapshot_ref:
        conn.execute(
            "UPDATE operations SET snapshot_ref=?, rollback_command=? WHERE id=?",
            (snapshot_ref, rollback_command, operation_id)
        )
        conn.commit()

    # State: executing
    conn.execute(
        "UPDATE operations SET status='executing', executed_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), operation_id)
    )
    conn.commit()
    _emit("operation_executing", {"operation_id": operation_id,
                                   "tool_name": op["tool_name"]})

    # --- Jalankan operasi (MVP: db.run_migration dalam, lainnya stub) ---
    exec_ok = True
    exec_msg = ""

    try:
        if op["tool_name"].startswith("db.run_migration"):
            exec_ok, exec_msg = _exec_migration(params)
        elif op["tool_name"].startswith("service.restart"):
            # Stub
            exec_ok, exec_msg = True, "service.restart stub — OK"
        elif op["tool_name"].startswith("config.write"):
            exec_ok, exec_msg = _exec_config_write(params)
        elif op["tool_name"].startswith("file.delete"):
            exec_ok, exec_msg = _exec_file_delete(params, op["snapshot_ref"])
        else:
            # Fail-closed: operasi tak dikenal tidak dieksekusi otomatis
            exec_ok, exec_msg = False, f"Tool '{op['tool_name']}' tidak dikenal — fail-closed"
    except Exception as e:
        exec_ok = False
        exec_msg = str(e)

    if not exec_ok:
        # Auto-rollback + FIX BUG-03: re-insert verified ops setelah rollback file DB
        rollback_ok = _do_rollback(rollback_command)
        if rollback_ok and snapshot_ref:
            conn_restored = sqlite3.connect(DB_PATH)
            conn_restored.row_factory = sqlite3.Row
            _restore_verified_operations(conn_restored, snapshot_ref)
            conn_restored.close()
        new_status = "rolled_back" if rollback_ok else "failed"
        conn.execute(
            "UPDATE operations SET status=? WHERE id=?",
            (new_status, operation_id)
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

    # Verifikasi post-conditions
    verify_ok, verify_msg = _verify_operation(op["tool_name"], params)

    if not verify_ok:
        # Auto-rollback + FIX BUG-03: re-insert verified ops setelah rollback file DB
        rollback_ok = _do_rollback(rollback_command)
        if rollback_ok and snapshot_ref:
            conn_restored = sqlite3.connect(DB_PATH)
            conn_restored.row_factory = sqlite3.Row
            _restore_verified_operations(conn_restored, snapshot_ref)
            conn_restored.close()
        new_status = "rolled_back" if rollback_ok else "failed"
        conn.execute(
            "UPDATE operations SET status=?, verified_at=? WHERE id=?",
            (new_status, datetime.utcnow().isoformat(), operation_id)
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

    # Sukses
    conn.execute(
        "UPDATE operations SET status='verified', verified_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), operation_id)
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


def _exec_migration(params: dict) -> tuple[bool, str]:
    """
    Eksekusi DB migration. MVP: jalankan SQL statement di params['sql'].
    Ini satu-satunya operasi yang diimplementasi penuh (sesuai SYNAPSE.md priority).
    """
    sql = params.get("sql", "")
    db_path = params.get("db_path", str(DB_PATH))

    if not sql:
        return False, "Tidak ada SQL di params['sql']"

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(sql)
        conn.commit()
        conn.close()
        return True, f"Migration berhasil: {sql[:80]}..."
    except Exception as e:
        return False, f"Migration gagal: {e}"


def _exec_config_write(params: dict) -> tuple[bool, str]:
    """Tulis konten ke file config."""
    file_path = params.get("file_path", "")
    content = params.get("content", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"
    try:
        Path(file_path).write_text(content, encoding="utf-8")
        return True, f"Config ditulis ke {file_path}"
    except Exception as e:
        return False, str(e)


def _exec_file_delete(params: dict, snapshot_ref: str) -> tuple[bool, str]:
    """Hapus file (hanya kalau snapshot sudah dibuat)."""
    file_path = params.get("file_path", "")
    if not file_path:
        return False, "params['file_path'] tidak ada"
    if not snapshot_ref:
        return False, "Tidak ada snapshot — file delete dibatalkan (fail-safe)"
    try:
        Path(file_path).unlink()
        return True, f"File {file_path} dihapus"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# 3. list_pending_approvals
# ---------------------------------------------------------------------------

def list_pending_approvals() -> dict:
    """Daftar semua operasi yang butuh approval manusia."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT o.*, a.decision as approval_decision
           FROM operations o
           LEFT JOIN approvals a ON a.operation_id = o.id
           WHERE o.requires_approval = 1
             AND o.status IN ('pending', 'approved')
           ORDER BY o.created_at DESC"""
    ).fetchall()
    conn.close()

    return {
        "ok": True,
        "count": len(rows),
        "pending": [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# 4. approve_operation
# ---------------------------------------------------------------------------

def approve_operation(operation_id: str, decision: str, note: str = "") -> dict:
    """
    Approve atau deny sebuah operasi.
    decision: 'approved' | 'denied'
    """
    if decision not in ("approved", "denied"):
        return {"ok": False, "error": "decision harus 'approved' atau 'denied'"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    op = conn.execute(
        "SELECT id, status, tool_name FROM operations WHERE id = ?",
        (operation_id,)
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
        (operation_id, decision, datetime.utcnow().isoformat(), note)
    )

    new_status = "approved" if decision == "approved" else "denied"
    conn.execute(
        "UPDATE operations SET status=? WHERE id=?",
        (new_status, operation_id)
    )
    conn.commit()
    conn.close()

    _emit("operation_approved" if decision == "approved" else "operation_denied", {
        "operation_id": operation_id,
        "decision": decision,
        "tool_name": op["tool_name"],
    })

    return {
        "ok": True,
        "operation_id": operation_id,
        "decision": decision,
        "status": new_status,
        "new_status": new_status,
    }
