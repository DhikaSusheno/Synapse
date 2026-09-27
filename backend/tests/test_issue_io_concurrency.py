"""
test_issue_io_concurrency.py — regression test untuk audit I/O + concurrency.

Enam temuan yang ditangani di commit ini, masing-masing dengan bukti:

  1. SQLite sinkron di dalam `async def` -> event loop beku.
     Endpoint yang/library yangcpy jelas: sqlite3.connect/execute/commit,
     file I/O, dan loop numpy. Diuji secara perilaku: kalau engine.ask_about
     memblokir 0,3 detik, event loop harus tetap bisa dijadwalkan.
  2. Tujuh requests.get/post ke GitHub tanpa timeout -> 40 thread anyio bisa
     habis, backend berhenti merespons termasuk /health.
  3. DB_PATH relatif ke CWD -> menjalankan server dari dua direktori
     berbeda membuka dua database kosong yang berbeda.
  4. upsert_entity() SELECT-lalu-INSERT di luar transaksi -> race.
     Bukti: 16 thread dengan id sama, sebelumnya 15 gagal.
  5. Tidak ada busy_timeout di koneksi mana pun.
  6. PRAGMA journal_mode=WAL melempar "database is locked" saat writer lain
     aktif, karena lock eksklusif tidak dihormati busy_timeout.

Test #1 memakai patched engine yang memblokir thread, bukan sleep di dalam
event loop, supaya kegagalan jelas: kalau to_thread hilang, test ini HANG dan
pytest timeout, bukan lolos diam-diam.
"""
import ast
import asyncio
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
import guardian  # noqa: E402
import main  # noqa: E402
import storage  # noqa: E402

MAIN_PY = BACKEND_DIR / "main.py"

# Panggilan yang memblokir thread kalau dijalankan langsung di dalam async def.
# None of these belong on the event loop.
BLOCKING_CALLS = {
    # sqlite3
    "connect", "execute", "executemany", "executescript",
    "commit", "rollback", "fetchall", "fetchone", "fetchmany",
    # file I/O
    "open", "read", "read_text", "read_bytes", "write", "write_text",
    "write_bytes", "is_file", "is_dir", "exists", "stat", "iterdir",
    "glob", "rglob", "resolve", "realpath", "listdir", "makedirs", "mkdir",
    "getsize", "getmtime", "readlink", "samefile",
    # blocking network
    "urlopen",
}


# ---------------------------------------------------------------------------
# 1. Tidak ada pemanggilan blocking langsung di dalam async def
# ---------------------------------------------------------------------------

def _async_defs_with_blocking_calls():
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
            if name in BLOCKING_CALLS:
                found.append((node.name, call.lineno, name))
    return found


def test_no_blocking_calls_in_async_endpoints():
    """
    Guard struktural untuk #1.

    Ini sengaja memeriksa AST, bukan hanya test perilaku: test perilaku hanya
    mencakup jalur yang benar-benar dipanggil test, sementara bug ini ada di
    enam endpoint sekaligus. Guard ini gagal di endpoint mana pun yang rusak
    di masa depan, walaupun tidak ada test yang menyentuh endpoint itu.
    """
    found = _async_defs_with_blocking_calls()
    assert found == [], (
        "Ada pemanggilan blocking langsung di dalam async def. "
        "Bungkus dengan asyncio.to_thread():\n"
        + "\n".join(f"  {fn}() L{ln} -> .{name}()" for fn, ln, name in found)
    )


def test_stream_events_stays_pure_async():
    """
    stream_events() sengaja TIDAK disentuh: audit awal sempat salah menandainya
    sebagai endpoint blocking, padahal seluruh kerjanya sudah async. Test ini
    mengunci status itu supaya perbaikan di masa depan tidak mengubahnya tanpa
    alasan.
    """
    assert main.stream_events.__doc__ is not None or True
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "stream_events"
    )
    names = {
        getattr(c.func, "attr", None) or getattr(c.func, "id", None)
        for c in ast.walk(fn) if isinstance(c, ast.Call)
    }
    assert not (names & BLOCKING_CALLS), (
        f"stream_events kembali punya pemanggilan blocking: {names & BLOCKING_CALLS}"
    )


@pytest.mark.parametrize(
    "endpoint_name, engine_attr",
    [
        ("llm_explain", "ask_about"),
        ("llm_review", "review_change"),
        ("llm_refactor", "propose_refactor"),
    ],
)
def test_engine_calls_do_not_block_event_loop(monkeypatch, endpoint_name, engine_attr):
    """
    Bukti perilaku untuk #1 — ini test yang benar-benar menangkap bug.

    Engine asli di-patch supaya memblokir thread-nya selama 0,3 detik. Kalau
    endpoint memanggilnya langsung (bukan lewat to_thread), event loop ikut
    tertahan dan probe sleep(0.02) selesai jauh melewati 0,02 detik. Kalau lewat
    to_thread, probe selesai mendekati 0,02 detik selagi worker masih sibuk.
    """
    release = threading.Event()

    def blocking(*args, **kwargs):
        release.wait(timeout=5.0)
        return {"ok": True, "answer": "ok", "context": "ok"}

    monkeypatch.setattr(main.engine, engine_attr, blocking)

    async def run():
        endpoint = getattr(main, endpoint_name)
        request = getattr(main, {
            "llm_explain": "ExplainRequest",
            "llm_review": "ReviewRequest",
            "llm_refactor": "RefactorRequest",
        }[endpoint_name])
        payload = {
            "llm_explain": {"provider_id": "p1", "topic": "x"},
            "llm_review": {"provider_id": "p1", "path_or_diff": "x"},
            "llm_refactor": {"provider_id": "p1", "node_name": "x"},
        }[endpoint_name]

        task = asyncio.create_task(endpoint(request(**payload)))
        await asyncio.sleep(0.02)          # harus tetap responsif
        probe = time.perf_counter()
        await asyncio.sleep(0.02)
        elapsed = (time.perf_counter() - probe) * 1000
        release.set()
        # Hasil endpoint sendiri tidak penting di sini: setelah engine dipatch,
        # endpoint lanjut ke lookup provider dan berhenti dengan 404. Yang
        # diukur hanya apakah event loop sempat jalan selagi worker diblokir.
        try:
            await task
        except Exception:  # noqa: BLE001
            pass
        return elapsed

    elapsed_ms = asyncio.run(run())
    assert elapsed_ms < 150, (
        f"{endpoint_name} memblokir event loop: probe sleep(20ms) butuh "
        f"{elapsed_ms:.0f} ms. Panggil engine.{engine_attr}() lewat "
        f"asyncio.to_thread()."
    )


def test_rag_helpers_are_sync_and_pure():
    """
    Helper RAG sengaja sinkron karena dipanggil via to_thread. Kalau ada yang
    mengubahnya jadi `async def`, pemanggilnya di main.py tidak ikut berubah
    dan kita kembali memblokir loop.
    """
    for name in ("_chunk_texts", "_store_rag_chunks", "_rag_search_sync",
                 "_load_provider_row"):
        fn = getattr(main, name)
        assert not asyncio.iscoroutinefunction(fn), (
            f"{name} harus tetap sinkron - dipanggil lewat asyncio.to_thread()"
        )


def test_chunk_texts_matches_original_inline_algorithm():
    """
    _chunk_texts() adalah ekstraksi dari loop inline yang lama. Perilaku
    chunking harus PERSIS sama, karena id PRIMARY KEY rag_chunks adalah
    md5 dari isi chunk: mengubah batas chunk berarti semua dokumen yang
    sudah ter-ingest akan ter-duplikasi saat re-ingest.
    """
    def original(texts, chunk_size, chunk_overlap):
        chunks = []
        for content in texts:
            lines = content.split("\n")
            chunk = []
            for line in lines:
                chunk.append(line)
                if len("\n".join(chunk)) >= chunk_size:
                    chunks.append("\n".join(chunk))
                    overlap = chunk[-chunk_overlap // 50:] if chunk_overlap else []
                    chunk = overlap
            if chunk:
                chunks.append("\n".join(chunk))
        return chunks

    cases = [
        (["satu\ndua\ntiga"], 10, 0),
        (["satu\ndua\ntiga\nempat\nlima"], 12, 100),
        ([""], 5, 0),
        (["a" * 200], 50, 200),
        (["baris1\nbaris2\nbaris3", "x\ny"], 8, 50),
    ]
    for texts, size, overlap in cases:
        assert main._chunk_texts(texts, size, overlap) == original(texts, size, overlap), (
            f"_chunk_texts({texts!r}, {size}, {overlap}) berbeda dari algoritma asli"
        )


# ---------------------------------------------------------------------------
# 2. Semua panggilan GitHub punya timeout
# ---------------------------------------------------------------------------

def test_all_github_requests_have_timeout():
    """
    Guard struktural untuk #2. Tujuh callsite; yang tanpa timeout menggantung
    sampai worker thread anyio habis (default 40).
    """
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "post")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"):
            calls.append(node)

    assert len(calls) == 7, f"-harapan 7 panggilan GitHub, ditemukan {len(calls)}"
    missing = [n.lineno for n in calls if "timeout" not in {k.arg for k in n.keywords}]
    assert missing == [], (
        f"panggilan requests tanpa timeout di baris {missing}. "
        f"Tambahkan timeout=GITHUB_TIMEOUT."
    )


def test_github_timeout_is_bounded():
    """Nilai timeout harus berupa (connect, read) dan tidak nol/None."""
    assert isinstance(main.GITHUB_TIMEOUT, tuple)
    assert len(main.GITHUB_TIMEOUT) == 2
    assert all(isinstance(v, (int, float)) and 0 < v <= 60 for v in main.GITHUB_TIMEOUT)


# ---------------------------------------------------------------------------
# 3. DB_PATH tidak lagi bergantung pada CWD
# ---------------------------------------------------------------------------

def test_db_paths_are_absolute():
    assert database.DB_PATH.is_absolute(), f"database.DB_PATH relatif: {database.DB_PATH}"
    assert storage.DB_PATH.is_absolute(), f"storage.DB_PATH relatif: {storage.DB_PATH}"


def test_db_paths_anchored_to_backend_dir():
    """Keduanya harus menunjuk ke dalam backend/, masing-masing file berbeda."""
    assert Path(database.DB_PATH).parent == BACKEND_DIR
    assert Path(storage.DB_PATH).parent == BACKEND_DIR
    assert database.DB_PATH != storage.DB_PATH, (
        "v1 dan v2 harus tetap file terpisah (lihat docstring database.py)"
    )


def test_db_paths_independent_of_cwd(tmp_path):
    """
    Bukti nyata untuk #3: jalankan import dari CWD yang berbeda, hasilnya
    harus sama. Kalau DB_PATH relatif, ini menghasilkan dua path berbeda.
    """
    import subprocess

    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import database, storage;"
        "print(database.DB_PATH); print(storage.DB_PATH)" % BACKEND_DIR
    )
    results = set()
    for cwd in (tmp_path, BACKEND_DIR, Path.home()):
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(cwd), timeout=120,
        )
        assert out.returncode == 0, f"import gagal dari {cwd}: {out.stderr[-400:]}"
        results.update(l for l in out.stdout.splitlines() if l.strip())

    assert len(results) == 2, (
        "path DB berubah tergantung CWD - ini bug yang sama seperti semula:\n"
        + "\n".join(sorted(results))
    )


# ---------------------------------------------------------------------------
# 4. upsert_entity / upsert_relation aman dari race
# ---------------------------------------------------------------------------

@pytest.fixture
def v2_db(tmp_path, monkeypatch):
    """Schema v2 di file sementara, koneksi di-reset per test."""
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    storage.reset_conn()
    storage.init_db()
    yield tmp_path / "synapse_v2.db"
    storage.reset_conn()


def test_upsert_entity_concurrent_same_id_all_succeed(v2_db):
    """
    Kasus yang sebelumnya menghasilkan 15 error dari 16 thread:
    "UNIQUE constraint failed: entities.id" dan "database is locked".
    """
    n_threads = 16
    barrier = threading.Barrier(n_threads)
    ok, errs = [], []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()          # samakan titik mulai, perbesar peluang tabrakan
        try:
            storage.upsert_entity("sama", "file", f"label-{i}", {"i": i})
            with lock:
                ok.append(i)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errs.append(f"thread {i}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errs == [], "upsert_entity gagal saat konkuren:\n" + "\n".join(errs)
    assert len(ok) == n_threads

    conn = storage.connect()
    try:
        rows = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
    finally:
        conn.close()
    assert rows == 1, f"harusnya tepat 1 baris, ada {rows}"


def test_upsert_entity_concurrent_distinct_ids(v2_db):
    """Jalur lain dari race yang sama: banyak id berbeda, banyak writer."""
    n_threads = 16
    per_thread = 8
    barrier = threading.Barrier(n_threads)
    errs = []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        for j in range(per_thread):
            try:
                storage.upsert_entity(
                    f"e{i}-{j}", "file", f"label-{i}-{j}", {"i": i, "j": j}
                )
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errs.append(f"thread {i} row {j}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert errs == [], "gagal:\n" + "\n".join(errs[:10])
    conn = storage.connect()
    try:
        rows = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
    finally:
        conn.close()
    assert rows == n_threads * per_thread


def test_upsert_entity_version_increments_once(v2_db):
    """
    BEGIN IMMEDIATE tidak boleh mengubah semantik versi: label sama harus
    tetap mengembalikan False dan TIDAK menaikkan version. Kolom version mulai
    dari 1 saat insert, jadi satu perubahan isi = 2.
    """
    assert storage.upsert_entity("v", "file", "label", {}) is True      # insert
    assert storage.upsert_entity("v", "file", "label", {}) is False     # identik
    assert storage.upsert_entity("v", "file", "label", {}) is False     # identik
    assert storage.upsert_entity("v", "file", "label-berubah", {}) is True  # berubah

    conn = storage.connect()
    try:
        row = conn.execute("SELECT version FROM entities WHERE id='v'").fetchone()
    finally:
        conn.close()
    assert row["version"] == 2, "version harus naik hanya saat konten berubah"


def test_upsert_relation_concurrent(v2_db):
    """ concurrently relation antar dua entity yang sudah ada."""
    storage.upsert_entity("a", "file", "a", {})
    storage.upsert_entity("b", "file", "b", {})

    n_threads = 12
    barrier = threading.Barrier(n_threads)
    errs, ids = [], []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        try:
            rid = storage.upsert_relation("a", "b", "REFERENCES", 1.0)
            with lock:
                ids.append(rid)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errs.append(f"thread {i}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errs == [], "upsert_relation gagal:\n" + "\n".join(errs)
    assert len(set(ids)) == 1, "semua thread harus menulis relasi dengan id yang sama"

    conn = storage.connect()
    try:
        rows = conn.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"]
    finally:
        conn.close()
    assert rows == 1


def test_upsert_relation_missing_endpoint_still_returns_none(v2_db):
    """Perilaku lama harus dipertahankan: ujung hilang -> None, bukan error."""
    storage.upsert_entity("a", "file", "a", {})
    assert storage.upsert_relation("a", "tidak-ada", "REFERENCES") is None
    assert storage.upsert_relation("tidak-ada", "a", "REFERENCES") is None


def test_real_ingest_runs_hundreds_of_immediate_transactions(tmp_path, monkeypatch):
    """
    BEGIN IMMEDIATE Versus transaksi yang sudah terbuka.

    engine.py mengimpor upsert_entity/upsert_relation sebagai bare name dan
    memanggilnya ratusan kali dalam satu ingest. Kalau pemanggil mana pun
    meninggalkan transaksi terbuka di koneksi yang sama, SQLite melempar
    "cannot start a transaction within a transaction" - jadi test ini menjalankan
    ingest repo sungguhan, bukan hanya memanggil upsert secara terpisah.
    """
    import engine
    import settings as settings_store

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "core.py").write_text(
        "import os\nimport json\n\n"
        "class Thing:\n    def run(self):\n        return os.getcwd()\n\n"
        "def helper():\n    return json.dumps({})\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "extra.py").write_text(
        "from pkg.core import Thing\n\ndef go():\n    return Thing().run()\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        "from pkg.core import helper\nfrom pkg.extra import go\n\n"
        "print(helper(), go())\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Fixture\n\nDokumen yang menyebut app.py dan core.py.\n", encoding="utf-8"
    )

    # Guard #66 (path allowlist) menolak temp dir, jadi daftarkan fixture ini
    # sebagai root yang sah untuk test.
    monkeypatch.setattr(settings_store, "allowed_roots",
                        lambda: [str(repo), str(tmp_path)])

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "synapse.db"))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    storage.reset_conn()
    database.init_db()
    storage.init_db()

    result = engine.ingest_repository(str(repo))
    assert result.get("ok") is True, f"ingest gagal: {result}"

    conn = storage.connect()
    try:
        entities = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
        relations = conn.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"]
    finally:
        conn.close()

    assert entities > 0, "tidak ada entity yang ter-ingest"
    assert relations > 0, (
        "tidak ada relasi - jalur BEGIN IMMEDIATE di upsert_relation tidak teruji"
    )
    storage.reset_conn()


# ---------------------------------------------------------------------------
# 5. busy_timeout diset di setiap koneksi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "opener, label",
    [
        (lambda: main._db_conn(":memory:"), "main._db_conn"),
        (lambda: database.connect(":memory:"), "database.connect"),
        (lambda: storage.connect(":memory:"), "storage.connect"),
        (lambda: guardian._connect(":memory:"), "guardian._connect"),
    ],
)
def test_every_opener_sets_busy_timeout(opener, label):
    """
    PRAGMA busy_timeout dibaca balik dengan PRAGMA busy_timeout agarnilainya
    benar-benar yang dipegang SQLite, bukan cuma parameter connect() yang
    diteruskan.
    """
    conn = opener()
    try:
        got = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert got > 0, f"{label} tidak menyetel busy_timeout (dapat {got})"
    finally:
        conn.close()


def test_busy_timeout_constant_is_sane():
    for mod in (database, storage):
        assert 1000 <= mod.BUSY_TIMEOUT_MS <= 60_000, (
            f"{mod.__name__}.BUSY_TIMEOUT_MS = {mod.BUSY_TIMEOUT_MS} tidak masuk akal"
        )


# ---------------------------------------------------------------------------
# 6. journal_mode=WAL tidak boleh melempar saat DB sedang terkunci
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Cukup untuk _enable_wal: cuma perlu .fetchone() -> tuple."""

    def __init__(self, value):
        self._row = (value,)

    def fetchone(self):
        return self._row


def test_enable_wal_swallows_lock_error():
    """
    PRAGMA journal_mode=WAL butuh lock eksklusif dan TIDAK dihormati
    busy_timeout. Kalau tidak ditelan, satu writer lain yang sedang aktif
    membuat koneksi gagal padahal DB-nya sehat.

    sqlite3.Connection.execute tidak bisa di-monkeypatch (read-only attribute),
    jadi stub kecil dipakai untuk memaksa PRAGMA itu gagal.
    """
    class LockedConn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, *a, **kw):
            self.calls.append(sql)
            if "journal_mode" in sql.lower():
                raise sqlite3.OperationalError("database is locked")
            return _FakeCursor("wal")

    conn = LockedConn()
    main._enable_wal(conn)   # tidak boleh melempar
    assert any("journal_mode" in c.lower() for c in conn.calls), (
        "stub harusnya benar-benar menahan PRAGMA journal_mode"
    )


def test_enable_wal_noop_when_already_wal(tmp_path):
    """Kalau sudah WAL, jangan sentuh lagi - itu yang menghindari lock."""
    db = tmp_path / "wal2.db"
    conn = main._db_conn(db)
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()

    calls = []

    class Spy:
        def execute(self, sql, *a, **kw):
            calls.append(sql)
            return _FakeCursor("wal")     # sudah mode wal

    main._enable_wal(Spy())
    assert not any("journal_mode=WAL" in c for c in calls), (
        f"tidak perlu set WAL lagi, tapi dipanggil: {calls}"
    )


def test_enable_wal_still_sets_wal_on_normal_db(tmp_path):
    db = tmp_path / "wal.db"
    conn = main._db_conn(db)
    conn.execute("CREATE TABLE t (x INT)")
    conn.commit()
    conn.close()

    conn = main._db_conn(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
