"""
Regression test untuk autentikasi, dekripsi credential, CORS, dan batas input RAG.

M1 [MEDIUM] auth.verify_token() memakai secrets.compare_digest pada str.
    compare_digest mewajibkan kedua sisi ASCII dan melempar
    TypeError begitu token memuat karakter non-ASCII. Middleware auth tidak
    menangkap exception, jadi satu karakter "é" di header berujung 500 +
    traceback, bukan 401. 500 di jalur auth juga berarti respons tidak
    terduga (dan berpotensi bocor) untuk request yang seharusnya ditolak.

M3 [MEDIUM] decrypt_token() melempar exception library mentah
    (Fernet.InvalidToken, atau AttributeError kalau nilai None). Semua
    pemanggilnya di main.py tidak menangkap, jadi credential tersimpan yang
    tidak bisa dibuka menghasilkan 500 berisi stack trace Fernet.
    Terkait: FERNET_KEY yang terisi tapi invalid dulu senyap ditukar dengan
    key acak, yang memusnahkan seluruh credential tersimpan tanpa error.

M4 [MEDIUM] CORS allow_methods hanya "GET","POST","OPTIONS", padahal app
    punya route PUT/PATCH/DELETE nyata. Preflight lalu tidak pernah
    mengizinkan method itu dan browser memblokirnya.

M5 [MEDIUM] tidak ada satu pun test yang meminta tanpa token. Test 401 yang
    ada hanya memanggil auth.verify_token() langsung, jadi middleware yang
    sebenarnya bisa dicabut tanpa CI merah.

M15 [MEDIUM] RAGIngestRequest.chunk_size/chunk_overlap tanpa batas.
    chunk_size <= 0 membuat syarat `len(...) >= chunk_size` selalu benar,
    sehingga setiap baris jadi satu chunk terpisah — 100rb baris berarti
    100rb panggilan API berbayar dari satu request.

L1 [LOW] auth.require_api_key() tidak pernah dipakai di route mana pun dan
    tidak punya test, sehingga statusnya sebagai dependency tidak
    terverifikasi.
"""

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402
from fastapi import HTTPException, Request  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------- helpers


def _request_with_headers(headers):
    """Bangun Request Starlette dari daftar (name, value) mentah."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    return Request(scope)


def _preflight(method):
    """
    Preflight CORS untuk `method` tertentu.

    Header wajib preflight: Origin + Access-Control-Request-Method.
    """
    from httpx import ASGITransport, AsyncClient

    async def run():
        transport = ASGITransport(app=_main_app())
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.options(
                "/api/llm/providers/p1",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": method,
                },
            )

    return asyncio.run(run())


def _main_app():
    import main

    return main.app


# ---------------------------------------------------------------- M1 / M5


class TestTokenEnforcement:
    def test_missing_token_returns_401_bukan_500(self):
        """
        Request tanpa satu pun header token harus 401.

        Ditulis lewat ASGITransport supaya lolos fixture conftest yang
        menyuntikkan X-Synapse-Token otomatis ke setiap TestClient.request —
        tanpa ini "token hilang" tidak pernah bisa dirujuk sama sekali.
        """
        from httpx import ASGITransport, AsyncClient

        async def run():
            transport = ASGITransport(app=_main_app())
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get("/api/llm/providers")

        resp = asyncio.run(run())
        assert resp.status_code == 401, resp.text
        assert "detail" in resp.json()

    def test_invalid_token_returns_401(self):
        client = TestClient(_main_app())
        resp = client.get(
            "/api/llm/providers",
            headers={auth.TOKEN_HEADER: "token-palsu-bukan-yang-asli"},
        )
        assert resp.status_code == 401

    def test_empty_token_header_returns_401(self):
        """Header ada tapi kosong dianggap tidak ada token, bukan lolos."""
        client = TestClient(_main_app())
        resp = client.get(
            "/api/llm/providers", headers={auth.TOKEN_HEADER: ""}
        )
        assert resp.status_code == 401

    def test_valid_token_returns_200(self):
        client = TestClient(_main_app())
        resp = client.get(
            "/api/llm/providers", headers={auth.TOKEN_HEADER: auth.API_TOKEN}
        )
        assert resp.status_code == 200, resp.text

    def test_public_health_tanpa_token(self):
        client = TestClient(_main_app())
        # kosongkan secara eksplisit: conftest menyuntikkan token otomatis
        resp = client.get("/health", headers={auth.TOKEN_HEADER: ""})
        assert resp.status_code == 200

    def test_non_ascii_token_returns_401_bukan_500(self):
        """
        Inti M1: header token berisi karakter non-ASCII dulu memicu
        TypeError di secrets.compare_digest yang lolos ke handler 500
        dengan traceback, bukan 401.

        Tidak bisa lewat httpx: _normalize_header_value meng-encode nilai
        header sebagai ASCII dan melempar UnicodeEncodeError di sisi klien,
        padahal klien HTTP nyata (curl, klien mentah, klien non-Python)
        bebas mengirim byte apa pun. Karena itu test ini memanggil middleware
        langsung dengan raw byte 0xe9 — persis yang diterima uvicorn lalu
        di-decode latin-1 jadi 'é'.
        """
        import main

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/llm/providers",
            "raw_path": b"/api/llm/providers",
            "query_string": b"",
            "headers": [(b"x-synapse-token", b"caf\xe9-\xe9\xe9\xe9")],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }

        async def call_next(request):  # pragma: no cover - tidak boleh kejar
            raise AssertionError("request ber-token non-ASCII tidak boleh lolos")

        resp = asyncio.run(main.enforce_api_token(Request(scope), call_next))
        assert resp.status_code == 401, (
            f"dapat {resp.status_code} (diharapkan 401, bukan 500)"
        )

    def test_non_ascii_header_menghasilkan_token_atau_none_tanpa_melempar(self):
        """_extract_token + verify_token tidak boleh melempar, apa pun isinya."""
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/llm/providers",
            "raw_path": b"/api/llm/providers",
            "query_string": b"",
            "headers": [(b"x-synapse-token", "token-日本語".encode("utf-8"))],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
        token = auth._extract_token(Request(scope))
        assert auth.verify_token(token) is False

    def test_verify_token_non_ascii_mengembalikan_false(self):
        assert auth.verify_token("tökén-non-ascii") is False

    def test_verify_token_ascii_tetap_benar(self):
        assert auth.verify_token(auth.API_TOKEN) is True

    def test_verify_token_kosong(self):
        assert auth.verify_token(None) is False
        assert auth.verify_token("") is False
        assert auth.verify_token("   ") is False

    def test_verify_token_beda_panjang(self):
        assert auth.verify_token(auth.API_TOKEN[:-1]) is False
        assert auth.verify_token(auth.API_TOKEN + "x") is False


# ---------------------------------------------------------------- L1


class TestRequireApiKeyDependency:
    """auth.require_api_key() dulu tidak pernah dipakai dan tidak dites."""

    def test_dependency_melempar_401_tanpa_token(self):
        req = _request_with_headers([])
        with pytest.raises(HTTPException) as exc:
            auth.require_api_key(req)
        assert exc.value.status_code == 401
        assert "WWW-Authenticate" in exc.value.headers

    def test_dependency_melempar_401_token_salah(self):
        req = _request_with_headers([(auth.TOKEN_HEADER, "salah")])
        with pytest.raises(HTTPException) as exc:
            auth.require_api_key(req)
        assert exc.value.status_code == 401

    def test_dependency_mengembalikan_token_valid(self):
        req = _request_with_headers([(auth.TOKEN_HEADER, auth.API_TOKEN)])
        assert auth.require_api_key(req) == auth.API_TOKEN

    def test_dependency_menerima_bearer_scheme(self):
        req = _request_with_headers(
            [("Authorization", f"Bearer {auth.API_TOKEN}")]
        )
        assert auth.require_api_key(req) == auth.API_TOKEN


# ---------------------------------------------------------------- M4


class TestCorsAllowMethods:
    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_preflight_mengizinkan_method_route_nyata(self, method):
        """
        Route nyata memakai ketiganya (PUT /api/projects/{id}/llm-config,
        PATCH + DELETE /api/llm/providers/{id}). Preflight yang tidak
        mengizinkannya membuat browser memblokir request itu.
        """
        resp = _preflight(method)
        assert resp.status_code == 200, resp.text
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert method in allowed, (
            f"preflight untuk {method} tidak mengizinkannya: {allowed!r}"
        )

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_preflight_tetap_mengizinkan_method_lama(self, method):
        resp = _preflight(method)
        assert method in resp.headers.get("access-control-allow-methods", "")

    def test_preflight_hanya_origin_terdaftar(self):
        from httpx import ASGITransport, AsyncClient

        async def run():
            transport = ASGITransport(app=_main_app())
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.options(
                    "/api/llm/providers/p1",
                    headers={
                        "Origin": "http://evil.example",
                        "Access-Control-Request-Method": "POST",
                    },
                )

        resp = asyncio.run(run())
        # Origin asing tidak boleh dapat konfirmasi CORS
        assert not resp.headers.get("access-control-allow-origin"), (
            "origin asing diizinkan CORS"
        )

    def test_tidak_ada_wildcard_origin(self):
        import main

        raw = Path(BACKEND_DIR / "main.py").read_text(encoding="utf-8")
        assert 'allow_origins=["*"]' not in raw


# ---------------------------------------------------------------- M3


class TestDecryptErrors:
    def _stored(self, value):
        return auth.decrypt_stored_token(value)

    def _client(self, value):
        return auth.decrypt_client_token(value)

    def test_nilai_bukan_fernet_menghasilkan_token_decrypt_error(self):
        with pytest.raises(auth.TokenDecryptError):
            auth.decrypt_token("ini-bukan-token-fernet")

    def test_decrypt_token_none_tidak_attribute_error(self):
        with pytest.raises(auth.TokenDecryptError):
            auth.decrypt_token(None)

    def test_decrypt_stored_kosong_400(self):
        """Provider tanpa API key: masalah konfigurasi user -> 400, bukan 500."""
        with pytest.raises(HTTPException) as exc:
            self._stored(None)
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            self._stored("")
        assert exc.value.status_code == 400

    def test_decrypt_stored_rusak_500_dengan_pesan_actionable(self):
        with pytest.raises(HTTPException) as exc:
            self._stored("bukan-fernet-juga")
        assert exc.value.status_code == 500
        assert "FERNET_KEY" in exc.value.detail

    def test_decrypt_client_rusak_400(self):
        """Input klien yang tidak valid -> 400, bukan 500."""
        with pytest.raises(HTTPException) as exc:
            self._client("bukan-fernet-juga")
        assert exc.value.status_code == 400

    def test_roundtrip_masih_bekerja(self):
        plain = "sk-halodunia-1234567890"
        assert auth.decrypt_token(auth.encrypt_token(plain)) == plain

    def test_exception_library_tidak_bocor_ke_pemanggil(self):
        """Fernet.InvalidToken tidak boleh keluar dari decrypt_token."""
        from cryptography.fernet import InvalidToken

        with pytest.raises(auth.TokenDecryptError):
            auth.decrypt_token("AAAA")
        with pytest.raises(auth.TokenDecryptError):
            auth.decrypt_token("!" * 100)


# ---------------------------------------------------------------- M15


class TestRagIngestBounds:
    @pytest.mark.parametrize("chunk_size", [0, -1, -1000, 99999999])
    def test_chunk_size_di_luar_batas_ditolak_422(self, chunk_size):
        """
        chunk_size <= 0 membuat loop chunking menghasilkan satu chunk per
        baris (syarat `len(...) >= chunk_size` selalu benar) -> satu
        panggilan API berbayar per baris file.
        """
        client = TestClient(_main_app())
        resp = client.post(
            "/api/rag/ingest",
            json={
                "provider_id": "p1",
                "files": ["a\nb\nc"],
                "chunk_size": chunk_size,
            },
        )
        assert resp.status_code == 422, (
            f"chunk_size={chunk_size} diterima (diharapkan 422): {resp.text[:200]}"
        )

    @pytest.mark.parametrize("chunk_overlap", [0, -1, -99999])
    def test_chunk_overlap_negatif_ditolak_422(self, chunk_overlap):
        client = TestClient(_main_app())
        resp = client.post(
            "/api/rag/ingest",
            json={
                "provider_id": "p1",
                "files": ["isi dokumen"],
                "chunk_overlap": chunk_overlap,
            },
        )
        if chunk_overlap < 0:
            assert resp.status_code == 422, resp.text[:200]

    def test_chunk_size_default_dan_valid_diterima(self):
        """Batas tidak boleh menolak nilai yang wajar."""
        client = TestClient(_main_app())
        resp = client.post(
            "/api/rag/ingest",
            json={
                "provider_id": "p1",
                "files": ["isi dokumen"],
                "chunk_size": 1000,
                "chunk_overlap": 200,
            },
        )
        # lolos validasi pydantic (bukan 422); gagal belakangan karena
        # provider tidak ada di DB temporer
        assert resp.status_code != 422, resp.text[:200]

    def test_chunk_size_tepat_di_batas_atas_diterima(self):
        client = TestClient(_main_app())
        resp = client.post(
            "/api/rag/ingest",
            json={"provider_id": "p1", "files": ["x"], "chunk_size": 8000},
        )
        assert resp.status_code != 422, resp.text[:200]
