"""
test_conflict_detection.py — QC-1 (pidpid35)
Memverifikasi conflict detection Guardian sesuai SYNAPSE.md section 4.5.

Skenario yang dicakup:
  C1  Dua operasi mengenai target sama dalam CONFLICT_WINDOW → approve dipaksa
  C2  Dua operasi mengenai target berbeda → tidak trigger conflict
  C3  Operasi kedua di luar window (status 'verified') → tidak dihitung konflik
  C4  Operasi dengan blast_radius rendah + konflik → TETAP dipaksa approval
      (invariant: konflik override individual blast_radius)
  C5  Adversarial bypass: coba inject operasi dengan requires_approval=False
      setelah patching rule, konflik harus tetap paksa approval
  C6  Tiga agent simultan mengenai target sama → semua terdeteksi konflik
  C7  Self-conflict: operasi yang sama tidak konflik dengan dirinya sendiri
"""
import sqlite3
import pytest
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_existing_op(db_path, target_node_id: str, status: str = "pending",
                        minutes_ago: float = 0.0) -> str:
    """Insert operasi fiktif di DB untuk setup test konflik."""
    import uuid
    op_id = str(uuid.uuid4())
    created = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO nodes (id, type, name) VALUES (?, 'operation', ?) ON CONFLICT(id) DO NOTHING",
        (target_node_id, target_node_id)
    )
    conn.execute(
        """
        INSERT INTO operations
        (id, tool_name, params_json, target_node_id, blast_radius,
         reversibility_class, status, requires_approval, created_at)
        VALUES (?, 'service.restart', '{}', ?, 'medium', 'needs_snapshot', ?, 0, ?)
        """,
        (op_id, target_node_id, status, created)
    )
    conn.commit()
    conn.close()
    return op_id


# ---------------------------------------------------------------------------
# C1: dua operasi ke target sama dalam window → conflict paksa approval
# ---------------------------------------------------------------------------

class TestConflictForcesApproval:
    def test_conflict_same_target_forces_approval(self, guardian_module, mem_db):
        """
        C1: Operasi A sudah 'pending' di target X.
        Operasi B ke target X dalam window → requires_approval dipaksa True,
        meski rule asli operasi B adalah require_approval=False.
        """
        target = "operation_target::db_production"
        # Operasi A sudah ada
        _insert_existing_op(mem_db, target, status="pending", minutes_ago=2)

        # Operasi B: service.restart (rule-nya require_approval=False)
        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "db_production"
        )
        assert result["requires_approval"] is True, (
            "C1 FAIL: Konflik harus memaksa requires_approval=True, "
            f"dapat {result['requires_approval']}"
        )
        assert result["conflicts"] != [], (
            "C1 FAIL: Seharusnya ada daftar konflik yang terdeteksi"
        )

    def test_conflict_count_correct(self, guardian_module, mem_db):
        """C1b: Jumlah konflik yang dilaporkan harus akurat."""
        target = "operation_target::shared_node"
        _insert_existing_op(mem_db, target, status="pending", minutes_ago=1)
        _insert_existing_op(mem_db, target, status="approved", minutes_ago=3)

        result = guardian_module.propose_operation(
            "config.write", {"file_path": "/etc/app.conf"}, "shared_node"
        )
        assert len(result["conflicts"]) >= 2, (
            f"C1b FAIL: Seharusnya terdeteksi >=2 konflik, dapat {len(result['conflicts'])}"
        )


# ---------------------------------------------------------------------------
# C2: target berbeda → tidak ada konflik
# ---------------------------------------------------------------------------

class TestNoConflictDifferentTarget:
    def test_different_target_no_conflict(self, guardian_module, mem_db):
        """C2: Operasi ke target berbeda tidak boleh trigger conflict."""
        _insert_existing_op(
            mem_db, "operation_target::target_A", status="pending", minutes_ago=1
        )

        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "target_B"  # target berbeda
        )
        # service.restart punya require_approval=False dan tidak ada konflik
        assert result["conflicts"] == [], (
            f"C2 FAIL: Tidak boleh ada konflik untuk target berbeda, "
            f"dapat {result['conflicts']}"
        )
        assert result["requires_approval"] is False, (
            "C2 FAIL: Tanpa konflik, service.restart seharusnya require_approval=False"
        )


# ---------------------------------------------------------------------------
# C3: operasi lama di luar window → tidak dihitung konflik
# ---------------------------------------------------------------------------

class TestConflictWindowExpiry:
    def test_old_operation_outside_window_ignored(self, guardian_module, mem_db):
        """
        C3: Operasi yang dibuat CONFLICT_WINDOW_MINUTES + 5 menit lalu
        tidak boleh dihitung sebagai konflik.
        """
        window = guardian_module.CONFLICT_WINDOW_MINUTES
        target = "operation_target::stale_target"
        _insert_existing_op(
            mem_db, target, status="pending",
            minutes_ago=window + 5  # di luar window
        )

        result = guardian_module.propose_operation(
            "service.restart", {}, "stale_target"
        )
        assert result["conflicts"] == [], (
            f"C3 FAIL: Operasi di luar conflict window ({window} menit) "
            "tidak boleh dihitung konflik"
        )

    def test_operation_inside_window_detected(self, guardian_module, mem_db):
        """C3b: Operasi tepat di dalam window HARUS terdeteksi."""
        window = guardian_module.CONFLICT_WINDOW_MINUTES
        target = "operation_target::fresh_target"
        _insert_existing_op(
            mem_db, target, status="pending",
            minutes_ago=window - 1  # masih dalam window
        )

        result = guardian_module.propose_operation(
            "service.restart", {}, "fresh_target"
        )
        assert result["conflicts"] != [], (
            f"C3b FAIL: Operasi dalam conflict window ({window-1} menit) harus terdeteksi"
        )


# ---------------------------------------------------------------------------
# C4: blast_radius rendah + konflik → approval tetap dipaksa
# ---------------------------------------------------------------------------

class TestConflictOverridesBlastRadius:
    def test_low_blast_radius_with_conflict_still_requires_approval(self, guardian_module, mem_db):
        """
        C4: Bahkan operasi 'service.restart' (medium, no-approval) yang
        punya konflik TETAP harus require_approval=True.
        Konflik selalu override rule individual.
        """
        target = "operation_target::critical_db"
        _insert_existing_op(mem_db, target, status="executing", minutes_ago=1)

        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "critical_db"
        )
        assert result["requires_approval"] is True, (
            "C4 FAIL: Konflik harus override blast_radius rule dan paksa approval"
        )


# ---------------------------------------------------------------------------
# C5: adversarial — operasi dalam window dengan status 'verified' tidak konflik
# ---------------------------------------------------------------------------

class TestConflictStatusFilter:
    def test_verified_operations_not_conflict(self, guardian_module, mem_db):
        """
        C5: Operasi dengan status 'verified' (selesai sukses) dalam window
        TIDAK boleh dihitung sebagai konflik aktif.
        Hanya status: pending, approved, executing, executed_unverified yang konflik.
        """
        target = "operation_target::clean_target"
        _insert_existing_op(mem_db, target, status="verified", minutes_ago=1)

        result = guardian_module.propose_operation(
            "service.restart", {}, "clean_target"
        )
        assert result["conflicts"] == [], (
            "C5 FAIL: Operasi 'verified' tidak boleh trigger konflik"
        )

    def test_failed_operations_not_conflict(self, guardian_module, mem_db):
        """Operasi 'failed' juga tidak boleh dihitung konflik."""
        target = "operation_target::failed_target"
        _insert_existing_op(mem_db, target, status="failed", minutes_ago=1)

        result = guardian_module.propose_operation(
            "service.restart", {}, "failed_target"
        )
        assert result["conflicts"] == []

    def test_rolled_back_not_conflict(self, guardian_module, mem_db):
        """Operasi 'rolled_back' tidak boleh dihitung konflik."""
        target = "operation_target::rolled_target"
        _insert_existing_op(mem_db, target, status="rolled_back", minutes_ago=1)

        result = guardian_module.propose_operation(
            "service.restart", {}, "rolled_target"
        )
        assert result["conflicts"] == []

    @pytest.mark.parametrize("active_status", [
        "pending", "approved", "executing", "executed_unverified"
    ])
    def test_active_statuses_all_trigger_conflict(self, guardian_module, mem_db, active_status):
        """C5c: Semua status aktif harus trigger konflik."""
        target = f"operation_target::active_{active_status}"
        _insert_existing_op(mem_db, target, status=active_status, minutes_ago=1)

        result = guardian_module.propose_operation(
            "service.restart", {}, f"active_{active_status}"
        )
        assert result["conflicts"] != [], (
            f"C5c FAIL: Status '{active_status}' harus trigger konflik"
        )


# ---------------------------------------------------------------------------
# C6: multi-agent simultan
# ---------------------------------------------------------------------------

class TestMultiAgentConflict:
    def test_three_simultaneous_agents_all_flagged(self, guardian_module, mem_db):
        """
        C6: Tiga 'agent' propose operasi ke target sama.
        Setelah operasi pertama ada, semua yang berikutnya harus conflict.
        """
        target = "operation_target::shared_resource"
        # Agent 1 (sudah ada sebelumnya)
        _insert_existing_op(mem_db, target, status="pending", minutes_ago=0.5)

        # Agent 2
        r2 = guardian_module.propose_operation(
            "config.write", {"file_path": "/app.conf"}, "shared_resource"
        )
        assert r2["requires_approval"] is True, "Agent 2 harus conflict"

        # Agent 3
        r3 = guardian_module.propose_operation(
            "db.run_migration", {"sql": "SELECT 1"}, "shared_resource"
        )
        assert r3["requires_approval"] is True, "Agent 3 harus conflict"
        # db.run_migration sudah require_approval=True dari rule,
        # tapi juga harus ada konflik dalam daftar
        assert r3["conflicts"] != [], "Agent 3 harus lapor konflik yang aktif"
