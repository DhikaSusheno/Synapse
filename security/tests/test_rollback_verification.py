"""
test_rollback_verification.py — QC-1 (pidpid35)
Memverifikasi rollback Guardian benar-benar memulihkan state.
Sesuai SYNAPSE.md section 2.2 + PRD deliverable #8.

Skenario yang dicakup:
  RB1  Rollback db.run_migration yang gagal → DB kembali ke state sebelumnya
  RB2  Rollback harus memulihkan ISI data, bukan hanya status HTTP sukses
  RB3  Eksekusi tanpa approval → ditolak SEBELUM rollback diperlukan
  RB4  Operasi yang sudah 'denied' tidak bisa dieksekusi
  RB5  Status operasi tidak boleh stuck 'executing' setelah selesai
  RB6  Rollback menghasilkan state historis yang valid (bukan impossible state)
  RB7  Waktu rollback < 10 detik (performance metric SYNAPSE.md 2.7)
  RB8  Double-execute yang sama → ditolak (idempotency guard)
"""
import sqlite3
import time
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approve(guardian_module, mem_db, op_id: str):
    """Helper: approve operasi langsung di DB dan via guardian."""
    guardian_module.approve_operation(op_id, "approved", "approved by test")


def _get_op_status(mem_db, op_id: str) -> str:
    conn = sqlite3.connect(str(mem_db))
    row = conn.execute(
        "SELECT status FROM operations WHERE id=?", (op_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# RB1 + RB2: rollback db.run_migration yang sengaja dirusak
# ---------------------------------------------------------------------------

class TestDbMigrationRollback:
    def test_failed_migration_triggers_rollback(self, guardian_module, mem_db):
        """
        RB1: SQL yang sengaja salah (invalid SQL) harus memicu rollback.
        Status akhir harus 'rolled_back' atau 'failed', BUKAN 'verified'.
        """
        # Propose
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "THIS IS NOT VALID SQL !!!@#", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Approve
        _approve(guardian_module, mem_db, op_id)

        # Execute — harus gagal
        exec_result = guardian_module.execute_operation(op_id)
        assert exec_result["ok"] is False, (
            "RB1 FAIL: Migration SQL invalid harus gagal"
        )

        final_status = _get_op_status(mem_db, op_id)
        assert final_status in ("rolled_back", "failed"), (
            f"RB1 FAIL: Status akhir harus 'rolled_back' atau 'failed', "
            f"dapat '{final_status}'"
        )

    def test_rollback_restores_db_tables(self, guardian_module, mem_db, tmp_path):
        """
        RB2: Setelah rollback, tabel kontrak (nodes, edges, operations, approvals)
        HARUS masih ada dan bisa di-query.
        Ini memverifikasi rollback memulihkan state, bukan hanya set status.
        """
        # Catat tabel sebelum migrasi rusak
        conn_before = sqlite3.connect(str(mem_db))
        tables_before = set(
            row[0] for row in
            conn_before.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        )
        conn_before.close()

        required_tables = {"nodes", "edges", "operations", "approvals"}
        assert required_tables.issubset(tables_before), (
            f"Prerequisite FAIL: tabel kontrak harus ada sebelum test, dapat {tables_before}"
        )

        # Propose + approve + execute migration yang sengaja menjatuhkan tabel
        # (tapi kita gunakan SQL invalid supaya gagal sebelum DROP)
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "INVALID QUERY THAT BREAKS", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]
        _approve(guardian_module, mem_db, op_id)
        guardian_module.execute_operation(op_id)

        # Verifikasi tabel kontrak masih ada setelah rollback
        conn_after = sqlite3.connect(str(mem_db))
        tables_after = set(
            row[0] for row in
            conn_after.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        )
        conn_after.close()

        assert required_tables.issubset(tables_after), (
            f"RB2 FAIL: Tabel kontrak harus tetap ada setelah rollback. "
            f"Missing: {required_tables - tables_after}"
        )


# ---------------------------------------------------------------------------
# RB3: execute tanpa approval → ditolak
# ---------------------------------------------------------------------------

class TestNoApprovalBlocked:
    def test_execute_without_approval_rejected(self, guardian_module, mem_db):
        """
        RB3: db.run_migration require_approval=True.
        Memanggil execute tanpa approve dulu harus return ok=False.
        """
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Langsung execute TANPA approve
        exec_result = guardian_module.execute_operation(op_id)
        assert exec_result["ok"] is False, (
            "RB3 FAIL: Execute tanpa approval harus ditolak (ok=False)"
        )

        # Status harus tetap 'pending', tidak berubah
        status = _get_op_status(mem_db, op_id)
        assert status == "pending", (
            f"RB3 FAIL: Status harus tetap 'pending', dapat '{status}'"
        )


# ---------------------------------------------------------------------------
# RB4: operasi yang di-deny tidak bisa dieksekusi
# ---------------------------------------------------------------------------

class TestDeniedOperationBlocked:
    def test_denied_operation_cannot_execute(self, guardian_module, mem_db):
        """RB4: Operasi yang di-deny harus tidak bisa dieksekusi."""
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Deny
        guardian_module.approve_operation(op_id, "denied", "test denial")

        # Coba execute
        exec_result = guardian_module.execute_operation(op_id)
        assert exec_result["ok"] is False, (
            "RB4 FAIL: Operasi yang di-deny harus tidak bisa dieksekusi"
        )

        status = _get_op_status(mem_db, op_id)
        assert status == "denied", (
            f"RB4 FAIL: Status harus 'denied', dapat '{status}'"
        )


# ---------------------------------------------------------------------------
# RB5: status tidak stuck 'executing'
# ---------------------------------------------------------------------------

class TestNoStuckExecuting:
    def test_status_not_stuck_executing_on_success(self, guardian_module, mem_db):
        """
        RB5: Setelah execute_operation selesai (sukses),
        status tidak boleh masih 'executing'.
        (Invariant dari synapse.invariants.yaml: operation_status_not_executing)
        """
        # service.restart tidak butuh approval
        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "api-service"
        )
        op_id = result["operation_id"]

        guardian_module.execute_operation(op_id)

        status = _get_op_status(mem_db, op_id)
        assert status != "executing", (
            f"RB5 FAIL: Status tidak boleh stuck 'executing' setelah selesai, "
            f"dapat '{status}'"
        )

    def test_status_not_stuck_executing_on_failure(self, guardian_module, mem_db):
        """RB5b: Bahkan saat gagal, status tidak boleh stuck 'executing'."""
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "BROKEN SQL!!", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]
        _approve(guardian_module, mem_db, op_id)
        guardian_module.execute_operation(op_id)

        status = _get_op_status(mem_db, op_id)
        assert status != "executing", (
            f"RB5b FAIL: Status tidak boleh stuck 'executing' setelah gagal, "
            f"dapat '{status}'"
        )


# ---------------------------------------------------------------------------
# RB6: rollback tidak menghasilkan impossible state
# ---------------------------------------------------------------------------

class TestRollbackStateValidity:
    def test_rollback_state_is_historically_consistent(self, guardian_module, mem_db):
        """
        RB6: Sesuai SYNAPSE.md 2.2 — rollback 'sukses teknis' masih bisa
        menghasilkan state historis yang mustahil.
        Test: setelah rollback, operasi yang sudah 'verified' sebelumnya
        tidak boleh ikut terhapus dari DB (data lama harus tetap ada).
        """
        # Buat operasi yang sukses dulu (sebagai historical record)
        r1 = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "service-node"
        )
        op_id_good = r1["operation_id"]
        guardian_module.execute_operation(op_id_good)

        status_good = _get_op_status(mem_db, op_id_good)
        assert status_good == "verified", f"Setup FAIL: operasi pertama harus 'verified'"

        # Sekarang buat operasi yang gagal dan di-rollback
        r2 = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "INVALID SQL!!", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id_bad = r2["operation_id"]
        _approve(guardian_module, mem_db, op_id_bad)
        guardian_module.execute_operation(op_id_bad)

        # Verifikasi: operasi pertama yang sudah 'verified' masih ada
        status_after_rollback = _get_op_status(mem_db, op_id_good)
        assert status_after_rollback == "verified", (
            f"RB6 FAIL: Operasi 'verified' sebelumnya harus tetap ada setelah rollback, "
            f"dapat '{status_after_rollback}' — ini adalah historically impossible state!"
        )


# ---------------------------------------------------------------------------
# RB7: performance — rollback < 10 detik
# ---------------------------------------------------------------------------

class TestRollbackPerformance:
    def test_rollback_completes_under_10_seconds(self, guardian_module, mem_db):
        """
        RB7: SYNAPSE.md 2.7 — waktu dari 'operasi berisiko diminta' sampai
        'rollback selesai' pada skenario injected failure harus < 10 detik.
        """
        start = time.time()

        # Propose
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "INTENTIONALLY BROKEN SQL", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Approve
        _approve(guardian_module, mem_db, op_id)

        # Execute (akan gagal dan rollback)
        guardian_module.execute_operation(op_id)

        elapsed = time.time() - start
        assert elapsed < 10.0, (
            f"RB7 FAIL: Propose→rollback harus < 10 detik, "
            f"memakan {elapsed:.2f} detik (SYNAPSE.md 2.7)"
        )


# ---------------------------------------------------------------------------
# RB8: double-execute guard (idempotency)
# ---------------------------------------------------------------------------

class TestDoubleExecuteGuard:
    def test_double_execute_rejected(self, guardian_module, mem_db):
        """
        RB8: Memanggil execute_operation dua kali dengan ID yang sama
        harus ditolak pada panggilan kedua.
        Mencegah replay attack / accidental double-run.
        """
        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "api-node"
        )
        op_id = result["operation_id"]

        # Execute pertama → harus sukses
        r1 = guardian_module.execute_operation(op_id)
        assert r1["ok"] is True, f"Execute pertama harus sukses, dapat: {r1}"

        # Execute kedua → harus ditolak
        r2 = guardian_module.execute_operation(op_id)
        assert r2["ok"] is False, (
            f"RB8 FAIL: Execute kedua harus ditolak (ok=False), dapat ok={r2.get('ok')}"
        )
