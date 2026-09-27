"""
test_issue_46_47.py — regression test untuk issue #46 dan #47.

  #46  guardian.approve_operation() tidak punya guard status terminal
       -> operasi yang sudah selesai bisa di-approve ulang, status di-reset
          ke 'approved', CAS di execute_operation() lolos, dan operasinya
          dieksekusi DUA KALI.
  #47  engine._TS_QUERIES["javascript"] kurung tidak balanced
       -> tree_sitter.Query() menolak, _load_ts_uncached() balik None,
          bahasa di-blacklist permanen, dan semua file .js/.jsx/.mjs
          menghasilkan nol simbol.

Test #47 sengaja memakai file JavaScript sungguhan, bukan cuma menghitung
kurung — karena kurung yang seimbang belum tentu query yang valid.
"""
import io
import sqlite3
import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


JS_SOURCE = textwrap.dedent("""\
    import React from 'react';
    import { useState } from "react";
    import * as path from 'path';

    export default function Hello() { return null; }

    export function named() { return 1; }

    const arrow = () => 42;
    const fexpr = function () { return 2; };

    class Widget extends React.Component {
      render() { return null; }
    }

    export async function* gen() { yield 1; }

    const complex = (a) => { if (a) { return 1 } else { return 2 } };
""")


# ===========================================================================
# #47 — query tree-sitter
# ===========================================================================

class TestIssue47TsQueries:
    def test_parens_balanced_in_every_query(self):
        """'(' harus sama dengan ')' di tiap query (bug pertama #47)."""
        import engine
        for lang, q in engine._TS_QUERIES.items():
            assert q.count("(") == q.count(")"), (
                f"_TS_QUERIES[{lang!r}] kurung tidak seimbang: "
                f"'(' = {q.count('(')} vs ')' = {q.count(')')}"
            )

    def test_every_query_actually_compiles(self):
        """
        Query harus benar-benar bisa dibuat — kurung seimbang belum tentu
        cukup. Bug kedua #47: `(import_statement source: (template_string))`
        impossible karena field "source" hanya bisa berisi `string`.
        """
        engine = pytest.importorskip("engine")
        ts = engine._load_ts_uncached("javascript")
        assert ts is not None, (
            "query javascript ditolak tree-sitter — cek _TS_QUERIES['javascript']"
        )
        assert ts["api"] in ("new", "legacy")

    def test_no_impossible_template_string_import(self):
        """`template_string` tidak pernah jadi `source` import di JS."""
        import engine
        q = engine._TS_QUERIES["javascript"]
        assert "template_string" not in q, (
            "(import_statement source: (template_string)) impossible — "
            "source import hanya bisa berupa string"
        )

    def test_js_file_yields_symbols(self, tmp_path):
        """File .js sungguhan harus menghasilkan simbol, bukan nol."""
        import engine
        f = tmp_path / "comp.js"
        f.write_text(JS_SOURCE, encoding="utf-8")
        syms = engine.parse_source(f, "javascript")
        names = {s["name"] for s in syms}
        for expected in ("Hello", "named", "arrow", "fexpr", "Widget", "gen", "complex"):
            assert expected in names, f"simbol {expected!r} hilang, dapat: {sorted(names)}"

    def test_js_class_kind_correct(self, tmp_path):
        import engine
        f = tmp_path / "comp.js"
        f.write_text(JS_SOURCE, encoding="utf-8")
        kinds = {s["name"]: s["kind"] for s in engine.parse_source(f, "javascript")}
        assert kinds.get("Widget") == "class", str(kinds.get("Widget"))
        assert kinds.get("Hello") == "function", str(kinds.get("Hello"))

    def test_js_imports_captured(self, tmp_path):
        import engine
        f = tmp_path / "comp.js"
        f.write_text(JS_SOURCE, encoding="utf-8")
        mods = {s["name"] for s in engine.parse_source(f, "javascript")
                if s["kind"] == "import"}
        assert "react" in mods, f"import 'react' hilang, dapat: {sorted(mods)}"
        assert "path" in mods, f"import 'path' hilang, dapat: {sorted(mods)}"

    def test_js_complexity_from_body(self, tmp_path):
        """Complexity harus dari body arrow function, bukan dari teks nama."""
        import engine
        f = tmp_path / "comp.js"
        f.write_text(JS_SOURCE, encoding="utf-8")
        cx = {s["name"]: s["complexity"] for s in engine.parse_source(f, "javascript")}
        assert cx.get("complex", 0) > 1, f"complex={cx.get('complex')} (harusnya >1, punya if/else)"
        assert cx.get("arrow") == 1, f"arrow={cx.get('arrow')} (harusnya 1)"

    @pytest.mark.parametrize("suffix", [".js", ".jsx", ".mjs"])
    def test_all_js_extensions(self, tmp_path, suffix):
        import engine
        f = tmp_path / ("comp" + suffix)
        f.write_text(JS_SOURCE, encoding="utf-8")
        assert len(engine.parse_source(f, "javascript")) > 0, f"{suffix} nol simbol"

    def test_ingest_persists_js_entities(self, tmp_path, monkeypatch):
        """Entitas JS harus benar-benar sampai ke database."""
        import importlib
        import storage
        import engine
        importlib.reload(storage)
        importlib.reload(engine)

        db = tmp_path / "js_v2.db"
        monkeypatch.setattr(storage, "DB_PATH", db)
        monkeypatch.setattr(engine, "DB_PATH", db)
        storage.reset_conn()
        storage.init_db()

        repo = tmp_path / "demojs"
        repo.mkdir()
        (repo / "app.py").write_text("def pyfunc():\n    return 1\n", encoding="utf-8")
        (repo / "comp.js").write_text(JS_SOURCE, encoding="utf-8")

        res = engine.ingest_repository(str(repo))
        assert res["ok"], res
        assert res["stats"]["symbols"] > 0, res["stats"]

        conn = storage.get_conn()
        labels = {r[0] for r in conn.execute(
            "SELECT label FROM entities WHERE kind='symbol'").fetchall()}
        conn.close()
        for n in ("Hello", "Widget", "arrow"):
            assert n in labels, f"entitas {n!r} tidak masuk DB"
        storage.reset_conn()

    def test_ts_failure_is_logged_not_silent(self, caplog):
        """
        Kegagalan tree-sitter harus terlihat di log.

        Issue #47: `except: pass` membuat query rusak hanya terlihat
        sebagai "nol simbol" tanpa jejak apa pun.
        """
        import engine
        # paksa kegagalan: query yang pasti tidak valid
        orig = dict(engine._TS_QUERIES)
        engine._TS_QUERIES["javascript"] = "(this_node_does_not_exist) @x"
        engine._ts_cache.pop("javascript", None)
        engine._ts_unavailable.discard("javascript")
        try:
            with caplog.at_level("WARNING", logger="synapse.engine"):
                assert engine._load_ts_uncached("javascript") is None
            msgs = " ".join(r.getMessage() for r in caplog.records)
            assert "javascript" in msgs, f"tidak ada log, hanya: {msgs[:200]}"
        finally:
            engine._TS_QUERIES.clear()
            engine._TS_QUERIES.update(orig)
            engine._ts_cache.pop("javascript", None)
            engine._ts_unavailable.discard("javascript")


# ===========================================================================
# #46 — approve_operation() harus menolak status terminal
# ===========================================================================

TERMINAL = ("verified", "rolled_back", "failed", "denied")
NON_TERMINAL = ("pending", "approved", "executing", "executed_unverified")


def _mk_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, name TEXT,
                            meta_json TEXT DEFAULT '{}');
        CREATE TABLE edges (id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
                            relationship TEXT, confidence REAL DEFAULT 1.0);
        CREATE TABLE operations (
            id TEXT PRIMARY KEY, tool_name TEXT NOT NULL,
            params_json TEXT DEFAULT '{}', target_node_id TEXT,
            blast_radius TEXT, reversibility_class TEXT,
            status TEXT DEFAULT 'pending', snapshot_ref TEXT, rollback_command TEXT,
            requires_approval INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            executed_at TEXT, verified_at TEXT);
        CREATE TABLE approvals (operation_id TEXT PRIMARY KEY, decision TEXT,
                               decided_at TEXT, note TEXT DEFAULT '');
    """)
    conn.commit()
    conn.close()


@pytest.fixture()
def g(tmp_path, monkeypatch):
    """guardian module dengan DB temporer dan _emit dimock."""
    import importlib
    import database
    import guardian
    db = tmp_path / "g46.db"
    _mk_db(db)
    monkeypatch.setattr(database, "DB_PATH", db)
    monkeypatch.setattr(guardian, "_db_path", lambda: db)
    monkeypatch.setattr(guardian, "_emit", lambda *a, **k: None)
    importlib.reload(guardian)
    guardian._emit = lambda *a, **k: None
    yield guardian, db
    importlib.reload(guardian)


def _add_op(db: Path, status: str, tool="service.restart") -> str:
    oid = f"op-{status}"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO operations (id, tool_name, status, params_json) VALUES (?,?,?,?)",
        (oid, tool, status, '{"service": "x"}'),
    )
    conn.commit()
    conn.close()
    return oid


def _status(db: Path, oid: str) -> str:
    conn = sqlite3.connect(str(db))
    s = conn.execute("SELECT status FROM operations WHERE id=?", (oid,)).fetchone()[0]
    conn.close()
    return s


class TestIssue46TerminalGuard:
    def test_terminal_statuses_constant(self, g):
        guardian, _ = g
        assert set(guardian.TERMINAL_STATUSES) == set(TERMINAL), (
            f"TERMINAL_STATUSES = {sorted(guardian.TERMINAL_STATUSES)}"
        )

    @pytest.mark.parametrize("status", TERMINAL)
    def test_cannot_approve_terminal(self, g, status):
        guardian, db = g
        oid = _add_op(db, status)
        for decision in ("approved", "denied"):
            r = guardian.approve_operation(oid, decision)
            assert r["ok"] is False, f"{status} + {decision} seharusnya ditolak, dapat {r}"
            assert r.get("terminal") is True, f"{status} harus ditandai terminal: {r}"
        assert _status(db, oid) == status, "status berubah padahal ditolak"

    @pytest.mark.parametrize("status", ("pending", "approved"))
    def test_can_approve_approvable(self, g, status):
        """Guard hanya boleh memblokir transisi yang memang tidak sah."""
        guardian, db = g
        oid = _add_op(db, status)
        r = guardian.approve_operation(oid, "approved")
        assert r["ok"] is True, f"{status} harusnya bisa di-approve: {r}"
        assert _status(db, oid) == "approved"

    @pytest.mark.parametrize("status", ("executing", "executed_unverified"))
    def test_cannot_approve_inflight(self, g, status):
        """
        BUG-09: kedua status ini bukan terminal, tapi TIDAK BOLEH di-approve.

        Kalau boleh, approve menulis ulang status jadi 'approved', dan CAS di
        execute_operation() mengizinkan 'approved' - operasi dieksekusi dua
        kali. Test lama justru mengkotbodermi ini sebagai perilaku yang
        diharapkan; sekarang sudah dibalik.
        """
        guardian, db = g
        oid = _add_op(db, status)
        r = guardian.approve_operation(oid, "approved")
        assert r["ok"] is False, f"{status} tidak boleh bisa di-approve: {r}"
        assert r.get("terminal") is False, f"{status} bukan terminal: {r}"
        assert _status(db, oid) == status, "status berubah padahal ditolak"

    def test_double_execution_blocked(self, g):
        """
        Rantai exploit penuh dari issue #46:
          propose -> execute (verified) -> approve (approved) -> execute
        Setelah fix, approve harus ditolak dan execute kedua tidak jalan.
        """
        guardian, db = g
        prop = guardian.propose_operation(
            "service.restart", {"service": "synapse"}, "synapse-svc")
        oid = prop["operation_id"]

        first = guardian.execute_operation(oid)
        assert first["ok"] is True, first
        assert _status(db, oid) == "verified"

        reapprove = guardian.approve_operation(oid, "approved")
        assert reapprove["ok"] is False, (
            f"approve pada operasi 'verified' harus ditolak, dapat {reapprove}"
        )
        assert _status(db, oid) == "verified", "status ter-reset ke approved"

        second = guardian.execute_operation(oid)
        assert second["ok"] is False, (
            f"execute kedua harus ditolak, dapat {second}"
        )
        assert _status(db, oid) == "verified"

    def test_no_approvals_row_written_for_terminal(self, g):
        """Guard harus menolak SEBELUM menulis ke tabel approvals."""
        guardian, db = g
        oid = _add_op(db, "verified")
        guardian.approve_operation(oid, "approved")
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE operation_id=?", (oid,)).fetchone()[0]
        conn.close()
        assert row == 0, f"baris approvals tetap ditulis ({row})"

    def test_approve_nonexistent_still_fails(self, g):
        """Guard baru tidak boleh merusak pesan 'tidak ditemukan'."""
        guardian, _ = g
        r = guardian.approve_operation("does-not-exist", "approved")
        assert r["ok"] is False
        assert "tidak ditemukan" in r["error"], r["error"]

    def test_invalid_decision_still_rejected(self, g):
        guardian, db = g
        oid = _add_op(db, "pending")
        r = guardian.approve_operation(oid, "maybe")
        assert r["ok"] is False
        assert _status(db, oid) == "pending"

    def test_terminal_guard_is_atomic_not_read_then_write(self, g):
        """
        Guard harus ATOMIK, bukan "baca status lalu tulis".

        Versi pertama fix ini pakai SELECT lalu UPDATE terpisah. Itu TOCTOU:
        banyak request bersamaan semuanya membaca status lama, semuanya lolos
        guard, lalu saling menimpa. Diuji: 20 thread (10 approve + 10 deny)
        menghasilkan 19 approve() ok=True, dan operasi yang sudah di-DENY
        bisa berakhir berstatus 'approved' - yaitu denial hilang dan operasi
        bisa dieksekusi.

        Guard yang benar menaruh kondisi status di WHERE sehingga hanya satu
        request yang benar-benar mengubah baris.
        """
        import threading
        import collections

        guardian, db = g
        N = 20
        decisions = ["approved"] * (N // 2) + ["denied"] * (N // 2)
        # Beberapa percobaan: race bersifat probabilistik, jadi satu trial
        # saja kadang tidak menunjukkan apa-apa.
        breached = 0
        for i in range(6):
            oid = f"op-atomic-{i}"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO operations (id, tool_name, status) VALUES (?,?,?)",
                (oid, "service.restart", "pending"))
            conn.commit()
            conn.close()

            ok = collections.Counter()
            lock = threading.Lock()
            barrier = threading.Barrier(N)

            def worker(dec):
                barrier.wait()
                r = guardian.approve_operation(oid, dec)
                with lock:
                    ok[dec] += 1 if r.get("ok") else 0

            threads = [threading.Thread(target=worker, args=(d,)) for d in decisions]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            accepted = ok["approved"] + ok["denied"]
            if accepted >= N:
                breached += 1

        assert breached == 0, (
            f"seorang pun dari {6} percobaan membiarkan semua {N} request "
            f"diterima bersamaan. Guard masih read-then-write (TOCTOU); "
            f"kondisi status harus ada di WHERE agar hanya satu yang menulis."
        )

    def test_denied_stays_denied_under_concurrency(self, g):
        """
        Properti keamanan utama: operasi yang sudah di-DENY tidak boleh
        kembali jadi 'approved' (yang berarti boleh dieksekusi).

        Runner tunggal tidak bisa membuktikan ini - butuh beberapa thread
        yang saling berebut.
        """
        import threading
        import collections

        violations = 0
        for i in range(8):
            guardian, db = g
            oid = f"op-conc-{i}"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO operations (id, tool_name, status) VALUES (?,?,?)",
                (oid, "service.restart", "pending"))
            conn.commit()
            conn.close()

            decisions = ["approved"] * 10 + ["denied"] * 10
            ok = collections.Counter()
            lock = threading.Lock()
            barrier = threading.Barrier(20)

            def worker(dec):
                barrier.wait()
                r = guardian.approve_operation(oid, dec)
                with lock:
                    ok[dec] += 1 if r.get("ok") else 0

            threads = [threading.Thread(target=worker, args=(d,)) for d in decisions]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if ok["denied"] > 0 and _status(db, oid) == "approved":
                violations += 1

        assert violations == 0, (
            f"{violations} trial: deny diterima tapi operasi berakhir 'approved' - "
            f"denial hilang, operasi bisa dieksekusi"
        )
