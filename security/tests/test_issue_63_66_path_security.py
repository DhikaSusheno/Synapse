"""
test_issue_63_66_path_security.py — regresi untuk #66 dan #63.

#66: tiga endpoint menerima path filesystem dari request tanpa validasi.
      - POST /api/rag/ingest   (RAGIngestRequest.files)
      - POST /review_change   (ReviewArtifactRequest.path_or_diff)
      - POST /understand_repo (UnderstandRepoRequest.repo_path)

      Yang paling parah: /api/rag/ingest membaca file dari disk lalu
      MENGIRIM isinya ke provider LLM pihak ketiga. Jadi ini bukan sekadar
      arbitrary file read, tapi exfiltrasi.

      Catatan penting soal desain fix-nya: allowlist root saja TIDAK cukup,
      karena file .env berada DI DALAM repo. Itu sebabnya settings.py punya
      dua lapis — allowed roots DAN daftar file sensitif. Test di bawah
      mengunci kedua lapis itu, karena cuma menguji "path di luar root" akan
      lolos sementara bug aslinya masih hidup.

#63: proxy frontend menyuntikkan SYNAPSE_API_TOKEN ke semua pemanggil.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import settings as settings_store


# ---------------------------------------------------------------------------
# Fixture: workspace yang terisolasi
# ---------------------------------------------------------------------------

@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """
    Sandbox dengan dua root yang diizinkan:
      allowed/   - meniru repo + file kode yang BOLEH dibaca
      secrets/   - meniru home directory pengguna (di luar root)
    """
    root = tmp_path / "allowed"
    outside = tmp_path / "secrets"
    root.mkdir()
    outside.mkdir()

    (root / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    (root / ".env").write_text("SYNAPSE_API_TOKEN=abc\nFERNET_KEY=secret\n", encoding="utf-8")
    (root / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    (root / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    (root / "app.db").write_text("sqlite\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "notes.md").write_text("# catatan\n", encoding="utf-8")

    (outside / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    (outside / "innocent.txt").write_text("bukan rahasia\n", encoding="utf-8")
    (outside / ".env").write_text("FERNET_KEY=leak\n", encoding="utf-8")

    # Arahkan allowed_roots() ke sandbox ini supaya test tidak bergantung pada
    # letak repo di disk.
    monkeypatch.setattr(settings_store, "REPO_ROOT", str(root))
    monkeypatch.setattr(
        settings_store,
        "load",
        lambda: {**settings_store.DEFAULTS, "workspace_path": str(root)},
    )
    return {"root": root, "outside": outside}


# ---------------------------------------------------------------------------
# #66 lapis 1: file TEORITIS boleh dibaca
# ---------------------------------------------------------------------------

def test_readable_allows_source_inside_root(workspace):
    assert settings_store.is_readable_path(str(workspace["root"] / "main.py"))


def test_readable_allows_nested_file_inside_root(workspace):
    assert settings_store.is_readable_path(str(workspace["root"] / "sub" / "notes.md"))


def test_readable_allows_root_itself(workspace):
    assert settings_store.is_readable_path(str(workspace["root"]))


# ---------------------------------------------------------------------------
# #66 lapis 2: path DI LUAR root ditolak
# ---------------------------------------------------------------------------

def test_rejects_absolute_path_outside_root(workspace):
    assert not settings_store.is_readable_path(str(workspace["outside"] / "innocent.txt"))


def test_rejects_relative_traversal_out_of_root(workspace):
    traversal = os.path.join(str(workspace["root"]), "..", "secrets", "id_rsa")
    assert not settings_store.is_readable_path(traversal)


def test_rejects_home_expansion(workspace, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(workspace["outside"]))
    monkeypatch.setenv("HOME", str(workspace["outside"]))
    assert not settings_store.is_readable_path("~/id_rsa")


def test_rejects_parent_of_root(workspace):
    assert not settings_store.is_readable_path(str(workspace["root"].parent))


def test_rejects_empty_and_whitespace():
    assert not settings_store.is_readable_path("")
    assert not settings_store.is_readable_path("   ")
    assert not settings_store.is_readable_path(None)


# ---------------------------------------------------------------------------
# #66 lapis 3: file sensitif ditolak WALAUPUN berada di dalam root
# ---------------------------------------------------------------------------
# Test paling penting di file ini. .env ada DI DALAM repo, jadi kalau fix-nya
# cuma allowlist root, file ini lolos dan FERNET_KEY tetap bisa bocor ke LLM.

@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "app.db",
        "app.sqlite3",
        "keystore.p12",
        ".npmrc",
        ".netrc",
        "credentials.json",
    ],
)
def test_rejects_sensitive_files_even_inside_root(workspace, name):
    target = workspace["root"] / name
    target.write_text("rahasia\n", encoding="utf-8")
    assert settings_store.is_readable_path.__module__  # sanity: helper ter-resolve
    assert not settings_store.is_readable_path(str(target)), (
        f"{name} ada di dalam root tapi harus tetap ditolak"
    )


def test_rejects_ssh_directory(workspace):
    ssh_dir = workspace["root"] / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text("Host *\n", encoding="utf-8")
    assert not settings_store.is_readable_path(str(ssh_dir / "config"))


def test_real_env_inside_actual_repo_is_rejected():
    """
    Guard nyata: file .env yang benar-benar ada di repo development
    (bukan hasil tmp_path) harus ditolak oleh helper.
    """
    backend_env = Path(settings_store.BASE_DIR) / ".env"
    if not backend_env.exists():
        pytest.skip("tidak ada .env di checkout ini")
    assert not settings_store.is_readable_path(str(backend_env))


# ---------------------------------------------------------------------------
# #66: review_change() menolak file di luar root
# ---------------------------------------------------------------------------

def test_review_change_rejects_outside_file(workspace):
    import engine

    target = workspace["outside"] / "innocent.txt"
    result = engine.review_change(str(target))

    assert result["ok"] is False, "file di luar root harus ditolak, bukan dinilai"
    assert "tidak boleh dibaca" in result["error"]


def test_review_change_rejects_traversal(workspace):
    import engine

    traversal = os.path.join(str(workspace["root"]), "..", "secrets", "id_rsa")
    result = engine.review_change(traversal)

    assert result["ok"] is False
    assert "tidak boleh dibaca" in result["error"]


def test_review_change_rejects_env_inside_root(workspace):
    """Yang ini akan LOLOS kalau fix-nya cuma allowlist root."""
    import engine

    result = engine.review_change(str(workspace["root"] / ".env"))
    assert result["ok"] is False
    assert "tidak boleh dibaca" in result["error"]


def test_review_change_still_accepts_inline_diff(workspace):
    """Fix tidak boleh merusak jalur diff inline yang dipakai frontend."""
    import engine

    result = engine.review_change("+def f():\n+    pass\n- old line\n")
    assert result["ok"] is True


def test_review_change_still_accepts_allowed_file(workspace):
    import engine

    result = engine.review_change(str(workspace["root"] / "main.py"))
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# #66: ingest_repository() menolak direktori di luar root
# ---------------------------------------------------------------------------

def test_ingest_repository_rejects_outside_dir(workspace):
    import engine

    result = engine.ingest_repository(str(workspace["outside"]))
    assert result["ok"] is False
    assert "tidak boleh dipindai" in result["error"]


def test_ingest_repository_rejects_traversal_dir(workspace):
    import engine

    traversal = os.path.join(str(workspace["root"]), "..", "secrets")
    result = engine.ingest_repository(traversal)
    assert result["ok"] is False
    assert "tidak boleh dipindai" in result["error"]


def test_ingest_repository_still_reports_missing_path(workspace):
    """Perilaku lama harus dipertahankan: path hilang -> error yang jelas."""
    import engine

    result = engine.ingest_repository(str(workspace["root"] / "nope"))
    assert result["ok"] is False
    assert "tidak ditemukan" in result["error"]


# ---------------------------------------------------------------------------
# #66: /api/rag/ingest tidak boleh mengirim isi file terlarang ke LLM
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(workspace):
    """
    TestClient dengan SYNAPSE_API_TOKEN yang diketahui.

    auth.API_TOKEN dibaca SEKALI saat import, jadi monkeypatch.setenv di dalam
    test terlalu late - tokennya sudah ter-cache. Patch konstantanya langsung.
    """
    import auth
    import main

    main.app.dependency_overrides.clear()
    from fastapi.testclient import TestClient

    token = "test-token-1234567890abcdef"
    with TestClient(main.app) as c:
        c.headers.update({"X-Synapse-Token": token})
        # importlib tidak dipakai: cukup set atribut modul, dan auth.verify_token
        # membacanya saat request lewat module global.
        original = auth.API_TOKEN
        auth.API_TOKEN = token
        try:
            yield c
        finally:
            auth.API_TOKEN = original


def test_client_fixture_token_actually_works(client):
    """Guard: kalau fixture ini bocor, semua test 400 di bawahnya Meaningless."""
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text


def test_rag_ingest_rejects_env_file(client, workspace, monkeypatch):
    """
    Regresi inti #66: .env berada di dalam repo, tapi isinya (FERNET_KEY)
    tidak boleh sampai ke provider LLM.
    """
    from fastapi import HTTPException

    resp = client.post(
        "/api/rag/ingest",
        json={"provider_id": "p-test", "files": [str(workspace["root"] / ".env")], "chunk_size": 500},
    )
    assert resp.status_code == 400, resp.text
    assert "tidak boleh dibaca" in resp.json()["detail"]


def test_rag_ingest_rejects_outside_file(client, workspace, monkeypatch):
    resp = client.post(
        "/api/rag/ingest",
        json={"provider_id": "p-test", "files": [str(workspace["outside"] / "innocent.txt")], "chunk_size": 500},
    )
    assert resp.status_code == 400
    assert "tidak boleh dibaca" in resp.json()["detail"]


def test_rag_ingest_rejects_traversal(client, workspace, monkeypatch):
    traversal = os.path.join(str(workspace["root"]), "..", "secrets", "id_rsa")
    resp = client.post(
        "/api/rag/ingest",
        json={"provider_id": "p-test", "files": [traversal], "chunk_size": 500},
    )
    assert resp.status_code == 400
    assert "tidak boleh dibaca" in resp.json()["detail"]


def test_rag_ingest_still_accepts_inline_content(client, workspace, monkeypatch):
    """
    jalur ini harus tetap jalan - frontend memang mengirim konten langsung
    lewat field yang sama.
    """
    resp = client.post(
        "/api/rag/ingest",
        json={"provider_id": "p-test", "files": ["+def hello():\n+    return 1\n"], "chunk_size": 500},
    )
    # Tidak wajib 200 (dependen konfigurasi provider LLM), tapi WAJIB bukan
    # 400 penolakan path.
    assert resp.status_code != 400, resp.text


def test_rag_ingest_error_is_explicit_not_silent_fallback(client, workspace, monkeypatch):
    """
    Bug lama: `except:` telanjang membuat path yang gagal dibaca diam-diam
    diperlakukan sebagai konten, jadi string path ikut masuk vector store.
    Path yang ADA tapi di luar allowlist harus error, bukan fallback diam.
    """
    resp = client.post(
        "/api/rag/ingest",
        json={"provider_id": "p-test", "files": [str(workspace["outside"] / "innocent.txt")], "chunk_size": 500},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Pesan harus menyebut path-nya, bukan diam-diam meng-embed string.
    assert "innocent.txt" in detail


# ---------------------------------------------------------------------------
# #63: proxy frontend
# ---------------------------------------------------------------------------
# Proxy-nya TypeScript, jadi diuji dari sisi frontend. Test Python di bawah
# mengunci Environment yang dia baca, supaya perubahan env tidak diam-diam
# mengubah perilaku proxy.

def test_proxy_env_defaults_are_safe(monkeypatch):
    """
    Token yang dipakai proxy harus punya nama env yang sama dengan yang dibaca
    backend. Kalau backend berubah nama dan proxy tidak, proxy diam-diam jadi
    pass-through tanpa token.
    """
    import auth

    assert "SYNAPSE_API_TOKEN" in Path(settings_store.BASE_DIR).joinpath("auth.py").read_text(
        encoding="utf-8"
    )
    assert hasattr(auth, "PUBLIC_PATHS")


def test_backend_still_requires_token_by_default():
    """
    Jaring pengaman: kalau PUBLIC_PATHS melebar lagi, proxy #63 jadi berarti.
    """
    import auth

    assert set(auth.PUBLIC_PATHS) <= {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
    }, f"PUBLIC_PATHS melebar lagi: {auth.PUBLIC_PATHS}"
