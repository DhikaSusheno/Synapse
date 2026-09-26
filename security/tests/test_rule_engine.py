"""
test_rule_engine.py — QC-1 (pidpid35)
Memverifikasi rule table Guardian sesuai SYNAPSE.md section 4.4.

Skenario yang dicakup:
  R1  db.run_migration   → blast_radius=high, require_approval=True
  R2  service.restart    → blast_radius=medium, require_approval=False
  R3  config.write       → blast_radius=medium, require_approval=False
  R4  file.delete        → blast_radius=high, require_approval=True
  R5  UNKNOWN tool       → blast_radius=unknown, require_approval=True  (fail-closed)
  R6  Partial match prefix (db.run_migration.v2) → tetap match rule db.run_migration
  R7  Empty string tool  → fail-closed
  R8  None-like / whitespace tool → fail-closed
  R9  Case-sensitive: DB.RUN_MIGRATION → fail-closed (bukan match)
  R10 Operasi tak dikenal TIDAK boleh auto-execute tanpa approval
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule_for(guardian_module, tool_name: str) -> dict:
    """Akses private helper _get_rule dari modul guardian."""
    return guardian_module._get_rule(tool_name)


# ---------------------------------------------------------------------------
# R1: db.run_migration
# ---------------------------------------------------------------------------

class TestDbRunMigration:
    def test_blast_radius_high(self, guardian_module):
        rule = _rule_for(guardian_module, "db.run_migration")
        assert rule["blast_radius"] == "high", (
            f"db.run_migration harus blast_radius='high', dapat '{rule['blast_radius']}'"
        )

    def test_require_approval_true(self, guardian_module):
        rule = _rule_for(guardian_module, "db.run_migration")
        assert rule["require_approval"] is True, (
            "db.run_migration harus require_approval=True (SYNAPSE.md 4.4)"
        )

    def test_propose_sets_requires_approval(self, guardian_module, mem_db):
        """propose_operation harus menyimpan requires_approval=1 di DB."""
        import sqlite3
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(mem_db)},
            "synapse.db"
        )
        assert result["requires_approval"] is True
        assert result["blast_radius"] == "high"

        conn = sqlite3.connect(str(mem_db))
        row = conn.execute(
            "SELECT requires_approval FROM operations WHERE id=?",
            (result["operation_id"],)
        ).fetchone()
        conn.close()
        assert row[0] == 1, "requires_approval harus tersimpan sebagai 1 di DB"


# ---------------------------------------------------------------------------
# R2: service.restart
# ---------------------------------------------------------------------------

class TestServiceRestart:
    def test_blast_radius_medium(self, guardian_module):
        rule = _rule_for(guardian_module, "service.restart")
        assert rule["blast_radius"] == "medium"

    def test_require_approval_false(self, guardian_module):
        rule = _rule_for(guardian_module, "service.restart")
        assert rule["require_approval"] is False, (
            "service.restart seharusnya TIDAK butuh approval (auto-approve)"
        )

    def test_propose_no_approval_required(self, guardian_module):
        result = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "api-service"
        )
        assert result["requires_approval"] is False
        assert result["blast_radius"] == "medium"


# ---------------------------------------------------------------------------
# R3: config.write
# ---------------------------------------------------------------------------

class TestConfigWrite:
    def test_blast_radius_medium(self, guardian_module):
        rule = _rule_for(guardian_module, "config.write")
        assert rule["blast_radius"] == "medium"

    def test_require_approval_false(self, guardian_module):
        rule = _rule_for(guardian_module, "config.write")
        assert rule["require_approval"] is False


# ---------------------------------------------------------------------------
# R4: file.delete
# ---------------------------------------------------------------------------

class TestFileDelete:
    def test_blast_radius_high(self, guardian_module):
        rule = _rule_for(guardian_module, "file.delete")
        assert rule["blast_radius"] == "high"

    def test_require_approval_true(self, guardian_module):
        rule = _rule_for(guardian_module, "file.delete")
        assert rule["require_approval"] is True


# ---------------------------------------------------------------------------
# R5–R9: fail-closed (unknown / empty / wrong-case)
# ---------------------------------------------------------------------------

class TestFailClosed:
    @pytest.mark.parametrize("tool_name", [
        "unknown_tool",
        "totally.random.operation",
        "hack.db",
        "admin.override",
        "   ",
        "",
        "DB.RUN_MIGRATION",          # R9: case-sensitive → tidak match
        "Service.Restart",           # case-sensitive
        "config.write.as.root",      # partial prefix yang lebih panjang dari rule
    ])
    def test_unknown_tool_fail_closed(self, guardian_module, tool_name):
        """
        SYNAPSE.md 4.4: setiap tool yang tidak match rule manapun
        HARUS require_approval=True dan blast_radius='unknown'.
        Zero exceptions.
        """
        rule = _rule_for(guardian_module, tool_name)
        assert rule["require_approval"] is True, (
            f"Tool '{tool_name}' tidak dikenal → harus fail-closed (require_approval=True), "
            f"dapat require_approval={rule['require_approval']}"
        )
        assert rule["blast_radius"] == "unknown", (
            f"Tool '{tool_name}' tidak dikenal → blast_radius harus 'unknown', "
            f"dapat '{rule['blast_radius']}'"
        )

    def test_unknown_tool_propose_fail_closed(self, guardian_module):
        """propose_operation untuk tool tak dikenal harus return requires_approval=True."""
        result = guardian_module.propose_operation(
            "totally_unknown_tool_xyz",
            {},
            "some_target"
        )
        assert result["requires_approval"] is True, (
            "propose_operation untuk unknown tool harus fail-closed"
        )
        assert result["blast_radius"] == "unknown"

    def test_unknown_tool_cannot_execute_without_approval(self, guardian_module):
        """
        R10: Operasi unknown yang dipropose langsung dicoba execute
        tanpa approval → harus ditolak dengan error.
        """
        propose_result = guardian_module.propose_operation(
            "totally_unknown_tool_xyz",
            {},
            "some_target"
        )
        op_id = propose_result["operation_id"]

        # Coba execute tanpa approval
        exec_result = guardian_module.execute_operation(op_id)
        assert exec_result["ok"] is False, (
            "execute_operation tanpa approval harus mengembalikan ok=False"
        )
        assert "approval" in exec_result.get("error", "").lower(), (
            f"Pesan error harus menyebut approval, dapat: '{exec_result.get('error')}'"
        )


# ---------------------------------------------------------------------------
# R6: prefix match
# ---------------------------------------------------------------------------

class TestPrefixMatch:
    def test_db_migration_variant_matches_rule(self, guardian_module):
        """db.run_migration.v2 harus match rule db.run_migration via startswith."""
        rule = _rule_for(guardian_module, "db.run_migration.v2")
        assert rule["require_approval"] is True
        assert rule["blast_radius"] == "high"

    def test_service_restart_variant_matches_rule(self, guardian_module):
        """service.restart.graceful harus match rule service.restart."""
        rule = _rule_for(guardian_module, "service.restart.graceful")
        assert rule["require_approval"] is False
        assert rule["blast_radius"] == "medium"

    def test_service_restart_NOT_matches_db_rule(self, guardian_module):
        """service.restart tidak boleh match rule db.run_migration."""
        rule = _rule_for(guardian_module, "service.restart")
        assert rule["blast_radius"] != "high"
