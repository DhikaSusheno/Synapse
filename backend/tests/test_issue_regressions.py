"""
test_issue_regressions.py — regression test untuk issue backend #31–#36.

Setiap test di sini guarding bug yang SUDAH pernah terjadi. Kalau ada yang
salah lagi, test ini harus gagal — jangan dihapus tanpa alasan.

  #31  database.py get_conn() thread-local tidak pernah di-close
       -> get_conn() dihapus total; tidak boleh muncul kembali.
  #32  cortex.py _sse_subscribers list tanpa lock (race condition)
       -> semua akses harus lewat _sse_lock; queue penuh harus dipangkas.
  #33  cortex.py lazy-rebuild graph duplikat di 5 fungsi
       -> logika rebuild dipusatkan di _get_graph() yang terkunci.
  #34  guardian.py _exec_migration() memecah SQL dengan split(";")
       -> lexer yang menghormati string literal, identifier, dan komentar.
  #35  main.py GET /operations tidak memvalidasi ?status
       -> status jadi Literal; nilai ngawu harus 422, bukan 200 [].
  #36  cortex.py _calc_complexity() menghitung keyword di string/komentar
       -> komputasi harus jalan di atas sumber yang sudah dibersihkan.
"""
import asyncio
import inspect
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ===========================================================================
# #31 — get_conn() tidak boleh kembali ke database.py
# ===========================================================================

class TestIssue31NoGetConnLeak:
    def test_database_py_has_no_get_conn(self):
        """get_conn() di database.py adalah connection leak (issue #31)."""
        import database
        assert not hasattr(database, "get_conn"), (
            "database.py tidak boleh punya get_conn() lagi — thread-local "
            "connection tidak pernah di-close (issue #31). Pakai storage.get_conn()."
        )

    def test_database_py_has_no_close_conn_needed(self):
        """Kalau get_conn dihapus, tidak perlu close_conneither."""
        import database
        assert not hasattr(database, "close_conn")

    def test_storage_get_conn_is_the_single_source(self):
        """storage.py yang memegang thread-local connection sekarang."""
        import storage
        assert hasattr(storage, "get_conn")
        assert hasattr(storage, "reset_conn"), (
            "test butuh reset_conn() untuk melepas thread-local connection"
        )


# ===========================================================================
# #32 — _sse_subscribers harus thread-safe
# ===========================================================================

@pytest.fixture()
def clean_sse():
    """Bersihkan subscriber + event loop sebelum & sesudah test."""
    import engine
    with engine._sse_lock:
        engine._sse_subscribers.clear()
    engine.set_event_loop(None)
    yield engine
    with engine._sse_lock:
        engine._sse_subscribers.clear()
    engine.set_event_loop(None)


class TestIssue32SseThreadSafety:
    def test_all_list_access_under_lock(self, clean_sse):
        """Setiap akses ke _sse_subscribers harus di dalam _sse_lock."""
        src = inspect.getsource(clean_sse)
        body = src[src.index("def _emit("):src.index("def subscribe_sse(")]
        touching = [l for l in body.splitlines() if "_sse_subscribers" in l]
        assert touching, "blok _emit() tidak menyentuh _sse_subscribers?"
        assert "_sse_lock" in body, "list diakses tanpa _sse_lock"

    def test_concurrent_emit_and_churn(self, clean_sse):
        """6 thread emit + 2 thread subscribe/unsubscribe bersamaan."""
        qs = [clean_sse.subscribe_sse() for _ in range(20)]
        errors = []

        def emitter(i):
            try:
                for _ in range(200):
                    clean_sse._emit("t", {"i": i})
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        def churner():
            try:
                for _ in range(200):
                    if qs:
                        clean_sse.unsubscribe_sse(qs[0])
                        clean_sse.subscribe_sse()
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=emitter, args=(i,)) for i in range(6)]
        threads += [threading.Thread(target=churner) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"race condition: {errors[:3]}"

    def test_full_queue_is_pruned_not_orphan(self, clean_sse):
        """
        Queue yang PENUH harus ditandai mati lalu dibuang.

        Ini residual yang tertinggal dari fix #32: try/except di _emit()
        tidak menangkap QueueFull, karena call_soon_threadsafe()
        menjadwalkan callback — exception-nya muncul di thread event loop.
        Akibatnya 3 exception liar + subscriber yatim selamanya.
        """
        full = asyncio.Queue(maxsize=2)
        full.synapse_dead = False
        healthy = clean_sse.subscribe_sse()
        with clean_sse._sse_lock:
            clean_sse._sse_subscribers.append(full)
        full.put_nowait("a")
        full.put_nowait("b")
        assert full.full()

        # emit langsung (tanpa loop) — jalur paling sederhana
        clean_sse._emit("flood", {"i": 0})
        assert full.synapse_dead is True, "queue penuh harus ditandai mati"

        clean_sse._emit("flood", {"i": 1})
        assert full not in clean_sse._sse_subscribers, (
            "queue penuh harus dibuang dari _sse_subscribers"
        )
        assert healthy in clean_sse._sse_subscribers, (
            "subscriber yang sehat tidak boleh ikut terbuang"
        )

    def test_queue_full_inside_callback_does_not_raise(self, clean_sse):
        """QueueFull di dalam callback event loop tidak boleh jadi exception liar."""
        caught = []
        loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(loop)
            loop.set_exception_handler(lambda l, ctx: caught.append(ctx.get("message")))
            loop.call_soon(loop.stop)
            loop.run_forever()

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.2)
        clean_sse.set_event_loop(loop)

        full = asyncio.Queue(maxsize=1)
        full.synapse_dead = False
        full.put_nowait("x")
        with clean_sse._sse_lock:
            clean_sse._sse_subscribers.append(full)

        for i in range(3):
            clean_sse._emit("flood", {"i": i})
        time.sleep(0.4)
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()

        assert not caught, f"exception liar di event loop: {caught}"


# ===========================================================================
# #33 — rebuild graph hanya di _get_graph()
# ===========================================================================

class TestIssue33GraphRebuildCentralized:
    def test_no_lazy_rebuild_pattern_in_functions(self, clean_sse):
        """Pola 'if len(g.nodes) == 0: rebuild' tidak boleh ada di functon mana pun."""
        import engine
        src = inspect.getsource(engine)
        for pattern in ("len(g.nodes) == 0", "len(_graph.nodes) == 0"):
            assert pattern not in src, (
                f"'{pattern}' masih ada — rebuild harus dipusatkan di _get_graph() "
                "(issue #33: overwrite graph valid saat concurrent)"
            )

    def test_get_graph_is_defined_once_and_locked(self, clean_sse):
        import engine
        src = inspect.getsource(engine)
        assert src.count("def _get_graph()") == 1, "_get_graph() harus tunggal"
        body = inspect.getsource(engine._get_graph)
        assert "_graph_lock" in body, "_get_graph() harus memakai _graph_lock"

    @pytest.mark.parametrize(
        "fn", ["ask_about", "health_report", "trace_connection",
               "propose_refactor", "rank_complexity"]
    )
    def test_public_fns_do_not_rebuild(self, clean_sse, fn):
        """5 fungsi yang disebut issue #33 tidak boleh rebuild sendiri."""
        import engine
        body = inspect.getsource(getattr(engine, fn))
        assert "_rebuild_graph" not in body, f"{fn}() rebuild sendiri"
        assert "_graph_lock" not in body, f"{fn}() accessing _graph langsung"

    def test_concurrent_readers_see_same_graph(self, clean_sse):
        """16 thread reader _get_graph() bersamaan harus konsisten."""
        import engine
        seen, errors = [], []

        def reader():
            try:
                for _ in range(30):
                    seen.append(len(engine._get_graph().nodes))
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=reader) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"reader error: {errors[:3]}"
        assert len(set(seen)) == 1, f"graph terlihat berbeda: {set(seen)}"


# ===========================================================================
# #34 — SQL splitting harus lexer, bukan split(";")
# ===========================================================================

@pytest.fixture()
def guardian_fresh():
    """guardian module terkini (conftest fixtures me-reload modul ini)."""
    import guardian
    return guardian


class TestIssue34SqlSplitting:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            # inti issue: ';' di dalam string literal
            ("INSERT INTO c VALUES ('k', 'v;w;x');",
             ["INSERT INTO c VALUES ('k', 'v;w;x')"]),
            ("INSERT INTO t VALUES ('a;b'); INSERT INTO t VALUES ('c;d');",
             ["INSERT INTO t VALUES ('a;b')", "INSERT INTO t VALUES ('c;d')"]),
            # escape kutip di dalam string
            ("INSERT INTO t VALUES ('it''s;fine');",
             ["INSERT INTO t VALUES ('it''s;fine')"]),
            # identifier bertanda kutip
            ('CREATE TABLE "my;table" (a INT);', ['CREATE TABLE "my;table" (a INT)']),
            ("CREATE TABLE `my;table` (a INT);", ["CREATE TABLE `my;table` (a INT)"]),
            ("SELECT a FROM [my;table];", ["SELECT a FROM [my;table]"]),
            ('SELECT "od""d;name" FROM t;', ['SELECT "od""d;name" FROM t']),
            # komentar
            ("SELECT 1; -- ini; komentar\nSELECT 2;", ["SELECT 1", "SELECT 2"]),
            ("SELECT /* a;b */ 1; SELECT 2;", ["SELECT  1", "SELECT 2"]),
            ("SELECT 1; /* unterminated ;", ["SELECT 1"]),
            # bentuk tak lazim
            ("SELECT 1", ["SELECT 1"]),
            ("SELECT 1;;", ["SELECT 1"]),
            (";;;", []),
            ("", []),
            ("   \n\t ", []),
        ],
    )
    def test_split_respects_quoting_and_comments(self, guardian_fresh, sql, expected):
        assert guardian_fresh._split_sql_statements(sql) == expected

    def test_naive_split_would_corrupt(self, guardian_fresh):
        """Buktikan split(";") merusak — justifikasi, bukan over-engineering."""
        sql = "INSERT INTO t VALUES ('a', 'x;1'); INSERT INTO t VALUES ('b', 'y;2');"
        naive = sql.split(";")
        assert not any("'x;1'" in frag for frag in naive), (
            "split(\";\") ternyata tidak merusak pada kasus ini — test tidak relevan"
        )
        assert len(guardian_fresh._split_sql_statements(sql)) == 2

    def test_exec_migration_roundtrip_preserves_semicolons(self, guardian_fresh, tmp_path):
        """Nilai berisi ';' harus tersimpan utuh — ini regresi data corruption."""
        db = tmp_path / "m.db"
        sql = (
            "CREATE TABLE cfg (k TEXT, v TEXT);\n"
            "INSERT INTO cfg VALUES ('a', 'x;1');\n"
            "INSERT INTO cfg VALUES ('b', 'y;2'); -- trailing; comment\n"
            "UPDATE cfg SET v = 'p;q' WHERE k = 'a';"
        )
        result = guardian_fresh._exec_migration({"sql": sql, "db_path": str(db)})
        assert result[0], f"migration harus sukses: {result[1]}"

        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT k, v FROM cfg ORDER BY k").fetchall()
        conn.close()
        assert rows == [("a", "p;q"), ("b", "y;2")], f"nilai ; korup: {rows}"

    def test_exec_migration_still_rolls_back(self, guardian_fresh, tmp_path):
        """BUG-B tidak boleh regresi: statement gagal -> tidak ada partial commit."""
        db = tmp_path / "m2.db"
        guardian_fresh._exec_migration({"sql": "CREATE TABLE ok (a INT);", "db_path": str(db)})
        result = guardian_fresh._exec_migration({
            "sql": "INSERT INTO ok VALUES (1); INSERT INTO nope VALUES (2);",
            "db_path": str(db),
        })
        assert not result[0], "migration dengan statement salah harus gagal"
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM ok").fetchone()[0]
        conn.close()
        assert n == 0, f"partial commit terdeteksi: {n} baris"

    def test_exec_migration_rejects_empty(self, guardian_fresh, tmp_path):
        result = guardian_fresh._exec_migration(
            {"sql": "  ;;  ", "db_path": str(tmp_path / "m3.db")}
        )
        assert result[0] is False


# ===========================================================================
# #35 — ?status harus divalidasi
# ===========================================================================

VALID_STATUSES = [
    "pending", "approved", "executing", "executed_unverified",
    "verified", "failed", "rolled_back", "denied",
]


@pytest.fixture()
def ops_client(tmp_path, monkeypatch):
    """TestClient dengan DB temporer yang punya tabel operations."""
    from fastapi.testclient import TestClient
    import database
    import main

    db_file = tmp_path / "ops.db"
    conn = sqlite3.connect(str(db_file))
    # `edges` wajib ada: /operations (main.py, blok conflicts) men-query
    # edges dengan relationship='CONFLICTS_WITH' — bukan cuma operations.
    conn.executescript(
        """
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT,
            meta_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE operations (
            id TEXT PRIMARY KEY,
            tool_name TEXT NOT NULL,
            params_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute(
        "INSERT INTO operations (id, tool_name, status) VALUES ('o1', 'service.restart', 'pending')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(main, "DB_PATH", str(db_file))
    with TestClient(main.app) as c:
        yield c


class TestIssue35StatusValidation:
    @pytest.mark.parametrize("status", VALID_STATUSES)
    def test_valid_status_accepted(self, ops_client, status):
        r = ops_client.get("/operations", params={"status": status})
        assert r.status_code == 200, f"?status={status} ditolak: {r.text[:120]}"

    def test_no_status_accepted(self, ops_client):
        assert ops_client.get("/operations").status_code == 200

    @pytest.mark.parametrize("bad", [
        "INVALID_STATUS", "pendng", "PENDING", "anything", "hacked",
        "backdoor", "pending ", "approved; DROP TABLE operations",
    ])
    def test_invalid_status_rejected(self, ops_client, bad):
        """
        Sebelumnya semua nilai di atas dijawab 200 [] — developer tidak bisa
        bedakan "filter tidak cocok" dari "salah ketik" (issue #35).
        """
        r = ops_client.get("/operations", params={"status": bad})
        assert r.status_code == 422, f"?status={bad!r} seharusnya 422, dapat {r.status_code}"

    def test_error_message_lists_valid_values(self, ops_client):
        r = ops_client.get("/operations", params={"status": "pendng"})
        assert "pendng" in r.text
        assert "executed_unverified" in r.text, "pesan harus menyebut nilai yang diizinkan"

    def test_valid_status_actually_filters(self, ops_client):
        """Validasi tidak boleh damaging — filter tetap benar-benar jalan."""
        assert len(ops_client.get("/operations", params={"status": "pending"}).json()) == 1
        assert len(ops_client.get("/operations", params={"status": "failed"}).json()) == 0

    def test_frontend_status_options_all_valid(self, ops_client):
        """STATUS_OPTIONS di frontend/app/page.tsx harus tetap diterima."""
        for s in ["pending", "approved", "executing", "verified",
                  "failed", "rolled_back", "denied"]:
            r = ops_client.get("/operations", params={"status": s, "limit": 50})
            assert r.status_code == 200, f"frontend ?status={s} pecah: {r.status_code}"

    def test_openapi_documents_enum(self, ops_client):
        spec = ops_client.get("/openapi.json").json()
        params = spec["paths"]["/operations"]["get"]["parameters"]
        status_param = next(p for p in params if p["name"] == "status")
        schema = status_param.get("schema", {})
        enum = schema.get("enum")
        if enum is None and "anyOf" in schema:
            enum = next((a.get("enum") for a in schema["anyOf"] if "enum" in a), None)
        assert enum is not None, f"tidak ada enum di OpenAPI: {schema}"
        assert sorted(enum) == sorted(VALID_STATUSES)

    @pytest.mark.parametrize("limit", [0, 101, "abc"])
    def test_limit_validation_intact(self, ops_client, limit):
        assert ops_client.get("/operations", params={"limit": limit}).status_code == 422


# ===========================================================================
# #36 — complexity tidak boleh menghitung string & komentar
# ===========================================================================

class TestIssue36ComplexityIgnoresNoise:
    def test_keywords_in_docstring_not_counted(self):
        """Docstring berisi if/for/everything tidak boleh menginflasi skor."""
        import engine
        noisy = '''
def my_func():
    """
    This function handles the case where if the user
    is logged in and or has permission, for each item...
    """
    # if this is true, or that is true, for all cases
    x = "if you and I or else for each while..."
    return x
'''
        assert engine.calc_complexity(noisy, "python") == 1, (
            "fungsi tanpa branch harus complexity 1, bukan "
            f"{engine.calc_complexity(noisy, 'python')}"
        )

    def test_real_branches_still_counted(self):
        """Branch asli harus tetap terhitung — jangan under-count."""
        import engine
        real = '''
def branchy(x):
    if x:
        return 1
    elif x == 2:
        return 2
    else:
        return 3
'''
        assert engine.calc_complexity(real, "python") >= 3, (
            "branch if/elif/else harus terhitung, dapat "
            f"{engine.calc_complexity(real, 'python')}"
        )

    def test_loops_and_boolean_ops_counted(self):
        import engine
        src = '''
def f(items):
    total = 0
    for i in items:
        if i and i > 1:
            total += 1
    return total
'''
        assert engine.calc_complexity(src, "python") >= 3

    def test_empty_source(self):
        import engine
        assert engine.calc_complexity("", "python") == 1
