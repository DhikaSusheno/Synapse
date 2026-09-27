"""
test_issue_rag_limits.py — regression test untuk amplifikasi request keluar
di /api/rag/ingest.

BUG: RAGIngestRequest tidak punya satu pun batas validasi, dan rag_ingest
mengirim SATU request HTTP keluar per chunk, secara berurutan. chunk_size
diisi 0 atau negatif membuat _chunk_texts() memotong setiap baris file menjadi
chunk sendiri, jadi satu request masuk menghasilkan ratusan request keluar.

Bukti sebelum fix: file 200 baris dengan chunk_size=1 menghasilkan 201
request HTTP keluar. Dan karena files tidak berbatas, satu POST bisa
menahan backend sambil menghabiskan kuota API.

Perbaikan:
  - files dibatasi MAX_INGEST_FILES
  - chunk_size ge=1, le=MAX_CHUNK_SIZE
  - chunk_overlap ge=0 dan harus lebih kecil dari chunk_size
  - panjang tiap entri files dibatasi
  - jumlah chunk hasil pemotongan dibatasi MAX_INGEST_CHUNKS, sebagai
    pengaman kedua yang tidak bergantung pada validasi input

Yang tidak berubah: default aplikasi (chunk_size=1000, chunk_overlap=200)
dan file berukuran normal. Test di bawah mengunci itu.
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402
import main  # noqa: E402
import settings as settings_store  # noqa: E402
from pydantic import ValidationError  # noqa: E402

TOKEN = "test-token-0123456789abcdef"


def _ingest(**kw):
    data = {"provider_id": "openai:x", "files": ["a.py"], "chunk_size": 1000,
            "chunk_overlap": 200}
    data.update(kw)
    return main.RAGIngestRequest(**data)


# ---------------------------------------------------------------------------
# batas validasi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_size", [0, -1, -1000])
def test_chunk_size_must_be_positive(bad_size):
    with pytest.raises(ValidationError):
        _ingest(chunk_size=bad_size, chunk_overlap=0)


def test_chunk_size_upper_bound():
    with pytest.raises(ValidationError):
        _ingest(chunk_size=main.MAX_CHUNK_SIZE + 1, chunk_overlap=0)
    # tepat di batas masih boleh
    assert _ingest(chunk_size=main.MAX_CHUNK_SIZE, chunk_overlap=0)


def test_chunk_overlap_non_negative():
    with pytest.raises(ValidationError):
        _ingest(chunk_size=1000, chunk_overlap=-1)


@pytest.mark.parametrize("overlap", [1000, 1001, 5000])
def test_overlap_must_be_smaller_than_chunk_size(overlap):
    with pytest.raises(ValidationError) as exc:
        _ingest(chunk_size=1000, chunk_overlap=overlap)
    assert "chunk_overlap" in str(exc.value)


def test_overlap_equal_to_size_rejected():
    """overlap == size tidak berguna; ditolak, bukan diam-diam diterima."""
    with pytest.raises(ValidationError):
        _ingest(chunk_size=1000, chunk_overlap=1000)


def test_too_many_files():
    with pytest.raises(ValidationError):
        _ingest(files=["a.py"] * (main.MAX_INGEST_FILES + 1))
    # tepat di batas boleh
    assert len(_ingest(files=["a.py"] * main.MAX_INGEST_FILES).files) == \
        main.MAX_INGEST_FILES


def test_empty_files_list_still_valid_shape():
    """Daftar kosong bukan error validasi; ditangani di handler."""
    assert _ingest(files=[]).files == []


def test_oversized_inline_entry_rejected():
    huge = "x" * (main.MAX_INGEST_ENTRY_CHARS + 1)
    with pytest.raises(ValidationError) as exc:
        _ingest(files=[huge])
    assert "MAX" in str(exc.value) or "maksimal" in str(exc.value)


def test_top_k_bounded():
    with pytest.raises(ValidationError):
        main.RAGSearchRequest(provider_id="x", query="q", top_k=0)
    with pytest.raises(ValidationError):
        main.RAGSearchRequest(provider_id="x", query="q", top_k=101)
    assert main.RAGSearchRequest(provider_id="x", query="q", top_k=100).top_k == 100


# ---------------------------------------------------------------------------
# perilaku yang harus tetap jalan
# ---------------------------------------------------------------------------

def test_app_defaults_still_valid():
    """Default aplikasi harus lolos validasi apa adanya."""
    req = main.RAGIngestRequest(provider_id="openai:x", files=["a.py"])
    assert req.chunk_size == 1000
    assert req.chunk_overlap == 200


def test_default_chunking_behavior_unchanged():
    """
    _chunk_texts tidak boleh berubah perilakunya. Docstring-nya sudah
    memperingatkan bahwa batas chunk menentukan fingerprint md5 yang jadi
    PRIMARY KEY rag_chunks, jadi ini dikunci eksplisit.
    """
    text = "\n".join(f"baris {i}" for i in range(50))
    chunks = main._chunk_texts([text], 1000, 200)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_normal_file_chunks_sensibly():
    text = "\n".join(f"baris {i} " + "x" * 50 for i in range(100))
    chunks = main._chunk_texts([text], 200, 20)
    assert len(chunks) > 1
    assert all(c for c in chunks)


# ---------------------------------------------------------------------------
# bukti: jumlah request keluar ikut terkendali
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import database
    import storage
    from fastapi.testclient import TestClient

    calls = []

    class Emb(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            calls.append(len(body.get("input", "")))
            out = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Emb)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    monkeypatch.setattr(auth, "API_TOKEN", TOKEN, raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "synapse.db"))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "synapse.db"))
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    storage.reset_conn()
    database.init_db()
    storage.init_db()

    main.create_llm_provider(main.LLMProviderCreate(
        type="openai", name="emb", api_key="sk-dummy",
        base_url=f"http://127.0.0.1:{port}/v1", models=["m"]))

    with TestClient(main.app, raise_server_exceptions=False) as c:
        c.headers.update({auth.TOKEN_HEADER: TOKEN})
        yield c, calls
    srv.shutdown()


@pytest.fixture()
def many_line_file(tmp_path, monkeypatch):
    """File di dalam repo supaya lolos proteksi path."""
    target = Path(settings_store.REPO_ROOT) / "backend" / "_probe_rag_limit.txt"
    target.write_text(
        "\n".join(f"baris nomor {i} dengan isi yang cukup panjang" for i in range(200)),
        encoding="utf-8",
    )
    yield str(target)
    target.unlink(missing_ok=True)


def test_degenerate_chunk_size_makes_no_outbound_request(client, many_line_file):
    """
   Regression: chunk_size 0 / negatif dulu menghasilkan 201 request keluar.
    Sekarang ditolak di validasi, jadi nol request yang keluar.
    """
    c, calls = client
    for bad in (0, -1):
        calls.clear()
        r = c.post("/api/rag/ingest", json={
            "provider_id": "openai:emb", "model": "m",
            "files": [many_line_file], "chunk_size": bad, "chunk_overlap": 0,
        })
        assert r.status_code == 422, f"chunk_size={bad} menghasilkan {r.status_code}"
        assert calls == [], f"chunk_size={bad} tetap mengirim {len(calls)} request"


def test_too_many_files_makes_no_outbound_request(client):
    c, calls = client
    r = c.post("/api/rag/ingest", json={
        "provider_id": "openai:emb", "model": "m",
        "files": ["a.py"] * (main.MAX_INGEST_FILES + 1),
        "chunk_size": 1000, "chunk_overlap": 200,
    })
    assert r.status_code == 422
    assert calls == []


def test_chunk_cap_blocks_runaway_ingest(client, tmp_path, monkeypatch):
    """
    Pengaman kedua: meski validasi lolos, jumlah chunk dibatasi sehingga loop
    request keluar tidak bisa berjalan tak terbatas.
    """
    c, calls = client
    # buat file besar dengan barian pendek supaya chunk_size kecil menghasilkan
    # banyak chunk
    big = Path(settings_store.REPO_ROOT) / "backend" / "_probe_rag_big.txt"
    try:
        big.write_text("\n".join("x" for _ in range(20000)), encoding="utf-8")
        r = c.post("/api/rag/ingest", json={
            "provider_id": "openai:emb", "model": "m",
            "files": [str(big)], "chunk_size": 1, "chunk_overlap": 0,
        })
        assert r.status_code in (413, 422), f"dapatnya {r.status_code}: {r.text[:150]}"
        if r.status_code == 413:
            assert "chunk" in r.json()["detail"].lower()
            assert calls == [], "tidak boleh ada request keluar kalau sudah ditolak"
    finally:
        big.unlink(missing_ok=True)


def test_normal_ingest_still_works(client, many_line_file):
    """
    Ingest normal harus tetap berfungsi. Jumlah request embedding tidak
    di-hardcode: yang diuji adalah satu request per chunk, dan jumlahnya
    masuk akal untuk ukuran file -- bukan jauh melonjak.
    """
    c, calls = client
    r = c.post("/api/rag/ingest", json={
        "provider_id": "openai:emb", "model": "m",
        "files": [many_line_file], "chunk_size": 1000, "chunk_overlap": 200,
    })
    assert r.status_code == 200, r.text[:200]
    assert r.json()["ok"] is True
    written = r.json()["chunks"]
    assert written == len(calls), (
        f"{written} chunk tersimpan tapi {len(calls)} request embedding; "
        "harus satu request per chunk"
    )
    assert 1 <= written <= 50, f"{written} chunk untuk file kecil, tak masuk akal"
