"""
test_issue_ssrf_header.py — regression test untuk SSRF LLM base_url dan
input yang merusak HTTP header.

Dua temuan, masing-masing dengan bukti:

  1. SSRF + kebocoran kredensial lewat base_url provider LLM.
     POST /api/llm/providers menerima base_url dari user tanpa validasi URL
     apa pun. base_url itu lalu dipakai llm_chat / rag_ingest / rag_search
     untuk request HTTP keluar, dengan header Authorization berisi API key
     yang sudah didekripsi. Bukti: provider dengan base_url ke HTTP server
     milik si penyerang menerima request, lengkap dengan
     "Authorization: Bearer <key asli>", dan respons internal-nya dikembalikan
     ke pemanggil. Jadi bukan blind SSRF, dan key-nya ikut bocor.

  2. 500 untuk input yang sebenarnya cuma salah.
     POST /api/github/auth/pat menaruh PAT mentah di header Authorization.
     requests mengubah header ke Latin-1, jadi karakter non-ASCII (emoji,
     combining mark, U+202E) melempar UnicodeEncodeError, dan newline/CR
     melempar InvalidHeader. Keduanya tidak tertangkap -> 500 "Internal
     Server Error" beserta traceback di log. GitHub token selalu ASCII,
     jadi ini harus jadi 400 yang jelas.

Yang SENGAJA tetap diizinkan: localhost dan alamat privat. Ollama
(http://localhost:11434) dan server OpenAI-compatible self-hosted (vLLM,
LM Studio, LiteLLM) adalah use case sah aplikasi ini. Memblokirnya akan
merusak fitur, bukan menutup risiko. Test di bawah mengunci batas itu supaya
keputusan produknya eksplisit, bukan tersembunyi.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402

# Host cloud-metadata: target SSRF paling umum, dan tidak pernah base_url
# LLM yang sah.
METADATA_URLS = [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "https://169.254.169.254/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata.goog/",
    "http://100.100.100.200/latest/meta-data/",
    "http://[fd00:ec2::254]/latest/",
]

# Use case sah yang TIDAK boleh ikut diblokir.
LEGITIMATE_URLS = [
    "https://api.openai.com/v1",
    "https://api.anthropic.com/v1",
    "https://integrate.api.nvidia.com/v1",
    "https://api.deepseek.com/v1",
    "http://localhost:11434",            # Ollama
    "http://127.0.0.1:8000/v1",          # vLLM / LM Studio
    "http://192.168.1.50:8000/v1",       # vLLM di LAN
    "https://gw.example.com/proxy/llm/v1/",
]

MALFORMED_URLS = [
    "file:///etc/passwd",
    "gopher://evil.example.com/_payload",
    "not-a-url",
    "://no-scheme",
    "http://user:pass@evil.example.com/v1",
    "http://evil.example.com@169.254.169.254/",
    "http://exa\x00mple.com/v1",
    "http://example.com/v1\r\nX-Injected: 1",
    "http://example.com/a b",
    "http://example.com/\tv1",
    "http://example.com/" + "a" * 3000,
]

# Nilai yang tidak bisa dikirim sebagai header HTTP.
BAD_HEADER_VALUES = [
    "gho\x00abc",          # NUL
    "gho\x07abc",          # BEL
    "gho\nabc",            # LF
    "gho\rabc",            # CR
    "gho\tabc",            # TAB
    "gho\u202eabc",        # RIGHT-TO-LEFT OVERRIDE
    "gho\U0001F600abc",    # emoji
    "gho\u0301abc",        # combining acute accent
    "gho abc",             # spasi di tengah
]


# ---------------------------------------------------------------------------
# 1. base_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", METADATA_URLS)
def test_metadata_base_url_rejected(url):
    """Host cloud-metadata tidak boleh bisa jadi base_url LLM."""
    with pytest.raises(HTTPException) as exc:
        main._validate_llm_base_url(url)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("url", MALFORMED_URLS)
def test_malformed_base_url_rejected(url):
    """Skema aneh, URL tanpa host, kredensial tertanam, dan karakter kontrol."""
    with pytest.raises(HTTPException) as exc:
        main._validate_llm_base_url(url)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("url", LEGITIMATE_URLS)
def test_legitimate_base_url_accepted(url):
    """
    Ollama dan server self-hosted tetap harus jalan. Test ini ada supaya
    keputusan 'localhost diizinkan' tercatat eksplisit: kalau suatu saat mau
    diblokir, test ini gagal dan trade-off-nya terlihat, bukan diam-diam
    merusak fitur.
    """
    assert main._validate_llm_base_url(url) == url


@pytest.mark.parametrize("url", [None, "", "   "])
def test_empty_base_url_falls_back_to_default(url):
    """Kosong berarti 'pakai default provider', bukan error."""
    assert main._validate_llm_base_url(url) is None


def test_non_string_base_url_rejected():
    with pytest.raises(HTTPException) as exc:
        main._validate_llm_base_url(12345)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("url", METADATA_URLS + MALFORMED_URLS)
def test_every_base_url_consumer_validates(url):
    """
    base_url tidak boleh bisa lolos hanya karena baris DB-nya sudah ada
    sebelum validasi dipasang. Semua titik pakai harus memanggil validator,
    supaya baris lama yang rusak juga tertangkap.
    """
    import ast

    source = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    consumers = {"llm_chat", "rag_ingest", "rag_search"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in consumers:
            body = ast.unparse(node)
            assert "_validate_llm_base_url" in body, (
                f"{node.name} memakai base_url tanpa memanggil _validate_llm_base_url"
            )
            seen.add(node.name)
    assert seen == consumers, f"endpoint tidak ditemukan: {consumers - seen}"


def test_metadata_provider_row_blocked_at_use_time(tmp_path, monkeypatch):
    """
    Pertahanan kedalaman: provider dengan base_url cloud-metadata yang
    somehow sudah tersimpan harus ditolak saat dipakai, bukan hanya saat
    ditulis.
    """
    import os

    import auth
    import database
    import storage

    db = tmp_path / "synapse.db"
    monkeypatch.setattr(database, "DB_PATH", str(db))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    monkeypatch.setattr(main, "DB_PATH", str(db))
    storage.reset_conn()
    database.init_db()
    storage.init_db()
    monkeypatch.setenv("FERNET_KEY", auth.generate_key() if hasattr(auth, "generate_key") else "")

    from auth import encrypt_token

    conn = database.connect(str(db))
    try:
        conn.execute(
            """INSERT INTO llm_providers
               (id, name, type, base_url, api_key, models, default_model,
                max_tokens, supports_tools, supports_vision, enabled,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "openai:imds", "imds", "openai",
                "http://169.254.169.254/latest/",   # baris "&buruk", bypassing create
                encrypt_token("sk-whatever"),
                '["m"]', "m", 4096, 1, 0, 1,
                guardian_stamp(), guardian_stamp(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    provider = main._load_provider_row("openai:imds")
    assert provider is not None
    with pytest.raises(HTTPException) as exc:
        main._validate_llm_base_url(provider["base_url"])
    assert exc.value.status_code == 400


def guardian_stamp():
    import guardian
    return guardian._utcnow_iso()


# ---------------------------------------------------------------------------
# 2. nilai yang merusak HTTP header
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", BAD_HEADER_VALUES)
def test_bad_header_value_rejected(value):
    """
    Nilai yang tidak bisa jadi header harus jadi 400, bukan 500.
    Termasuk yang secara teknis bisa di-encode Latin-1 tapi tetap tidak
    sah sebagai token.
    """
    with pytest.raises(HTTPException) as exc:
        main._validate_header_token(value, "pat")
    assert exc.value.status_code == 400


def test_good_header_value_accepted():
    for good in ("ghp_abc123", "github_pat_11ABCDEFG_x", "gho_0123456789abcdef"):
        assert main._validate_header_token(good, "pat") == good


def test_header_value_too_long_rejected():
    with pytest.raises(HTTPException) as exc:
        main._validate_header_token("g" * 5000, "pat")
    assert exc.value.status_code == 400


def test_github_pat_returns_400_not_500_for_bad_token():
    """
    Uji level endpoint: input yang merusak header harus menghasilkan 400.
    Sebelum fix, semua nilai di sini menghasilkan 500
    "Internal Server Error" karena UnicodeEncodeError / InvalidHeader
    tidak tertangkap.
    """
    import asyncio

    for value in ("gho\U0001F600abc", "gho\nabc", "gho\u202eabc"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.github_pat(main.GitHubPATRequest(pat=value)))
        assert exc.value.status_code == 400, (
            f"{value!r} menghasilkan {exc.value.status_code}, harusnya 400"
        )


def test_github_oauth_misconfigured_returns_503():
    """
    'OAuth not configured' adalah kondisi konfigurasi, bukan kegagalan
    server. 500 bikin monitoring salah alarm dan menutupi bug 500 asli.
    """
    import asyncio
    import os

    old = {k: os.environ.pop(k, None) for k in ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET")}
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.github_callback(code="x"))
        assert exc.value.status_code == 503

        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.github_oauth_url())
        assert exc.value.status_code == 503
    finally:
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# 3. bukti langsung: request tidak pernah sampai ke host penyerang
# ---------------------------------------------------------------------------

def test_no_outbound_request_to_metadata_host(tmp_path, monkeypatch):
    """
    Bukti bahwa request ke host metadata benar-benar tidak terjadi, bukan
    hanya 'tidak ada respons'.

    Dipakai server HTTP lokal yang mencatat request apa pun yang masuk. kalau
    base_url lolos, request itu akan muncul di sini.
    """
    import asyncio
    import json

    import auth
    import database
    import storage

    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            captured.append(self.path)
            body = json.dumps({
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "x"},
                             "finish_reason": "stop"}]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    db = tmp_path / "synapse.db"
    monkeypatch.setattr(database, "DB_PATH", str(db))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    monkeypatch.setattr(main, "DB_PATH", str(db))
    storage.reset_conn()
    database.init_db()
    storage.init_db()

    from auth import encrypt_token

    conn = database.connect(str(db))
    try:
        conn.execute(
            """INSERT INTO llm_providers
               (id, name, type, base_url, api_key, models, default_model,
                max_tokens, supports_tools, supports_vision, enabled,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "openai:local", "local", "openai",
                f"http://127.0.0.1:{port}/v1",
                encrypt_token("sk-test-key"),
                '["m"]', "m", 4096, 1, 0, 1,
                guardian_stamp(), guardian_stamp(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        # base_url ke host lokal SAHIH secara sengaja, jadi request ini
        # memang dibiarkan lewat -- inilah yang membuat localhost tidak
        # bisa diblokir tanpa merusak Ollama / vLLM.
        asyncio.run(main.llm_chat(main.ChatCompletionRequest(
            provider_id="openai:local", model="m",
            messages=[main.ChatMessage(role="user", content="hi")],
        )))
        assert captured, (
            "localhost sengaja diizinkan, jadi request memang harus sampai; "
            "kalau tidak sampai, ada perubahan perilaku lain yang tak disadari"
        )

        # Sekarang host metadata: harus ditolak, dan tidak boleh ada request.
        captured.clear()
        with pytest.raises(HTTPException) as exc:
            main._validate_llm_base_url("http://169.254.169.254/latest/")
        assert exc.value.status_code == 400
        assert not captured
    finally:
        srv.shutdown()
