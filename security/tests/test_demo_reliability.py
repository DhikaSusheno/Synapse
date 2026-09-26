"""
test_demo_reliability.py — QC-2 (zuyss)
Test reliabilitas skenario demo: break→rollback harus reproducible.
Sesuai PRD deliverable #7 + SYNAPSE.md section 3.1 fase 7.

"Rekam skenario rusak→rollback berkali-kali sampai reliable."
"Ini bukan opsional — ini asuransi kalau live demo ngadat di depan juri."

Skenario yang dicakup (DR):
  DR1  Break→rollback dijalankan 3x berturut-turut — harus konsisten setiap run
  DR2  Rollback timing < 10 detik (SYNAPSE.md 2.7) — diuji 3x
  DR3  Setelah rollback, DB tetap bisa menerima operasi baru (recovery proof)
  DR4  Conflict detection + rollback bersamaan tidak menyebabkan DB corrupt
  DR5  Impossible state: history pre-rollback tidak ikut terhapus
  DR6  Graph ingest baseline timing: buat DB dengan seed, ukur waktu
  DR7  Demo sequence tidak ada operasi stuck 'executing' setelah suite selesai

TEST-BUG-2 FIX: import seed menggunakan sys.path-based agar bekerja
tanpa perlu __init__.py di semua level atau pytest dijalankan dari root.
"""
import sqlite3
import sys
import time
import pytest
from pathlib import Path

# TEST-BUG-2 FIX: tambah direktori tests ke sys.path agar
# 'from demo_data.seed import ...' bisa resolve tanpa absolute package path
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from demo_data.seed import create_demo_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path):
    """Fresh seeded demo DB untuk setiap test."""
    return create_demo_db(tmp_path / "reliability_test.db")


@pytest.fixture()
def rel_guardian(fresh_db, monkeypatch):
    """
    Guardian menunjuk ke fresh_db.
    TEST-BUG-3 FIX: pakai monkeypatch agar patch DB_PATH thread-safe.
    """
    import importlib
    from pathlib import Path as _Path
    from unittest.mock import MagicMock

    backend_dir = _Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    import database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)

    import guardian as g
    importlib.reload(g)
    g._emit = MagicMock()

    yield g


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_break_rollback(guardian, db_path, iteration: int = 0) -> dict:
    """
    Jalankan satu siklus lengkap break→rollback.
    Return dict dengan semua metric untuk assertion.
    """
    target = f"reliability-db-{iteration}"
    start = time.monotonic()

    r = guardian.propose_operation(
        "db.run_migration",
        {"sql": f"INTENTIONALLY BROKEN SQL ITERATION {iteration} @@@#$;",
         "db_path": str(db_path)},
        target
    )
    assert r["ok"] is True, f"Iter {iteration}: propose gagal: {r}"
    op_id = r["operation_id"]

    ar = guardian.approve_operation(op_id, "approved", f"reliability test iter {iteration}")
    assert ar["ok"] is True, f"Iter {iteration}: approve gagal: {ar}"

    er = guardian.execute_operation(op_id)
    elapsed = time.monotonic() - start

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT status FROM operations WHERE id=?", (op_id,)).fetchone()
    final_status = row[0] if row else "NOT_FOUND"
    conn.close()

    return {
        "iteration": iteration,
        "op_id": op_id,
        "exec_ok": er.get("ok"),
        "exec_status": er.get("status"),
        "final_status_db": final_status,
        "elapsed_sec": elapsed,
        "exec_result": er,
    }


# ---------------------------------------------------------------------------
# DR1: Break→rollback 3x berturut-turut — harus konsisten
# ---------------------------------------------------------------------------

class TestBreakRollbackReliability:
    def test_break_rollback_consistent_3_iterations(self, rel_guardian, fresh_db):
        results = []
        for i in range(3):
            result = _run_break_rollback(rel_guardian, fresh_db, iteration=i)
            results.append(result)

        for r in results:
            assert r["exec_ok"] is False, (
                f"DR1 FAIL iter {r['iteration']}: execute harus gagal (ok=False), "
                f"dapat {r['exec_ok']}"
            )
            assert r["final_status_db"] in ("rolled_back", "failed"), (
                f"DR1 FAIL iter {r['iteration']}: status harus rolled_back/failed, "
                f"dapat '{r['final_status_db']}'"
            )
            assert r["final_status_db"] != "executing", (
                f"DR1 FAIL iter {r['iteration']}: status tidak boleh stuck 'executing'"
            )

        conn = sqlite3.connect(str(fresh_db))
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert {"nodes", "edges", "operations", "approvals"}.issubset(tables), (
            f"DR1 FAIL: Tabel kontrak hilang setelah 3x break→rollback. Tables: {tables}"
        )


# ---------------------------------------------------------------------------
# DR2: Rollback timing < 10 detik (3x)
# ---------------------------------------------------------------------------

class TestRollbackTimingReliability:
    @pytest.mark.parametrize("iteration", [0, 1, 2])
    def test_rollback_under_10_seconds(self, rel_guardian, fresh_db, iteration):
        result = _run_break_rollback(rel_guardian, fresh_db, iteration=iteration)
        assert result["elapsed_sec"] < 10.0, (
            f"DR2 FAIL iter {iteration}: Propose→rollback harus < 10 detik, "
            f"memakan {result['elapsed_sec']:.3f}s (SYNAPSE.md 2.7)"
        )


# ---------------------------------------------------------------------------
# DR3: Setelah rollback, DB masih menerima operasi baru
# ---------------------------------------------------------------------------

class TestRecoveryAfterRollback:
    def test_db_accepts_new_operation_after_rollback(self, rel_guardian, fresh_db):
        _run_break_rollback(rel_guardian, fresh_db, iteration=0)

        r = rel_guardian.propose_operation(
            "service.restart",
            {"service": "recovery-test-svc"},
            "recovery-target"
        )
        assert r["ok"] is True, (
            f"DR3 FAIL: propose_operation gagal setelah rollback: {r}"
        )
        op_id = r["operation_id"]

        er = rel_guardian.execute_operation(op_id)
        assert er["ok"] is True, (
            f"DR3 FAIL: Operasi baru setelah rollback harus sukses, dapat: {er}"
        )
        assert er["status"] == "verified"


# ---------------------------------------------------------------------------
# DR4: Conflict + rollback tidak corrupt DB
# ---------------------------------------------------------------------------

class TestConflictAndRollbackNoCorrupt:
    def test_conflict_then_rollback_no_corruption(self, rel_guardian, fresh_db):
        shared_target = "conflict-rollback-target"

        rA = rel_guardian.propose_operation(
            "service.restart", {"service": "svc-a"}, shared_target
        )
        assert rA["ok"] is True
        op_id_A = rA["operation_id"]

        rB = rel_guardian.propose_operation(
            "db.run_migration",
            {"sql": "BROKEN SQL FOR CONFLICT TEST @@@;", "db_path": str(fresh_db)},
            shared_target
        )
        assert rB["ok"] is True
        assert rB["requires_approval"] is True
        op_id_B = rB["operation_id"]

        rel_guardian.approve_operation(op_id_B, "approved", "dr4: conflict+rollback")
        eB = rel_guardian.execute_operation(op_id_B)
        assert eB["ok"] is False, "DR4 FAIL: Migration rusak harus gagal"

        conn = sqlite3.connect(str(fresh_db))
        row = conn.execute(
            "SELECT status FROM operations WHERE id=?", (op_id_A,)
        ).fetchone()
        conn.close()
        assert row is not None, (
            "DR4 FAIL: Op A harus masih ada di DB setelah rollback Op B"
        )

        conn = sqlite3.connect(str(fresh_db))
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert {"nodes", "edges", "operations", "approvals"}.issubset(tables)


# ---------------------------------------------------------------------------
# DR5: Impossible state — history sebelum rollback tidak ikut terhapus
# ---------------------------------------------------------------------------

class TestImpossibleStateProtection:
    def test_pre_rollback_history_preserved(self, rel_guardian, fresh_db):
        r_good = rel_guardian.propose_operation(
            "service.restart", {"service": "pre-snapshot-svc"}, "pre-snapshot-target"
        )
        op_good = r_good["operation_id"]
        e_good = rel_guardian.execute_operation(op_good)
        assert e_good["ok"] is True, "Setup DR5: operasi pertama harus verified"
        assert e_good["status"] == "verified"

        r_bad = rel_guardian.propose_operation(
            "db.run_migration",
            {"sql": "BREAK THIS FOR DR5 @@@;", "db_path": str(fresh_db)},
            "dr5-broken-target"
        )
        op_bad = r_bad["operation_id"]
        rel_guardian.approve_operation(op_bad, "approved", "dr5 force rollback")
        e_bad = rel_guardian.execute_operation(op_bad)
        assert e_bad["ok"] is False

        conn = sqlite3.connect(str(fresh_db))
        row = conn.execute(
            "SELECT status FROM operations WHERE id=?", (op_good,)
        ).fetchone()
        conn.close()

        if row is None or row[0] != "verified":
            pytest.fail(
                "DR5 CONFIRMS BUG-03: Setelah rollback, operasi 'verified' sebelumnya "
                f"hilang dari DB atau status berubah. "
                f"Status: {row[0] if row else 'MISSING'}. "
                "Lihat Issue #6 — historically impossible state."
            )


# ---------------------------------------------------------------------------
# DR6: Graph ingest baseline timing
# ---------------------------------------------------------------------------

class TestGraphIngestTiming:
    def test_seed_db_creation_under_30_seconds(self, tmp_path):
        start = time.monotonic()
        db_path = create_demo_db(tmp_path / "timing_test.db")
        elapsed = time.monotonic() - start

        assert db_path.exists(), "DR6 FAIL: Demo DB tidak terbuat"
        assert elapsed < 5.0, (
            f"DR6 FAIL: Seed DB harus selesai < 5 detik, memakan {elapsed:.3f}s."
        )

    def test_seed_db_nodes_queryable_immediately(self, tmp_path):
        db_path = create_demo_db(tmp_path / "queryable_test.db")

        conn = sqlite3.connect(str(db_path))
        results = conn.execute(
            """
            SELECT n.name, n.type
            FROM nodes n
            JOIN edges e ON e.source_id = n.id
            WHERE e.relationship = 'IMPLEMENTED_BY'
              AND e.target_id = 'file::app/models.py'
            """
        ).fetchall()
        conn.close()

        assert len(results) >= 2, (
            f"DR6b FAIL: Query traversal graph harus return >=2 hasil, dapat {len(results)}: {results}"
        )


# ---------------------------------------------------------------------------
# DR7: Tidak ada operasi stuck 'executing' di akhir suite
# ---------------------------------------------------------------------------

class TestNoStuckExecutingGlobal:
    def test_no_executing_status_after_all_operations(self, rel_guardian, fresh_db):
        ops_to_run = [
            ("service.restart", {"service": "svc1"}, "target-dr7-1", False, True),
            ("db.run_migration",
             {"sql": "BROKEN @@@", "db_path": str(fresh_db)},
             "target-dr7-2", True, False),
            ("service.restart", {"service": "svc2"}, "target-dr7-3", False, True),
        ]

        for tool, params, target, need_approve, _ in ops_to_run:
            r = rel_guardian.propose_operation(tool, params, target)
            if need_approve or r["requires_approval"]:
                rel_guardian.approve_operation(
                    r["operation_id"], "approved", "dr7 batch"
                )
            rel_guardian.execute_operation(r["operation_id"])

        conn = sqlite3.connect(str(fresh_db))
        stuck = conn.execute(
            "SELECT id, tool_name FROM operations WHERE status='executing'"
        ).fetchall()
        conn.close()

        assert len(stuck) == 0, (
            f"DR7 FAIL: Ada {len(stuck)} operasi stuck 'executing': "
            f"{[(s[1], s[0][:8]) for s in stuck]}"
        )
