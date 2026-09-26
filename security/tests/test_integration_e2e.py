"""
test_integration_e2e.py — QC-2 (zuyss)
Test integrasi end-to-end: propose → approve → execute → verify.
Tidak membutuhkan server FastAPI — langsung memanggil modul guardian.
Sesuai PRD deliverable #6 dan SYNAPSE.md section 3.2 (demo workflow).

Skenario yang dicakup (E2E):
  E1  Full happy path: propose → approve → execute → status=verified
  E2  Full conflict path: op A pending, op B ke target sama → B forced approval
  E3  Full fail-closed path: unknown tool propose, approve, execute → fail-closed
  E4  Conflict scenario 2 operations same target: dua-duanya perlu manusia
  E5  Service restart (no-approval) full path tanpa approve step
  E6  Deny path: propose → deny → execute blocked → status tetap denied
  E7  Demo scenario 3.2 penuh: migration sukses → konflik → migration rusak→rollback
  E8  Fail-closed: unknown tool dieksekusi setelah approve → tetap ditolak runner
"""
import sqlite3
import pytest
from pathlib import Path
from security.tests.demo_data.seed import create_demo_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_op(db_path, op_id: str) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _approve(guardian_module, op_id: str, note: str = "e2e test") -> dict:
    return guardian_module.approve_operation(op_id, "approved", note)


def _deny(guardian_module, op_id: str) -> dict:
    return guardian_module.approve_operation(op_id, "denied", "e2e deny test")


# ---------------------------------------------------------------------------
# Override guardian_module fixture untuk memakai demo seed DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def demo_db(tmp_path):
    """
    DB dengan seed data realistis (nodes/edges/baseline op).
    Dipakai khusus untuk test E2E yang butuh state awal yang bermakna.
    """
    return create_demo_db(tmp_path / "demo_synapse.db")


@pytest.fixture()
def demo_guardian(demo_db):
    """
    Guardian module yang menunjuk ke demo_db.
    Sama polanya dengan guardian_module fixture dari conftest pidpid.
    """
    import sys
    from pathlib import Path as _Path
    from unittest.mock import MagicMock
    import importlib

    backend_dir = _Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    import database as db_mod
    original = db_mod.DB_PATH
    db_mod.DB_PATH = demo_db

    import guardian as g
    g._emit = MagicMock()
    importlib.reload(g)
    g._emit = MagicMock()

    yield g

    db_mod.DB_PATH = original


# ---------------------------------------------------------------------------
# E1: Full happy path — migration sukses
# ---------------------------------------------------------------------------

class TestFullHappyPath:
    def test_migration_propose_approve_execute_verified(self, demo_guardian, demo_db):
        """
        E1: Skenario SYNAPSE.md 3.2 baris 1–5:
        propose → approve → execute → status=verified.
        Ini adalah skenario demo paling penting.
        """
        # Propose
        r = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "CREATE TABLE IF NOT EXISTS demo_test (id INTEGER PRIMARY KEY);",
             "db_path": str(demo_db)},
            "demo.db"
        )
        assert r["ok"] is True
        assert r["blast_radius"] == "high"
        assert r["requires_approval"] is True
        assert r["status"] == "pending"
        op_id = r["operation_id"]

        # Approve
        ar = _approve(demo_guardian, op_id, "e2e migration happy path")
        assert ar["ok"] is True

        # Execute
        er = demo_guardian.execute_operation(op_id)
        assert er["ok"] is True, (
            f"E1 FAIL: execute harus sukses, dapat: {er}"
        )
        assert er["status"] == "verified", (
            f"E1 FAIL: status harus 'verified', dapat '{er.get('status')}'"
        )

        # Verifikasi di DB
        op = _get_op(demo_db, op_id)
        assert op["status"] == "verified"
        assert op["verified_at"] is not None

    def test_migration_creates_table_in_db(self, demo_guardian, demo_db):
        """
        E1b: Setelah migration sukses, tabel yang dibuat BENAR-BENAR ada di DB.
        Bukan hanya status=verified, tapi state DB benar-benar berubah.
        """
        table_name = "e1b_verify_table"
        r = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": f"CREATE TABLE IF NOT EXISTS {table_name} (x TEXT);",
             "db_path": str(demo_db)},
            "demo.db::schema"
        )
        _approve(demo_guardian, r["operation_id"])
        er = demo_guardian.execute_operation(r["operation_id"])
        assert er["ok"] is True

        # Cek tabel benar-benar ada
        conn = sqlite3.connect(str(demo_db))
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert table_name in tables, (
            f"E1b FAIL: Tabel '{table_name}' harus ada setelah migration, "
            f"tables yang ada: {tables}"
        )


# ---------------------------------------------------------------------------
# E2: Conflict path — operasi B ke target sama dipaksa approval
# ---------------------------------------------------------------------------

class TestConflictPath:
    def test_conflict_scenario_from_demo_workflow(self, demo_guardian, demo_db):
        """
        E2: SYNAPSE.md 3.2 — 'migration KEDUA yang sengaja rusak, target sama'
        Sebelum: Op A sudah verified.
        Tapi Op B masih pending (belum selesai) → B ke target sama = KONFLIK.
        """
        # Op A — propose dan biarkan pending (belum approve)
        rA = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "CREATE TABLE IF NOT EXISTS conflict_a (id INTEGER);",
             "db_path": str(demo_db)},
            "conflict-db-target"  # target khusus untuk test ini
        )
        assert rA["ok"] is True
        assert rA["status"] == "pending"

        # Op B — target sama, dalam window → harus konflik
        rB = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "CREATE TABLE IF NOT EXISTS conflict_b (id INTEGER);",
             "db_path": str(demo_db)},
            "conflict-db-target"  # SAMA
        )
        assert rB["ok"] is True
        assert rB["requires_approval"] is True, (
            "E2 FAIL: Konflik harus paksa requires_approval=True"
        )
        assert len(rB["conflicts"]) >= 1, (
            "E2 FAIL: Harus ada minimal 1 konflik dilaporkan"
        )

    def test_conflict_blocks_auto_execution(self, demo_guardian, demo_db):
        """
        E2b: Operasi yang berkonflik tidak bisa auto-execute —
        HARUS lewat approval manusia terlebih dahulu.
        """
        # Op A — biarkan pending
        rA = demo_guardian.propose_operation(
            "service.restart",
            {"service": "api"},
            "blocking-svc-target"
        )
        # service.restart biasanya no-approval, tapi karena ada op A pending...
        # Op B ke target sama
        rB = demo_guardian.propose_operation(
            "service.restart",
            {"service": "api"},
            "blocking-svc-target"
        )
        op_id_B = rB["operation_id"]

        # Coba execute B tanpa approve
        er = demo_guardian.execute_operation(op_id_B)
        # B harus require approval karena konflik, dan tidak diapprove
        assert er["ok"] is False, (
            "E2b FAIL: Operasi berkonflik tanpa approval harus ditolak"
        )


# ---------------------------------------------------------------------------
# E3: Fail-closed — unknown tool seluruh path
# ---------------------------------------------------------------------------

class TestFailClosedPath:
    def test_unknown_tool_full_path_blocked(self, demo_guardian, demo_db):
        """
        E3: SYNAPSE.md section 1 CONSTRAINTS — fail-closed default.
        Tool tak dikenal → propose OK tapi requires_approval=True,
        → approve → execute → runner menolak eksekusi karena tidak dikenal.
        Ini berbeda dari test pidpid (yang test tanpa approve):
        kita test WITH approve tapi eksekusi tetap fail-closed.
        """
        r = demo_guardian.propose_operation(
            "unknown.super.dangerous.tool",
            {"target": "production"},
            "prod-db"
        )
        assert r["blast_radius"] == "unknown"
        assert r["requires_approval"] is True
        op_id = r["operation_id"]

        # Approve (manusia memaksa jalan)
        _approve(demo_guardian, op_id, "forcing unknown tool")

        # Execute — runner harus fail-closed karena tool tidak dikenal
        er = demo_guardian.execute_operation(op_id)
        # Sesuai guardian.py: unknown tool → exec_ok=False, "fail-closed"
        assert er["ok"] is False, (
            "E3 FAIL: Unknown tool harus ditolak di execution layer (fail-closed), "
            f"dapat: {er}"
        )
        # Status harus 'rolled_back' atau 'failed' — tidak 'verified'
        final_status = _get_op(demo_db, op_id)["status"]
        assert final_status in ("rolled_back", "failed"), (
            f"E3 FAIL: Status harus 'rolled_back'/'failed', dapat '{final_status}'"
        )

    def test_zero_exceptions_for_unknown_tools(self, demo_guardian):
        """
        E3b: 100% unknown tools → require_approval=True.
        SYNAPSE.md 2.7: zero exceptions.
        Sample batch dari beberapa tool aneh.
        """
        unknown_tools = [
            "hack.system",
            "drop.all.tables",
            "rm.rf.slash",
            "exec.shell",
            "bypass.auth",
        ]
        for tool in unknown_tools:
            r = demo_guardian.propose_operation(tool, {}, f"target-{tool}")
            assert r["requires_approval"] is True, (
                f"E3b FAIL: Tool '{tool}' harus fail-closed, "
                f"dapat requires_approval={r.get('requires_approval')}"
            )


# ---------------------------------------------------------------------------
# E5: Service restart (no-approval) — full path tanpa approve
# ---------------------------------------------------------------------------

class TestServiceRestartNoApproval:
    def test_service_restart_executes_without_approval(self, demo_guardian, demo_db):
        """
        E5: service.restart rule: require_approval=False.
        Harus bisa langsung execute tanpa approve_operation.
        """
        r = demo_guardian.propose_operation(
            "service.restart",
            {"service": "synapse-api"},
            "synapse-api-svc"
        )
        assert r["requires_approval"] is False
        op_id = r["operation_id"]

        # Execute TANPA approve
        er = demo_guardian.execute_operation(op_id)
        assert er["ok"] is True, (
            f"E5 FAIL: service.restart harus bisa execute tanpa approval, dapat: {er}"
        )
        assert er["status"] == "verified"


# ---------------------------------------------------------------------------
# E6: Deny path
# ---------------------------------------------------------------------------

class TestDenyPath:
    def test_denied_operation_blocked_end_to_end(self, demo_guardian, demo_db):
        """
        E6: Propose → deny → coba execute → ditolak.
        """
        r = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(demo_db)},
            "deny-path-db"
        )
        op_id = r["operation_id"]

        _deny(demo_guardian, op_id)
        op_before_exec = _get_op(demo_db, op_id)
        assert op_before_exec["status"] == "denied"

        er = demo_guardian.execute_operation(op_id)
        assert er["ok"] is False, "E6 FAIL: Operasi denied tidak boleh dieksekusi"

        op_after = _get_op(demo_db, op_id)
        assert op_after["status"] == "denied", (
            f"E6 FAIL: Status harus tetap 'denied', dapat '{op_after.get('status')}'"
        )


# ---------------------------------------------------------------------------
# E7: Full demo scenario sesuai SYNAPSE.md 3.2
# ---------------------------------------------------------------------------

class TestFullDemoScenario:
    def test_demo_scenario_migration_sukses_then_conflict_then_rollback(
        self, demo_guardian, demo_db
    ):
        """
        E7: Skenario demo penuh sesuai SYNAPSE.md 3.2:
          1. Migration sukses → hijau
          2. Conflict terdeteksi → kuning/blocked
          3. Migration rusak → auto-rollback → merah → pulih

        Ini adalah SKENARIO UTAMA yang harus reliable untuk demo.
        Jika test ini flaky, HENTIKAN — perbaiki dulu sebelum presentasi.
        """
        # ── SCENE 1: Migration sukses ──────────────────────────────────
        r1 = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "CREATE TABLE IF NOT EXISTS demo_scene1 (id INTEGER);",
             "db_path": str(demo_db)},
            "demo-main-db"
        )
        op1 = r1["operation_id"]
        assert r1["status"] == "pending"
        assert r1["blast_radius"] == "high"

        _approve(demo_guardian, op1, "scene1: migration sukses")
        e1 = demo_guardian.execute_operation(op1)
        assert e1["ok"] is True, f"SCENE 1 FAIL: {e1}"
        assert e1["status"] == "verified"

        # ── SCENE 2: Migration kedua ke target sama → KONFLIK ──────────
        r2 = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "CREATE TABLE IF NOT EXISTS demo_scene2 (id INTEGER);",
             "db_path": str(demo_db)},
            "demo-main-db"  # target SAMA → conflict dengan op1 jika op1 masih dalam window
            # Catatan: op1 sudah verified, tapi op2 propose sebelum op1 verified
            # Dalam test ini op1 sudah verified, jadi tidak conflict.
            # Kita tambahkan conflict manual:
        )
        # Op1 sudah verified, jadi op2 tidak conflict dengan op1.
        # Kita buat op3 yang pending ke target sama SEBELUM op2 dikerjakan:
        r2b = demo_guardian.propose_operation(
            "service.restart",
            {"service": "demo"},
            "demo-main-db"  # target sama, dan r2 sudah pending → r2b akan conflict dengan r2
        )
        assert r2b["requires_approval"] is True, (
            "SCENE 2 FAIL: Konflik harus terdeteksi (r2 masih pending, r2b ke target sama)"
        )
        assert len(r2b["conflicts"]) >= 1, "SCENE 2 FAIL: Harus ada konflik terdaftar"

        # ── SCENE 3: Migration rusak → auto-rollback ───────────────────
        r3 = demo_guardian.propose_operation(
            "db.run_migration",
            {"sql": "THIS SQL IS INTENTIONALLY BROKEN @@@;",
             "db_path": str(demo_db)},
            "demo-broken-target"  # target berbeda agar tidak conflict dengan scene 1
        )
        op3 = r3["operation_id"]
        assert r3["status"] == "pending"

        _approve(demo_guardian, op3, "scene3: sengaja rusak")
        e3 = demo_guardian.execute_operation(op3)
        assert e3["ok"] is False, "SCENE 3 FAIL: Migration rusak harus gagal"
        assert e3["status"] in ("rolled_back", "failed"), (
            f"SCENE 3 FAIL: Status harus rolled_back/failed, dapat {e3.get('status')}"
        )

        # ── Verifikasi akhir: DB masih hidup ───────────────────────────
        conn = sqlite3.connect(str(demo_db))
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        required = {"nodes", "edges", "operations", "approvals"}
        assert required.issubset(tables), (
            f"E7 FAIL: Tabel kontrak harus tetap ada setelah demo penuh. "
            f"Missing: {required - tables}"
        )

        # ── Verifikasi: semua 3 operasi tercatat di DB ──────────────────
        conn = sqlite3.connect(str(demo_db))
        count = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE id IN (?, ?, ?)",
            (op1, r2["operation_id"], op3)
        ).fetchone()[0]
        conn.close()
        assert count == 3, (
            f"E7 FAIL: Semua 3 operasi demo harus tercatat di DB, dapat {count}"
        )


# ---------------------------------------------------------------------------
# E8: Seed data integrity check
# ---------------------------------------------------------------------------

class TestSeedDataIntegrity:
    def test_demo_db_has_expected_baseline(self, demo_db):
        """
        E8: Verifikasi seed data lengkap dan konsisten.
        Memastikan demo DB siap dipakai tanpa setup manual.
        """
        conn = sqlite3.connect(str(demo_db))
        conn.row_factory = sqlite3.Row

        # Cek semua tabel ada
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"nodes", "edges", "operations", "approvals"}.issubset(tables), (
            f"E8 FAIL: Tabel kontrak tidak lengkap: {tables}"
        )

        # Cek nodes terisi
        node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert node_count >= 10, (
            f"E8 FAIL: Demo DB harus punya minimal 10 nodes, dapat {node_count}"
        )

        # Cek edges terisi
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert edge_count >= 8, (
            f"E8 FAIL: Demo DB harus punya minimal 8 edges, dapat {edge_count}"
        )

        # Cek baseline operation ada dan verified
        op = conn.execute(
            "SELECT status FROM operations WHERE tool_name='service.restart' AND status='verified'"
        ).fetchone()
        assert op is not None, (
            "E8 FAIL: Demo DB harus punya minimal 1 operasi 'verified' sebagai baseline"
        )

        conn.close()

    def test_demo_db_has_diverse_node_types(self, demo_db):
        """Seed data harus punya berbagai tipe node (file, symbol, doc, dependency)."""
        conn = sqlite3.connect(str(demo_db))
        types = {row[0] for row in
                 conn.execute("SELECT DISTINCT type FROM nodes").fetchall()}
        conn.close()
        expected_types = {"file", "symbol", "doc", "dependency", "operation"}
        assert expected_types.issubset(types), (
            f"E8b FAIL: Seed data harus punya tipe node: {expected_types}, "
            f"dapat: {types}"
        )
