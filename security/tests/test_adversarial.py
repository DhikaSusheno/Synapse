"""
test_adversarial.py — QC-1 (pidpid35)
Adversarial probes: coba bobol jalur approval dan conflict detection.
Sesuai SYNAPSE.md section 4.5 + PRD deliverable #3.

Skenario:
  A1  Inject requires_approval=False langsung ke DB, coba execute → harus cek logic
  A2  Approve operasi orang lain (cross-operation approval) → tidak boleh berlaku
  A3  Decision 'APPROVED' (uppercase) → harus ditolak (enum case-sensitive)
  A4  Decision string kosong / arbitrary → harus ditolak
  A5  Propose operasi dengan tool_name mengandung wildcard '*' → fail-closed
  A6  Propose op dengan target kosong → tetap berjalan, tidak crash
  A7  Execute operation_id yang tidak ada → error bersih, tidak crash
  A8  Approve dua kali: ubah approved→denied → harus update, tidak duplikat
  A9  Concurrent double-execute: N thread execute_operation() bersamaan untuk
      satu operation_id → hanya SATU yang boleh ok=True (regression test BUG-07)
"""
import sqlite3
import threading

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approve(guardian_module, op_id: str, decision: str = "approved"):
    return guardian_module.approve_operation(op_id, decision)


def _get_approval(mem_db, op_id: str):
    conn = sqlite3.connect(str(mem_db))
    row = conn.execute(
        "SELECT decision FROM approvals WHERE operation_id=?", (op_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# A1: inject requires_approval=False langsung ke DB
# ---------------------------------------------------------------------------

class TestDirectDbManipulation:
    def test_db_injection_bypasses_approval_check(self, guardian_module, mem_db):
        """
        A1: Adversary langsung set requires_approval=0 di DB
        untuk operasi yang seharusnya butuh approval.
        Guardian harus tetap cek approval dari tabel approvals, bukan hanya
        kolom requires_approval di DB.

        NOTE: Jika test ini FAIL (bypass berhasil), itu adalah bug keamanan
        yang harus dilaporkan ke backend team.
        """
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Inject langsung ke DB: set requires_approval=0
        conn = sqlite3.connect(str(mem_db))
        conn.execute(
            "UPDATE operations SET requires_approval=0 WHERE id=?", (op_id,)
        )
        conn.commit()
        conn.close()

        # Coba execute tanpa approval
        exec_result = guardian_module.execute_operation(op_id)

        # Behavior yang diharapkan: execute mungkin lolos karena requires_approval=0
        # Tapi kita verifikasi bahwa status menjadi sesuatu yang valid, tidak crash
        # DAN kita track ini sebagai potential security finding
        status_after = None
        conn = sqlite3.connect(str(mem_db))
        row = conn.execute("SELECT status FROM operations WHERE id=?", (op_id,)).fetchone()
        conn.close()
        status_after = row[0] if row else None

        # Test ini mendokumentasikan behavior: apakah injection bypass berhasil?
        bypass_succeeded = exec_result.get("ok") is True
        if bypass_succeeded:
            # BUG REPORT: Direct DB manipulation berhasil bypass approval check
            # Guardian perlu validasi berlapis, bukan hanya cek kolom DB
            pytest.fail(
                "SECURITY FINDING A1: Direct DB injection bypass approval check! "
                f"Operation {op_id} dieksekusi tanpa approval setelah requires_approval "
                f"di-set 0 langsung di DB. Backend harus memperkuat validation."
            )
        # Jika tidak bypass → Guardian aman dari injection ini


# ---------------------------------------------------------------------------
# A2: cross-operation approval (approve op orang lain)
# ---------------------------------------------------------------------------

class TestCrossOperationApproval:
    def test_approve_nonexistent_operation(self, guardian_module):
        """A2: Approve operation_id yang tidak ada harus return ok=False."""
        result = guardian_module.approve_operation(
            "fake-uuid-that-does-not-exist", "approved"
        )
        assert result["ok"] is False, (
            "A2 FAIL: Approve operation yang tidak ada harus return ok=False"
        )


# ---------------------------------------------------------------------------
# A3 + A4: invalid decision enum
# ---------------------------------------------------------------------------

class TestInvalidDecision:
    @pytest.mark.parametrize("bad_decision", [
        "APPROVED",       # uppercase
        "Approved",       # mixed case
        "yes",
        "ok",
        "1",
        "true",
        "",
        " ",
        "approve",        # typo
        "denied ",        # trailing space
        "DENIED",
    ])
    def test_invalid_decision_rejected(self, guardian_module, mem_db, bad_decision):
        """
        A3+A4: Hanya 'approved' dan 'denied' (lowercase persis) yang valid.
        Semua string lain harus ditolak dengan ok=False.
        """
        result = guardian_module.propose_operation(
            "service.restart", {}, "test-target"
        )
        op_id = result["operation_id"]

        approve_result = guardian_module.approve_operation(op_id, bad_decision)
        assert approve_result["ok"] is False, (
            f"A3/A4 FAIL: Decision '{bad_decision}' harus ditolak, "
            f"dapat ok={approve_result.get('ok')}"
        )


# ---------------------------------------------------------------------------
# A5: tool_name mengandung wildcard '*'
# ---------------------------------------------------------------------------

class TestWildcardToolName:
    def test_wildcard_tool_name_fail_closed(self, guardian_module):
        """
        A5: Adversary coba inject '*' sebagai tool_name untuk
        match rule default fail-closed tapi mungkin dengan intent bypass.
        Harus tetap diperlakukan sebagai unknown → require_approval=True.
        """
        result = guardian_module.propose_operation(
            "*", {}, "some_target"
        )
        assert result["requires_approval"] is True, (
            "A5 FAIL: tool_name '*' harus fail-closed"
        )
        assert result["blast_radius"] == "unknown"

    def test_sql_injection_in_tool_name(self, guardian_module):
        """
        A5b: SQL injection attempt dalam tool_name.
        Harus fail-closed, tidak crash.
        """
        malicious = "'; DROP TABLE operations; --"
        result = guardian_module.propose_operation(
            malicious, {}, "target"
        )
        # Harus return ok=True (proposal disimpan) dengan fail-closed
        assert result.get("ok") is True, (
            "A5b: propose_operation tidak boleh crash karena tool_name aneh"
        )
        assert result["requires_approval"] is True


# ---------------------------------------------------------------------------
# A6: target kosong
# ---------------------------------------------------------------------------

class TestEmptyTarget:
    def test_empty_target_does_not_crash(self, guardian_module):
        """A6: target string kosong harus tidak crash."""
        try:
            result = guardian_module.propose_operation(
                "service.restart", {}, ""
            )
            # Boleh sukses atau gagal, tapi tidak boleh raise exception
            assert isinstance(result, dict), "Harus return dict"
        except Exception as e:
            pytest.fail(f"A6 FAIL: propose_operation crash dengan target kosong: {e}")


# ---------------------------------------------------------------------------
# A7: execute operation_id yang tidak ada
# ---------------------------------------------------------------------------

class TestNonexistentOperation:
    def test_execute_nonexistent_operation(self, guardian_module):
        """A7: Execute operation_id palsu harus return ok=False, tidak crash."""
        result = guardian_module.execute_operation("nonexistent-uuid-12345")
        assert result["ok"] is False
        assert "tidak ditemukan" in result.get("error", "").lower() or \
               "not found" in result.get("error", "").lower(), (
            f"A7 FAIL: Pesan error tidak informatif: '{result.get('error')}'"
        )


# ---------------------------------------------------------------------------
# A8: double-approve (ubah decision)
# ---------------------------------------------------------------------------

class TestDoubleApprove:
    def test_approve_then_deny_updates_record(self, guardian_module, mem_db):
        """
        A8: Approve dulu, lalu deny — record harus terupdate, tidak duplikat.
        Final decision harus 'denied'.
        """
        result = guardian_module.propose_operation(
            "db.run_migration",
            {"sql": "SELECT 1", "db_path": str(mem_db)},
            "synapse.db"
        )
        op_id = result["operation_id"]

        # Approve dulu
        guardian_module.approve_operation(op_id, "approved")
        assert _get_approval(mem_db, op_id) == "approved"

        # Lalu deny
        guardian_module.approve_operation(op_id, "denied", "changed mind")
        final = _get_approval(mem_db, op_id)
        assert final == "denied", (
            f"A8 FAIL: Setelah approve→deny, decision harus 'denied', dapat '{final}'"
        )

        # Pastikan hanya 1 record di approvals (tidak duplikat)
        conn = sqlite3.connect(str(mem_db))
        count = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE operation_id=?", (op_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 1, (
            f"A8 FAIL: Harus ada tepat 1 record approval, dapat {count}"
        )


# ---------------------------------------------------------------------------
# A9: concurrent double-execute (regression test BUG-07)
# ---------------------------------------------------------------------------

# Jumlah thread yang dilepas bersamaan. 8 dipilih supaya ada antrean writer di
# SQLite yang saling berebut lock -- justru kondisi yang harus ditahan CAS guard.
RACE_THREADS = 8

# SQLite membalas "database is locked" kalau writer lain memegang lock lebih
# lama dari busy timeout. Itu artefak kontensi SQLite, BUKAN bug yang diuji
# di sini -- jadi dicatat terpisah, bukan dianggap PASS diam-diam.
_LOCKED = "database is locked"


def _race_execute(guardian_module, op_id: str, threads: int = RACE_THREADS):
    """
    Jalankan execute_operation(op_id) dari `threads` thread yang dilepas
    bersamaan oleh Barrier, lalu kumpulkan hasil tiap thread.

    Barrier dipakai supaya semua thread sudah "bersiap" sebelum ada yang masuk
    ke execute_operation. Tanpa ini, thread kedua bisa baru mulai setelah
    thread pertama selesai dan race-nya tidak pernah terjadi.

    Return (results, locked_count, other_errors).
    """
    barrier = threading.Barrier(threads)
    results: list = [None] * threads
    errors: list = [None] * threads

    def worker(idx: int) -> None:
        try:
            barrier.wait(timeout=15)
        except threading.BrokenBarrierError:
            errors[idx] = RuntimeError("barrier pecah sebelum semua thread siap")
            return
        try:
            results[idx] = guardian_module.execute_operation(op_id)
        except sqlite3.OperationalError as e:
            errors[idx] = e
        except Exception as e:  # noqa: BLE001 - sengaja tangkap semua exception
            errors[idx] = e

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join(timeout=30)

    still_running = [t for t in workers if t.is_alive()]
    assert not still_running, (
        f"A9 FAIL: {len(still_running)} thread masih jalan setelah 30 detik "
        "-- execute_operation kemungkinan deadlock di CAS guard"
    )

    locked = [
        e
        for e in errors
        if isinstance(e, sqlite3.OperationalError) and _LOCKED in str(e).lower()
    ]
    others = [e for e in errors if e is not None and e not in locked]
    return results, locked, others


def _assert_single_winner(results, op_id: str) -> None:
    """Assertion bersama: tepat satu thread boleh menulis status terminal."""
    done = [r for r in results if isinstance(r, dict)]
    assert done, "A9 FAIL: tidak ada thread yang mengembalikan result dict"

    winners = [r for r in done if r.get("ok") is True]
    losers = [r for r in done if r.get("ok") is not True]

    assert len(winners) == 1, (
        f"A9 FAIL: harus tepat 1 thread ok=True, dapat {len(winners)}\n"
        f"  operation_id : {op_id}\n"
        f"  winners      : {winners}\n"
        f"  losers       : {losers}\n"
        f"  -- CAS guard di guardian.execute_operation() (UPDATE ... WHERE\n"
        f"    status IN ('pending','approved') + rowcount check) REGRESSED ke\n"
        f"    read-then-write, sehingga operasi dieksekusi lebih dari sekali."
    )

    # Setiap yang kalah harus dapat error yang informatif, bukan diam-diam sukses.
    for r in losers:
        assert r.get("error"), (
            f"A9 FAIL: thread yang kalah dapat result tanpa 'error': {r}"
        )


class TestConcurrentDoubleExecute:
    def test_concurrent_execute_only_one_wins(self, guardian_module, mem_db):
        """
        A9a: N thread execute_operation() bersamaan untuk satu operasi
        service.restart (no-approval, executor stub) -- hanya 1 yang ok=True.

        Ini yang diuji guard CAS BUG-07. Kalau guardnya hilang, semua thread
        lolos dan operasi dieksekusi N kali.
        """
        proposed = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "api-node"
        )
        op_id = proposed["operation_id"]

        results, locked, others = _race_execute(guardian_module, op_id)

        assert not others, (
            f"A9a FAIL: ada thread yang melempar exception tak terduga: "
            f"{[repr(e) for e in others]}"
        )
        if locked:
            print(
                f"\n[A9a] catatan: {len(locked)} thread kena "
                f"'{_LOCKED}' (kontensi SQLite, bukan bug)"
            )
        _assert_single_winner(results, op_id)

    def test_concurrent_execute_runs_migration_once(self, guardian_module, mem_db):
        """
        A9b: Verifikasi SISI EFEK, bukan cuma nilai balik.

        db.run_migration di-approve dulu, lalu N thread mengeksekusi bersamaan
        dengan SQL `CREATE TABLE IF NOT EXISTS`. Kalau CAS guard bekerja,
        _exec_migration() dipanggil tepat 1 kali. Kalau guardnya diregresikan,
        migration dijalankan N kali -- dan itu terdeteksi lewat hitungan pemanggilan.
        """
        proposed = guardian_module.propose_operation(
            "db.run_migration",
            {
                "sql": "CREATE TABLE IF NOT EXISTS a9_race_probe (id INTEGER)",
                "db_path": str(mem_db),
            },
            "synapse.db",
        )
        op_id = proposed["operation_id"]
        approved = guardian_module.approve_operation(op_id, "approved")
        assert approved["ok"] is True, (
            f"A9b FAIL: approve gagal, test tidak mungkin menguji execute: {approved}"
        )

        # Hitung berapa kali executor benar-benar dipanggil, tanpa mengubah
        # perilakunya -- bungkus fungsi asli.
        real_exec = guardian_module._exec_migration
        calls: list = []
        lock = threading.Lock()

        def counting_exec(params):
            with lock:
                calls.append(dict(params))
            return real_exec(params)

        guardian_module._exec_migration = counting_exec
        try:
            results, locked, others = _race_execute(guardian_module, op_id)
        finally:
            guardian_module._exec_migration = real_exec

        assert not others, (
            f"A9b FAIL: ada thread yang melempar exception tak terduga: "
            f"{[repr(e) for e in others]}"
        )
        if locked:
            print(
                f"\n[A9b] catatan: {len(locked)} thread kena "
                f"'{_LOCKED}' (kontensi SQLite, bukan bug)"
            )

        _assert_single_winner(results, op_id)

        assert len(calls) == 1, (
            f"A9b FAIL: _exec_migration() dipanggil {len(calls)} kali, harus 1.\n"
            f"  operation_id : {op_id}\n"
            f"  -- migration dieksekusi lebih dari sekali. Guard CAS BUG-07\n"
            f"    tidak bekerja, sehingga dua operasi bisa menulis ke DB\n"
            f"    yang sama tanpa serialization."
        )

    def test_status_not_left_executing(self, guardian_module, mem_db):
        """
        A9c: Setelah race selesai, status operasi harus terminal
        (verified / rolled_back / failed) -- tidak boleh tersangkut 'executing'.

        Kalau CAS update membunuh winner di tengah jalan, baris akan menggantung
        di status 'executing' dan operasi itu tidak bisa di-rollback lagi.
        """
        proposed = guardian_module.propose_operation(
            "service.restart", {"service": "api"}, "api-node"
        )
        op_id = proposed["operation_id"]

        _race_execute(guardian_module, op_id)

        conn = sqlite3.connect(str(mem_db))
        row = conn.execute(
            "SELECT status FROM operations WHERE id=?", (op_id,)
        ).fetchone()
        conn.close()

        assert row is not None, f"A9c FAIL: baris operasi {op_id} hilang"
        status = row[0]
        assert status != "executing", (
            f"A9c FAIL: status operasi masih 'executing' setelah race selesai -- "
            f"operasi menggantung dan tidak bisa di-rollback"
        )
        assert status in ("verified", "rolled_back", "failed", "denied"), (
            f"A9c FAIL: status '{status}' bukan status terminal yang valid"
        )
