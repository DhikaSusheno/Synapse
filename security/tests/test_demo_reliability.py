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
"""
import sqlite3
import time
import pytest
from pathlib import Path
from security.tests.demo_data.seed import create_demo_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path):
    """Fresh seeded demo DB untuk setiap test."""
    return create_demo_db(tmp_path / "reliability_test.db")


@pytest.fixture()
def rel_guardian(fresh_db):
    """Guardian menunjuk ke fresh_db."""
    import sys
    from pathlib import Path as _Path
    from unittest.mock import MagicMock
    import importlib

    backend_dir = _Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    import database as db_mod
    original = db_mod.DB_PATH
    db_mod.DB_PATH = fresh_db

    import guardian as g
    g._emit = MagicMock()
    importlib.reload(g)
    g._emit = MagicMock()

    yield g

    db_mod.DB_PATH = original


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

    # 1. Propose migration yang sengaja rusak
    r = guardian.propose_operation(
        "db.run_migration",
        {"sql": f"INTENTIONALLY BROKEN SQL ITERATION {iteration} @@@#$;",
         "db_path": str(db_path)},
        target
    )
    assert r["ok"] is True, f"Iter {iteration}: propose gagal: {r}"
    op_id = r["operation_id"]

    # 2. Approve (paksa jalan)
    ar = guardian.approve_operation(op_id, "approved", f"reliability test iter {iteration}")
    assert ar["ok"] is True, f"Iter {iteration}: approve gagal: {ar}"

    # 3. Execute — harus gagal dan rollback
    er = guardian.execute_operation(op_id)

    elapsed = time.monotonic() - start

    # 4. Cek status akhir
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
        """
        DR1: Jalankan break→rollback 3x. Setiap iterasi harus:
          - ok=False (eksekusi gagal)
          - status akhir = 'rolled_back' atau 'failed' (bukan 'verified'/'executing')
          - DB masih valid setelahnya

        Ini adalah versi automasi dari "rekam skenario rusak→rollback berkali-kali"
        (SYNAPSE.md 3.1 fase 7). Jika salah satu iterasi flaky → bug untuk diperbaiki.
        """
        results = []
        for i in range(3):
            result = _run_break_rollback(rel_guardian, fresh_db, iteration=i)
            results.append(result)

        # Semua iterasi harus konsisten
        for r in results:
            assert r["exec_ok"] is False, (
                f"DR1 FAIL iter {r['iteration']}: execute harus gagal (ok=False), "
                f"dapat {r['exec_ok']}"
            )
            assert r["final_status_db"] in ("rolled_back", "failed"), (
                f"DR1 FAIL iter {r['iteration']}: status harus rolled_back/failed, "
                f"dapat '{r['final_status_db']}'"
            )
            # Tidak boleh stuck executing
            assert r["final_status_db"] != "executing", (
                f"DR1 FAIL iter {r['iteration']}: status tidak boleh stuck 'executing'"
            )

        # DB harus masih valid setelah 3 iterasi
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
        """
        DR2: SYNAPSE.md 2.7 — propose→rollback selesai < 10 detik.
        Diuji 3x secara terpisah (pytest parametrize) agar masing-masing
        mendapat DB yang fresh dan tidak saling mempengaruhi timing.
        """
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
        """
        DR3: Setelah rollback, sistem harus bisa menerima dan mengeksekusi
        operasi baru yang valid. Membuktikan sistem recover, bukan hanya bertahan.
        """
        # Jalankan break→rollback sekali
        _run_break_rollback(rel_guardian, fresh_db, iteration=0)

        # Coba operasi baru yang seharusnya sukses
        r = rel_guardian.propose_operation(
            "service.restart",
            {"service": "recovery-test-svc"},
            "recovery-target"
        )
        assert r["ok"] is True, (
            f"DR3 FAIL: propose_operation gagal setelah rollback: {r}"
        )
        op_id = r["operation_id"]

        # service.restart no-approval, langsung execute
        er = rel_guardian.execute_operation(op_id)
        assert er["ok"] is True, (
            f"DR3 FAIL: Operasi baru setelah rollback harus sukses, dapat: {er}"
        )
        assert er["status"] == "verified"


# ---------------------------------------------------------------------------
# DR4: Conflict + rollback tidak corrupt DB
# ---------------------------------------------------------------------------

class TestConflictAndRollbackNoCorrupt:
    def test_conflict_then_rollback_no_corruption(
        self, rel_guardian, fresh_db
    ):
        """
        DR4: Scenario simultan:
          - Op A (pending) ke target X
          - Op B ke target X → dipaksa approval karena konflik
          - Op B diapprove dan dieksekusi tapi migration rusak → rollback
          - DB harus tetap konsisten, Op A masih ada
        """
        shared_target = "conflict-rollback-target"

        # Op A — biarkan pending
        rA = rel_guardian.propose_operation(
            "service.restart",
            {"service": "svc-a"},
            shared_target
        )
        assert rA["ok"] is True
        op_id_A = rA["operation_id"]

        # Op B — ke target sama, dengan migration rusak
        rB = rel_guardian.propose_operation(
            "db.run_migration",
            {"sql": "BROKEN SQL FOR CONFLICT TEST @@@;",
             "db_path": str(fresh_db)},
            shared_target
        )
        assert rB["ok"] is True
        assert rB["requires_approval"] is True  # dipaksa karena konflik
        op_id_B = rB["operation_id"]

        # Approve B
        rel_guardian.approve_operation(op_id_B, "approved", "dr4: conflict+rollback")

        # Execute B — harus gagal dan rollback
        eB = rel_guardian.execute_operation(op_id_B)
        assert eB["ok"] is False, "DR4 FAIL: Migration rusak harus gagal"

        # Op A harus masih ada di DB (tidak ikut terhapus)
        conn = sqlite3.connect(str(fresh_db))
        row = conn.execute(
            "SELECT status FROM operations WHERE id=?", (op_id_A,)
        ).fetchone()
        conn.close()
        assert row is not None, (
            "DR4 FAIL: Op A harus masih ada di DB setelah rollback Op B"
        )

        # DB harus masih valid
        conn = sqlite3.connect(str(fresh_db))
        tables = {row[0] for row in
                  conn.execute(
                      "SELECT name FROM sqlite_master WHERE type='table'"
                  ).fetchall()}
        conn.close()
        assert {"nodes", "edges", "operations", "approvals"}.issubset(tables)


# ---------------------------------------------------------------------------
# DR5: Impossible state — history sebelum rollback tidak ikut terhapus
# ---------------------------------------------------------------------------

class TestImpossibleStateProtection:
    def test_pre_rollback_history_preserved(self, rel_guardian, fresh_db):
        """
        DR5: Sesuai SYNAPSE.md 2.2 — rollback 'sukses teknis' bisa hasilkan
        state historis mustahil jika data pre-rollback hilang.

        Verifikasi: operasi yang sudah 'verified' sebelum snapshot diambil
        TETAP ada setelah rollback. Ini adalah bug yang dilaporkan pidpid di
        BUG-03 (#6) — test ini menjadi regression test setelah fix.

        Catatan QC-2: test ini MUNGKIN FAIL jika BUG-03 belum diperbaiki.
        Jika fail, catat sebagai konfirmasi BUG-03 masih open.
        """
        # Step 1: Operasi yang sukses sebelum snapshot (baseline history)
        r_good = rel_guardian.propose_operation(
            "service.restart",
            {"service": "pre-snapshot-svc"},
            "pre-snapshot-target"
        )
        op_good = r_good["operation_id"]
        e_good = rel_guardian.execute_operation(op_good)
        assert e_good["ok"] is True, "Setup DR5: operasi pertama harus verified"
        assert e_good["status"] == "verified"

        # Step 2: Migration rusak ke target berbeda → rollback
        r_bad = rel_guardian.propose_operation(
            "db.run_migration",
            {"sql": "BREAK THIS FOR DR5 @@@;",
             "db_path": str(fresh_db)},
            "dr5-broken-target"
        )
        op_bad = r_bad["operation_id"]
        rel_guardian.approve_operation(op_bad, "approved", "dr5 force rollback")
        e_bad = rel_guardian.execute_operation(op_bad)
        assert e_bad["ok"] is False  # harus gagal/rollback

        # Step 3: Verifikasi op_good masih ada (historical state terjaga)
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
        """
        DR6: SYNAPSE.md 2.7 — 'Graph terbentuk dari repo sample dalam < 30 detik'.

        Seed.py adalah proxy untuk understand_repo() minimal:
        membuat schema + insert semua nodes & edges.
        Jika seed.py saja > 30 detik, understand_repo() pasti lebih lambat.

        Target: seed DB (12 nodes, 11 edges) selesai dalam < 5 detik
        (jauh di bawah batas 30 detik untuk asuransi).
        """
        start = time.monotonic()
        db_path = create_demo_db(tmp_path / "timing_test.db")
        elapsed = time.monotonic() - start

        assert db_path.exists(), "DR6 FAIL: Demo DB tidak terbuat"
        assert elapsed < 5.0, (
            f"DR6 FAIL: Seed DB harus selesai < 5 detik, memakan {elapsed:.3f}s. "
            "understand_repo() akan jauh lebih lambat dari ini — periksa dependency."
        )

    def test_seed_db_nodes_queryable_immediately(self, tmp_path):
        """
        DR6b: Graph harus bisa di-query segera setelah selesai dibuat
        (tidak ada lazy init, tidak ada background task yang belum selesai).
        """
        db_path = create_demo_db(tmp_path / "queryable_test.db")

        conn = sqlite3.connect(str(db_path))
        # Query traversal sederhana: semua simbol yang ada di file tertentu
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
        """
        DR7: Setelah menjalankan beberapa operasi (sukses dan gagal),
        tidak boleh ada yang tersisa dalam status 'executing'.
        Invariant: operation_status_not_executing (synapse.invariants.yaml).
        """
        # Jalankan campuran operasi sukses dan gagal
        ops_to_run = [
            # (tool, params, target, should_approve, should_succeed)
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

        # Cek tidak ada yang stuck 'executing'
        conn = sqlite3.connect(str(fresh_db))
        stuck = conn.execute(
            "SELECT id, tool_name FROM operations WHERE status='executing'"
        ).fetchall()
        conn.close()

        assert len(stuck) == 0, (
            f"DR7 FAIL: Ada {len(stuck)} operasi stuck 'executing': "
            f"{[(s[1], s[0][:8]) for s in stuck]}"
        )
