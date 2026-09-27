"""
test_issue_workspace_boundary.py — regression test untuk bypass proteksi path
lewat settings.workspace_path.

BUG: allowed_roots() menambahkan workspace_path dari settings apa adanya ke
allowlist. Karena workspace_path bisa diubah siapa saja lewat POST /settings,
satu panggilan itu sudah cukup untuk membuat SELURUH isi filesystem terbaca:

    POST /settings {"workspace_path": "C:\\\\"}
      -> allowed_roots() = [REPO_ROOT, "C:\\\\"]
      -> is_readable_path(path apa pun) = True
      -> /api/rag/ingest membaca file itu dan MENYIMPAN teksnya ke rag_chunks
      -> /api/rag/search mengembalikan teks itu ke pemanggil

Rantainya terverifikasi eksplisit sebelum fix: file "github.txt" berisi token
palsu di luar repo berhasil dibaca, dipecah jadi chunk, dan isinya keluar
lagi lewat /api/rag/search. Lapis kedua (_is_sensitive) tidak menolong karena
itu cuma memblokir daftar nama file tertentu.

Ini membatalkan proteksi path yang dibangun untuk #63/#66, jadi harus tetap
tertutup.

Yang SENGAJA tetap diizinkan:
  - path di dalam repo, termasuk default aplikasi ("./workspace")
  - path relatif, absolut di dalam repo, dan "."
  - root tambahan yang didaftarkan operator lewat env
    SYNAPSE_EXTRA_WORKSPACE_ROOTS -- ini keputusan deployment,
    bukan sesuatu yang bisa dipilih lewat request HTTP
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402
import settings as settings_store  # noqa: E402

TOKEN = "test-token-0123456789abcdef"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient dengan DB dan settings yang terisolasi per-test."""
    import database
    import main
    import storage
    from fastapi.testclient import TestClient

    monkeypatch.setattr(auth, "API_TOKEN", TOKEN, raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "synapse.db"))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "synapse_v2.db"))
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "synapse.db"))
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    storage.reset_conn()
    database.init_db()
    storage.init_db()

    with TestClient(main.app, raise_server_exceptions=False) as c:
        c.headers.update({auth.TOKEN_HEADER: TOKEN})
        yield c


# ---------------------------------------------------------------------------
# bypass harus tertutup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evil", [
    "..",
    "../..",
    "../../..",
    "/",
    "/etc",
    "/root",
    "/home",
    "C:\\",
    "C:\\Windows",
    "C:\\Users",
    "/tmp",
])
def test_workspace_path_outside_repo_rejected(client, evil, tmp_path, monkeypatch):
    """
    Menolak di level endpoint, dengan 400 yang jelas -- bukan diam-diam
    mengabaikan, supaya penetrate tahu kenapa setting-nya tidak berefek.
    """
    r = client.post("/settings", json={"workspace_path": evil})
    assert r.status_code == 400, (
        f"workspace_path={evil!r} diterima; harus 400. "
        "Kalau diterima, allowed_roots() ikut melebar."
    )
    assert "SYNAPSE_EXTRA_WORKSPACE_ROOTS" in r.json()["detail"]


def test_workspace_path_cannot_widen_allowed_roots(client, tmp_path, monkeypatch):
    """
    Uji perilaku, bukan cuma status code: setelah percobaan ditolak, file di
    luar repo tetap harus tidak terbaca.
    """
    outside = tmp_path / "luar-repo"
    outside.mkdir()
    target = outside / "github.txt"
    target.write_text("ghp_TOKENPALSU_RAHASIA_1234567890", encoding="utf-8")

    r = client.post("/settings", json={"workspace_path": str(outside)})
    assert r.status_code == 400
    assert settings_store.is_readable_path(str(target)) is False
    assert str(outside) not in [
        os.path.realpath(x) for x in settings_store.allowed_roots()
    ]


def test_no_unguarded_path_becomes_readable(client, tmp_path):
    """
    Menembak banyak path sekaligus dan memastikan tidak ada yang berubah
    jadi bisa dibaca.
    """
    guesses = [
        "/etc/passwd", "/etc/hosts", "/proc/self/environ",
        str(tmp_path), str(tmp_path.parent), os.path.expanduser("~"),
        str(Path.home()), "..", "../..",
    ]
    before = set(settings_store.allowed_roots())
    for path in guesses:
        client.post("/settings", json={"workspace_path": path})
    after = set(settings_store.allowed_roots())
    assert after == before, f"allowlist berubah: {after - before}"


def test_prefix_stuffing_rejected(client, tmp_path, monkeypatch):
    """
    "Synapse-evil" bukan "Synapse". Cek batas memakai os.sep, jadi path
    sejodoh di luar root tidak ikut terbaca.
    """
    sibling = settings_store.REPO_ROOT + "-evil"
    monkeypatch.setattr(settings_store, "REPO_ROOT", str(tmp_path / "repo"))
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo-evil").mkdir()

    assert settings_store.is_readable_path(
        str(tmp_path / "repo-evil" / "x.txt")
    ) is False
    assert settings_store.is_readable_path(
        str(tmp_path / "repo" / "x.txt")
    ) is True
    assert sibling  # hanya agar variabel terpakai


# ---------------------------------------------------------------------------
# use case sah harus tetap jalan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("workspace", [
    "./backend",
    "backend",
    ".",
    "./",
    "./workspace",
])
def test_workspace_inside_repo_accepted(client, workspace):
    """Default aplikasi dan path relatif di dalam repo harus tetap bisa."""
    r = client.post("/settings", json={"workspace_path": workspace})
    assert r.status_code == 200, f"{workspace!r} ditolak: {r.text[:200]}"


def test_repo_absolute_path_accepted(client):
    r = client.post("/settings", json={"workspace_path": settings_store.REPO_ROOT})
    assert r.status_code == 200


def test_file_inside_repo_still_readable(client):
    client.post("/settings", json={"workspace_path": "./backend"})
    target = os.path.join(settings_store.REPO_ROOT, "backend", "main.py")
    assert settings_store.is_readable_path(target) is True


def test_extra_roots_from_env_honored(client, tmp_path, monkeypatch):
    """
    Operator tetap bisa menambah workspace lewat env. Ini opted-in saat
    deployment, jadi fitur yang sah tidak ikut hilang.
    """
    extra = tmp_path / "workspace-eksternal"
    extra.mkdir()
    target = extra / "github.txt"
    target.write_text("kredensial yang sengaja diizinkan operator", encoding="utf-8")

    monkeypatch.setenv("SYNAPSE_EXTRA_WORKSPACE_ROOTS", str(extra))

    r = client.post("/settings", json={"workspace_path": str(extra)})
    assert r.status_code == 200, f"root dari env ditolak: {r.text[:200]}"
    assert settings_store.is_readable_path(str(target)) is True


def test_sibling_of_extra_root_rejected(client, tmp_path, monkeypatch):
    """
    Env root ekstra tidak berarti seluruh direktori_tu-nya ikut boleh.
    """
    parent = tmp_path / "parent"
    allowed = parent / "boleh"
    denied = parent / "tidak-boleh"
    allowed.mkdir(parents=True)
    denied.mkdir(parents=True)
    monkeypatch.setenv("SYNAPSE_EXTRA_WORKSPACE_ROOTS", str(allowed))

    r = client.post("/settings", json={"workspace_path": str(denied)})
    assert r.status_code == 400
    assert settings_store.is_readable_path(str(denied / "x.txt")) is False


def test_extra_roots_env_parsing(tmp_path, monkeypatch):
    """Env dibaca ulang tiap panggilan dan mengabaikan entri kosong."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("SYNAPSE_EXTRA_WORKSPACE_ROOTS", f"  {a} , ,{b}  ")
    roots = settings_store.extra_workspace_roots()
    assert os.path.realpath(str(a)) in roots
    assert os.path.realpath(str(b)) in roots
    assert len(roots) == 2


def test_extra_roots_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("SYNAPSE_EXTRA_WORKSPACE_ROOTS", raising=False)
    assert settings_store.extra_workspace_roots() == []


# ---------------------------------------------------------------------------
# Setting lain tidak ikut terpengaruh
# ---------------------------------------------------------------------------

def test_other_settings_still_settable(client):
    """Hanya workspace_path yang dibatasi; setting lain harus normal."""
    r = client.post("/settings", json={"platform_name": "Synapse Dev"})
    assert r.status_code == 200
    assert r.json()["settings"]["platform_name"] == "Synapse Dev"


def test_workspace_path_ignored_when_not_in_patch(client):
    """Patch tanpa workspace_path tidak boleh memicu penolakan."""
    r = client.post("/settings", json={"log_level": "DEBUG"})
    assert r.status_code == 200


def test_empty_patch_rejected(client):
    r = client.post("/settings", json={})
    assert r.status_code == 400
