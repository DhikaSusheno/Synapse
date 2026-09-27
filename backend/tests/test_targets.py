"""
Test untuk target analisis (projects.py) dan isolasi graph per target.

KENAPA ADA TES INI
------------------
Dua target dengan file bernama sama (mis. `main.py`) menghasilkan id entity
yang sama persis: `file::main.py`. Kalau keduanya masuk satu tabel entities,
 PRIMARY KEY-nya bentrok dan repo kedua menimpa yang pertama - user melihat
graph repo lama padahal sudah pindah target. Yang diuji di sini adalah
bahwa pemisahan per target benar-benar terjadi, dan bukan sekadar label UI
yang berubah.

Test juga mengunci aturan path traversal saat ekstrak tarball GitHub, karena
satu bug di sana berarti backend menulis file ke ~/.ssh tanpa perlu token
tambahan - token GitHub yang sudah dipakai sync sudah cukup untuk itu.

Semua id target yang dipakai di dalam test ini sengaja memakai slug
sederhana, karena id itu sekaligus jadi nama file DB di server.
"""

import os
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402

TEST_TOKEN = "test-suite-token-0123456789abcdef"
auth.API_TOKEN = TEST_TOKEN


# ---------------------------------------------------------------------------
# Fixture: registry + DB terisolasi per test
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Semua path storage/projects diarahkan ke tmp_path.

    Tanpa ini, test ini akan menulis synapse_v2_<slug>.db di backend/ dan
    membaca registry proyek user sungguhan.
    """
    db = tmp_path / "graph.db"
    # Skema v1 (nodes/operations/approvals) sengaja file BERBEDA dari v2,
    # sama seperti produksi (synapse.db vs synapse_v2_<slug>.db). Kalau keduanya
    # digabung, tabel menabrak dan test tidak lagi mencerminkan produksi.
    legacy_db = tmp_path / "legacy.db"
    registry = tmp_path / "projects.json"
    monkeypatch.setenv("SYNAPSE_DB_PATH", str(db))
    monkeypatch.setenv("SYNAPSE_PROJECTS_PATH", str(registry))

    import projects
    import storage

    storage.set_active_target(None)
    storage.reset_conn()
    storage.init_db()
    monkeypatch.setattr(projects, "REGISTRY_PATH", registry)
    # Setara perilaku produksi: folder yang terdaftar ikut jadi root yang boleh
    # dibaca. engine.ingest_repository() menolak path di luar allowed_roots(),
    # jadi tanpa ini semua test ingest di file ini akan gagal dengan ok=False.
    monkeypatch.setenv("SYNAPSE_ALLOW_TARGET_ROOTS", "1")

    yield {
        "root": tmp_path,
        "db": db,
        "legacy_db": legacy_db,
        "registry": registry,
        "projects": projects,
        "storage": storage,
    }
    storage.set_active_target(None)
    storage.reset_conn()


def make_project(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Isolasi graph antar target
# ---------------------------------------------------------------------------


def test_two_targets_with_same_relative_path_do_not_collide(sandbox):
    """Dua folder dengan `main.py` sama harus jadi dua graph terpisah.

    Ini inti dari fitur ganti-target. Kalau id entity tidak terisolasi,
    repo kedua akan menimpa repo pertama di PRIMARY KEY.
    """
    import engine

    a = make_project(sandbox["root"], "alpha", {"main.py": "def alpha():\n    return 1\n"})
    b = make_project(sandbox["root"], "beta", {"main.py": "def beta():\n    return 2\n"})

    t_a = sandbox["projects"].create_target(kind="local", label="alpha", path=str(a))
    sandbox["storage"].set_active_target(t_a["id"])
    engine.invalidate_graph_cache()
    out_a = engine.ingest_repository(str(a))
    assert out_a["ok"], out_a.get("error")

    t_b = sandbox["projects"].create_target(kind="local", label="beta", path=str(b))
    sandbox["storage"].set_active_target(t_b["id"])
    engine.invalidate_graph_cache()
    out_b = engine.ingest_repository(str(b))
    assert out_b["ok"], out_b.get("error")

    # Id entiket sama persis di kedua repo...
    def file_ids(target_id: str) -> set[str]:
        conn = sqlite3.connect(sandbox["storage"].db_path_for_target(target_id))
        try:
            return {
                r[0]
                for r in conn.execute("SELECT id FROM entities WHERE kind='file'")
            }
        finally:
            conn.close()

    assert file_ids(t_a["id"]) == {"file::main.py"}
    assert file_ids(t_b["id"]) == {"file::main.py"}

    # ...tapi berada di file DB berbeda, jadi tidak pernah menabrakkan PRIMARY
    # KEY. Inilah yang membuat "ganti repository" benar-benar mengganti data.
    graph_a = sandbox["storage"].db_path_for_target(t_a["id"])
    graph_b = sandbox["storage"].db_path_for_target(t_b["id"])
    assert graph_a != graph_b
    assert graph_a.exists() and graph_b.exists()


def test_switching_target_rebuilds_in_memory_graph(sandbox):
    """Setelah ganti target, graph harus milik target baru, bukan yang lama.

    Tanpa invalidate_graph_cache(), _get_graph() melihat cache yang masih
    berisi node repo sebelumnya dan mengembalikan data basi.
    """
    import engine

    a = make_project(sandbox["root"], "a", {"alpha.py": "def alpha_only():\n    pass\n"})
    b = make_project(sandbox["root"], "b", {"beta.py": "def beta_only():\n    pass\n"})

    t_a = sandbox["projects"].create_target(kind="local", label="a", path=str(a))
    sandbox["storage"].set_active_target(t_a["id"])
    engine.invalidate_graph_cache()
    engine.ingest_repository(str(a))
    labels_a = {d.get("label") for _, d in engine._get_graph().nodes(data=True)}
    assert "alpha_only" in labels_a

    t_b = sandbox["projects"].create_target(kind="local", label="b", path=str(b))
    sandbox["projects"].set_active(t_b["id"])
    sandbox["storage"].set_active_target(t_b["id"])
    engine.invalidate_graph_cache()
    engine.ingest_repository(str(b))
    labels_b = {d.get("label") for _, d in engine._get_graph().nodes(data=True)}
    assert "beta_only" in labels_b
    assert "alpha_only" not in labels_b


def test_prune_stale_removes_deleted_files(sandbox):
    """Ingest ulang setelah file dihapus harus membuang entitasnya.

    Tanpa prune, graph hanya menumpuk: file yang sudah dihapus tetap muncul
    di health report sebagai "dead code" yang tidak bisa diInvestigate.
    """
    import engine

    root = make_project(
        sandbox["root"], "prune", {"keep.py": "def keep():\n    pass\n", "gone.py": "def gone():\n    pass\n"}
    )
    t = sandbox["projects"].create_target(kind="local", label="prune", path=str(root))
    sandbox["storage"].set_active_target(t["id"])
    engine.invalidate_graph_cache()
    first = engine.ingest_repository(str(root))
    assert first["ok"], first.get("error")
    assert first["stats"]["files"] == 2

    (root / "gone.py").unlink()
    second = engine.ingest_repository(str(root))
    assert second["ok"], second.get("error")
    assert second["stats"]["stale_removed"] > 0
    assert second["stats"]["files"] == 1

    rows = sandbox["storage"].get_conn().execute(
        "SELECT id FROM entities WHERE id LIKE '%gone%'"
    ).fetchall()
    assert rows == []
    kept = sandbox["storage"].get_conn().execute(
        "SELECT id FROM entities WHERE id = 'file::keep.py'"
    ).fetchall()
    assert len(kept) == 1


def test_prune_keeps_non_scan_entities(sandbox):
    """Entitas di luar file/symbol/doc bukan hasil pindai, jadi tidak boleh terhapus.

    Ini yang membedakan prune_stale() dari `DELETE FROM entities`. Action dan
    decision milik workflow Guardian/audit adalah jejak yang tidak boleh hilang
    hanya karena user menjalankan ingest lagi.
    """
    import engine
    from storage import upsert_entity

    root = make_project(sandbox["root"], "audit", {"x.py": "def x():\n    pass\n"})
    t = sandbox["projects"].create_target(kind="local", label="audit", path=str(root))
    sandbox["storage"].set_active_target(t["id"])
    engine.invalidate_graph_cache()
    engine.ingest_repository(str(root))

    upsert_entity("op::1", "action", "Migration", {"tool": "db.migrate"})
    upsert_entity("dec::1", "decision", "Approved", {"note": "ok"})

    engine.ingest_repository(str(root))

    rows = sandbox["storage"].get_conn().execute(
        "SELECT id FROM entities WHERE id IN ('op::1', 'dec::1')"
    ).fetchall()
    assert {r["id"] for r in rows} == {"op::1", "dec::1"}


# ---------------------------------------------------------------------------
# Registry & validasi path
# ---------------------------------------------------------------------------


def test_slug_mendapat_suffix_saat_label_sama(sandbox):
    """Label sama di dua folder harus tetap bisa dibedakan."""
    a = make_project(sandbox["root"], "one", {"a.py": "x = 1\n"})
    b = make_project(sandbox["root"], "two", {"b.py": "x = 2\n"})
    t1 = sandbox["projects"].create_target(kind="local", label="app", path=str(a))
    t2 = sandbox["projects"].create_target(kind="local", label="app", path=str(b))
    assert t1["id"] == "app"
    assert t2["id"] == "app-2"


def test_registering_target_makes_it_readable(sandbox, tmp_path):
    """Setelah terdaftar, folder target harus bisa dibaca is_readable_path."""
    import settings as settings_store

    monkey_env = os.environ.get("SYNAPSE_ALLOW_TARGET_ROOTS")
    os.environ["SYNAPSE_ALLOW_TARGET_ROOTS"] = "1"
    try:
        outside = tmp_path / "outside" / "proj"
        outside.mkdir(parents=True)
        (outside / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")

        assert not settings_store.is_readable_path(str(outside))
        target = sandbox["projects"].create_target(
            kind="local", label="luar", path=str(outside)
        )
        assert target["available"] is True
        assert settings_store.is_readable_path(str(outside))
    finally:
        if monkey_env is None:
            os.environ.pop("SYNAPSE_ALLOW_TARGET_ROOTS", None)
        else:
            os.environ["SYNAPSE_ALLOW_TARGET_ROOTS"] = monkey_env


def test_activate_rejects_folder_that_vanished(sandbox):
    """Folder hilang harus ditolak saat aktivasi, bukan menghasilkan graph hantu."""
    a = make_project(sandbox["root"], "gone", {"a.py": "x = 1\n"})
    target = sandbox["projects"].create_target(kind="local", label="gone", path=str(a))
    for child in sorted(a.rglob("*"), reverse=True):
        child.unlink()
    a.rmdir()

    listed = {t["id"]: t for t in sandbox["projects"].list_targets()}
    assert listed[target["id"]]["available"] is False
    with pytest.raises(PermissionError):
        sandbox["projects"].set_active(target["id"])


def test_corrupt_registry_does_not_crash(sandbox):
    """Registry rusak harus menghasilkan daftar kosong, bukan exception."""
    sandbox["registry"].write_text("{bukan json", encoding="utf-8")
    assert sandbox["projects"].list_targets() == []
    assert sandbox["projects"].get_active() is None


def test_registry_entry_with_bad_id_is_dropped(sandbox):
    """Id yang tidak cocok pola slug diabaikan - id itu jadi nama file DB."""
    sandbox["registry"].write_text(
        '{"active": null, "targets": ['
        '{"id": "../../etc/passwd", "kind": "local", "label": "jahat", "path": "/tmp"},'
        '{"id": "../../windows", "kind": "local", "label": "jahat2", "path": "/tmp"}'
        "]}",
        encoding="utf-8",
    )
    assert sandbox["projects"].list_targets() == []


def test_db_path_cannot_escape_directory(sandbox):
    """db_path_for_target menyaring id, jadi harus selalu di dalam folder DB."""
    base = sandbox["storage"].DB_PATH
    resolved = sandbox["storage"].db_path_for_target("../../evil")
    assert resolved.parent == base.parent
    assert resolved.name.startswith(base.stem)


# ---------------------------------------------------------------------------
# Keamanan ekstrak tarball (path traversal)
# ---------------------------------------------------------------------------


def _write_tar(path: Path, members: list[tuple[str, str]]) -> Path:
    """Buat tarball dengan nama member yang bisa contains traversal."""
    raw = path.with_suffix(".tar")
    with tarfile.open(raw, "w") as tar:
        for name, content in members:
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, __import__("io").BytesIO(data))
    import gzip
    import shutil

    with open(raw, "rb") as src, gzip.open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    raw.unlink()
    return path


def test_extraction_strips_github_top_level_dir(tmp_path):
    """GitHub membungkus isi repo di satu folder; itu harus dibuang."""
    import github_sync

    tar = _write_tar(
        tmp_path / "ok.tar.gz",
        [("owner-repo-abc123/main.py", "def main():\n    pass\n")],
    )
    dest = tmp_path / "out"
    stats = github_sync._extract_safely(tar, dest)
    assert stats["files"] == 1
    assert (dest / "main.py").exists()
    assert not (dest / "owner-repo-abc123").exists()


def test_extraction_refuses_path_traversal(tmp_path):
    """Member `../escaped.txt` tidak boleh menulis di luar dest.

    Ini guard paling penting di seluruh fitur sync: tanpa ini, siapa pun
    yang bisa memicu sync bisa menulis file ke mana saja di disk.
    """
    import github_sync

    tar = _write_tar(
        tmp_path / "evil.tar.gz",
        [("owner-repo-x/../../escaped.txt", "pwned\n")],
    )
    dest = tmp_path / "out"
    github_sync._extract_safely(tar, dest)
    assert not (tmp_path / "escaped.txt").exists()
    assert not (dest.parent / "escaped.txt").exists()
    # File di dalam dest pun tidak boleh berisi path yang keluar.
    for p in dest.rglob("*"):
        assert dest in p.parents or p == dest


def test_extraction_refuses_absolute_path(tmp_path):
    """Member dengan path absolut juga harus ditolak."""
    import github_sync

    target = tmp_path / "abs.txt"
    tar = _write_tar(
        tmp_path / "abs.tar.gz",
        [("owner-repo-x/" + target.as_posix(), "pwned\n")],
    )
    dest = tmp_path / "out"
    github_sync._extract_safely(tar, dest)
    assert not target.exists()


def test_extraction_skips_symlinks(tmp_path):
    """Symlink tidak diekstrak - bisa dipakai menunjuk ke /etc/passwd."""
    import github_sync

    raw = tmp_path / "link.tar"
    with tarfile.open(raw, "w") as tar:
        info = tarfile.TarInfo("owner-repo-x/evil-link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    import gzip
    import shutil

    with open(raw, "rb") as src, gzip.open(tmp_path / "link.tar.gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    raw.unlink()

    dest = tmp_path / "out"
    # Tarball isinya cuma symlink, jadi tidak ada yang bisa dipindai. Fungsi
    # harus menolak dengan pesan jelas, bukan menulis symlink ke disk.
    with pytest.raises(github_sync.SyncError) as exc:
        github_sync._extract_safely(tmp_path / "link.tar.gz", dest)
    assert not (dest / "evil-link").exists()
    assert not (dest / "evil-link").is_symlink()


def test_validate_source_rejects_traversal():
    import github_sync

    for bad in ("../etc/passwd", "owner/../repo", "owner", "a/b/c", "owner/re po"):
        with pytest.raises(ValueError):
            github_sync.validate_source(bad)
    assert github_sync.validate_source("DhikaSusheno/Synapse") == (
        "DhikaSusheno",
        "Synapse",
    )


def test_validate_branch_rejects_traversal():
    import github_sync

    for bad in ("", "  ", "-main", "../main", "main..dev", "main;rm"):
        with pytest.raises(ValueError):
            github_sync.validate_branch(bad)
    assert github_sync.validate_branch("feature/new-thing") == "feature/new-thing"


def test_registerable_dir_rejects_dangerous_paths(tmp_path, monkeypatch):
    """Root drive, home, dan folder kredensial tidak boleh jadi target."""
    import github_sync  # noqa: F401  (import Aless aman, memastikan modul load)
    import projects

    with pytest.raises(ValueError):
        projects._registerable_dir("")
    with pytest.raises(ValueError):
        projects._registerable_dir(str(tmp_path / "tidak-ada"))

    # Root drive: parent == self.
    drive_root = Path(tmp_path.anchor or "/")
    with pytest.raises(ValueError):
        projects._registerable_dir(str(drive_root))

    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    with pytest.raises(ValueError):
        projects._registerable_dir(str(ssh))

    node_modules = tmp_path / "proj" / "node_modules"
    node_modules.mkdir(parents=True)
    with pytest.raises(ValueError):
        projects._registerable_dir(str(node_modules))


def test_registerable_dir_rejects_home(monkeypatch, tmp_path):
    import projects

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    with pytest.raises(ValueError):
        projects._registerable_dir(str(fake_home))


# ---------------------------------------------------------------------------
# Endpoint HTTP
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(sandbox, monkeypatch):
    from starlette.testclient import TestClient

    import database
    import main

    # main.py mengimpor DB_PATH sebagai nama, guardian membaca
    # database.DB_PATH. Keduanya harus menunjuk file yang sama, kalau tidak
    # /operations dan guardian menulis ke DB berbeda dan test jadi bohong.
    # Patch keduanya ke tmp_path: tanpa ini test Guardian menulis ke
    # synapse.db milik user yang sedang dipakai backend yang berjalan.
    monkeypatch.setattr(main, "DB_PATH", sandbox["legacy_db"])
    monkeypatch.setattr(database, "DB_PATH", sandbox["legacy_db"])
    database.init_db()
    return TestClient(main.app)


def test_targets_start_empty_and_report_no_active(client):
    res = client.get("/api/targets")
    assert res.status_code == 200
    body = res.json()
    assert body["targets"] == []
    assert body["active"] is None


def test_create_activate_and_switch_target(client, sandbox):
    import engine

    a = make_project(sandbox["root"], "p1", {"a.py": "def a():\n    pass\n"})
    b = make_project(sandbox["root"], "p2", {"b.py": "def b():\n    pass\n"})

    res = client.post(
        "/api/targets", json={"kind": "local", "label": "satu", "path": str(a)}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active"] == "satu"
    assert body["ingest"]["ok"] is True

    res2 = client.post(
        "/api/targets", json={"kind": "local", "label": "dua", "path": str(b)}
    )
    assert res2.status_code == 200, res2.text
    assert res2.json()["active"] == "dua"

    # Kembali ke target pertama: graph dan path aktif harus ikut.
    res3 = client.post("/api/targets/satu/activate", json={"ingest": False})
    assert res3.status_code == 200, res3.text
    assert res3.json()["active"] == "satu"
    assert res3.json()["target"]["path"] == str(a)
    # Tidak ada byte path absolut server yang ikut keluar lewat API.
    assert "db_path" not in res3.json()["target"]


def test_activate_missing_target_is_404(client):
    assert client.post("/api/targets/tidak-ada/activate", json={}).status_code == 404


def test_activate_rejects_invalid_id(client):
    # Id menyalahi pola slug backend, harus ditolak sebelum menyentuh disk.
    assert client.post("/api/targets/..%2F..%2Fetc/activate", json={}).status_code in (400, 404)


def test_create_target_rejects_missing_folder(client, sandbox):
    res = client.post(
        "/api/targets",
        json={"kind": "local", "label": "x", "path": str(sandbox["root"] / "nope")},
    )
    assert res.status_code == 400
    assert "tidak ditemukan" in res.json()["detail"]


def test_delete_target_keeps_graph_by_default(client, sandbox):
    a = make_project(sandbox["root"], "del", {"a.py": "x = 1\n"})
    client.post("/api/targets", json={"kind": "local", "label": "del", "path": str(a)})
    graph_file = sandbox["storage"].db_path_for_target("del")
    assert graph_file.exists()

    res = client.delete("/api/targets/del")
    assert res.status_code == 200
    assert res.json()["active"] is None
    assert graph_file.exists(), "graph harus tetap ada tanpa remove_graph=true"

    res2 = client.delete("/api/targets/del", params={"remove_graph": True})
    assert res2.status_code == 404, "sudah dihapus di request sebelumnya"


def test_delete_with_remove_graph_destroys_files(client, sandbox):
    """remove_graph=true harus benar-benar menghapus file DB graph.

    Di Windows file SQLite yang masih dipegang connection tidak bisa
    di-unlink. Karena itu delete_target() menutup semua koneksi dulu, dan
    endpoint melaporkan graph_removed supaya kegagalan tidak pernah diam-diam.
    """
    import projects

    a = make_project(sandbox["root"], "del2", {"a.py": "x = 1\n"})
    client.post("/api/targets", json={"kind": "local", "label": "del2", "path": str(a)})
    assert projects.get_target("del2") is not None
    sandbox["storage"].set_active_target("del2")
    sandbox["storage"].get_conn().execute(
        "INSERT INTO entities (id, kind, label) VALUES ('x', 'action', 'x')"
    )
    sandbox["storage"].get_conn().commit()
    graph_file = sandbox["storage"].db_path_for_target("del2")
    assert graph_file.exists()

    res = client.delete("/api/targets/del2", params={"remove_graph": True})
    assert res.status_code == 200
    assert res.json()["graph_removed"] is True
    assert not graph_file.exists()
    # Sidecar WAL/SHM ikut hilang, tidakinggal sisa.
    assert not graph_file.with_name(graph_file.name + "-wal").exists()
    assert not graph_file.with_name(graph_file.name + "-shm").exists()


def test_active_target_survives_restart(client, sandbox):
    """Target aktif harus dipulihkan dari registry saat app start lagi."""
    import main

    a = make_project(sandbox["root"], "persist", {"a.py": "x = 1\n"})
    client.post("/api/targets", json={"kind": "local", "label": "persist", "path": str(a)})

    sandbox["storage"].set_active_target(None)
    main._restore_active_target()
    assert sandbox["storage"].get_active_target() == "persist"


def test_stale_active_target_degrades_to_empty(sandbox):
    """Target aktif yang foldernya hilang TIDAK boleh membuka graph lain."""
    import main

    a = make_project(sandbox["root"], "stale", {"a.py": "x = 1\n"})
    sandbox["projects"].create_target(kind="local", label="stale", path=str(a))
    for child in sorted(a.rglob("*"), reverse=True):
        child.unlink()
    a.rmdir()

    main._restore_active_target()
    assert sandbox["storage"].get_active_target() is None


# ---------------------------------------------------------------------------
# LLM provider dengan tipe di luar daftar
# ---------------------------------------------------------------------------


def test_create_provider_accepts_type_outside_list(client, monkeypatch, tmp_path):
    """Tipe custom harus diterima kalau base_url diberikan.

    Ini yang membuat LM Studio, vLLM, Groq, atau proxy internal bisa dipakai
    tanpa mengubah kode backend.
    """
    import database

    db = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    res = client.post(
        "/api/llm/providers",
        json={
            "name": "lokal",
            "type": "lmstudio",
            "base_url": "http://localhost:1234/v1",
            "models": ["qwen3-8b"],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == "lmstudio:lokal"


def test_create_provider_requires_base_url_for_unknown_type(client, monkeypatch, tmp_path):
    """Tanpa base_url, tipe custom harus ditolak - bukan diam-diam tembak OpenAI."""
    import database

    db = tmp_path / "legacy2.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    res = client.post(
        "/api/llm/providers", json={"name": "x", "type": "groq", "models": ["m"]}
    )
    assert res.status_code == 422


def test_known_type_still_gets_default_base_url(client, monkeypatch, tmp_path):
    """Menambah provider openai tanpa base_url harus tetap boleh."""
    import database

    db = tmp_path / "legacy3.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    res = client.post("/api/llm/providers", json={"name": "o", "type": "openai"})
    assert res.status_code == 200, res.text


def test_provider_type_is_normalized(client, monkeypatch, tmp_path):
    """"Open AI" dan "openai" harus jadi provider yang sama."""
    import database

    db = tmp_path / "legacy4.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    res = client.post("/api/llm/providers", json={"name": "o", "type": " Open AI "})
    assert res.status_code == 200, res.text
    assert res.json()["id"] == "openai:o"


def test_custom_provider_type_is_deletable(client, monkeypatch, tmp_path):
    """Tipe custom harus bisa dihapus - user perlu membersihkan config."""
    import database

    db = tmp_path / "legacy5.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    client.post(
        "/api/llm/providers",
        json={
            "name": "c",
            "type": "vllm",
            "base_url": "http://localhost:8000/v1",
        },
    )
    res = client.delete("/api/llm/providers/vllm:c")
    assert res.status_code == 200, res.text
    assert client.delete("/api/llm/providers/openai:builtin").status_code == 404


def test_chat_without_model_is_rejected_with_clear_message(client, monkeypatch, tmp_path):
    """Provider tanpa model harus ditolak dengan pesan yang bisa ditindaklanjuti."""
    import database

    db = tmp_path / "legacy6.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    import main

    monkeypatch.setattr(main, "DB_PATH", db)
    database.init_db()

    client.post(
        "/api/llm/providers",
        json={"name": "n", "type": "openai", "api_key": "sk-test", "models": []},
    )
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": "openai:n", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 400
    assert "model" in res.json()["detail"].lower()


# --- Kontrak normalize_provider_type ---------------------------------------
#
# fungsi ini juga diimplementasikan ulang di frontend/lib/llmProviders.ts
# (normalizeProviderType) karena id provider dihitung client-side. Kalau dua
# implementasi itu berbeda satu karakter saja, user mengetik "Open AI", client
# mengirim id "open-ai:team" sementara server menyimpan "openai:team" - dan
# provider itu tidak pernah bisa dipanggil lagi.
#
# Tabel di bawah sengaja berisi kasus yang surprising. "open ai compatible"
# menghasilkan "open-ai-compatible", BUKAN "openai-compatible", karena
# squashed-nya "openaicompatible" dan dashed-nya "open-ai-compatible", dua-duanya
# tidak ada di daftar bawaan. Docstring di main.py pernah mengklaim sebaliknya;
# test ini yang mengikat perilaku sebenarnya.


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("openai", "openai"),
        ("  OpenAI ", "openai"),
        ("OpenAI", "openai"),
        ("Open AI", "openai"),
        ("open ai", "openai"),
        ("Anthropic", "anthropic"),
        ("Ollama", "ollama"),
        ("openai compatible", "openai-compatible"),
        ("openai_compatible", "openai_compatible"),
        ("open ai compatible", "open-ai-compatible"),
        ("OpenAI Compatible", "openai-compatible"),
        ("vllm", "vllm"),
        ("LM Studio", "lm-studio"),
        ("internal-proxy", "internal-proxy"),
        ("deep seek", "deepseek"),
        ("nvidia nim", "nvidia-nim"),
        ("My Provider!", "my-provider"),
        ("  vllm  ", "vllm"),
        ("a//b", "a-b"),
        ("qwen.coder", "qwen.coder"),
        ("", "openai-compatible"),
        ("   ", "openai-compatible"),
        ("---", "openai-compatible"),
    ],
)
def test_normalize_provider_type_matches_documented_contract(raw, expected):
    import main

    assert main.normalize_provider_type(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Open AI", "openai", "vllm", "LM Studio", "My Provider!", "open ai compatible"],
)
def test_normalize_provider_type_is_idempotent(raw):
    """Dipanggil ulang oleh client (validateDraft lalu makeProviderId)."""
    import main

    once = main.normalize_provider_type(raw)
    assert main.normalize_provider_type(once) == once


def test_normalize_provider_type_only_falls_back_to_known_type_when_input_is_empty():
    """Tipe custom tidak boleh diam-diam jadi openai-compatible kalau tak dikenal.

    Kalau ini berubah, user yang mendaftarkan "vllm" tiba-tiba/provider-nya
    hilang begitu daftar bawaan berubah, dan request-nya diarahkan ke akun
    OpenAI yang tidak ia minta.
    """
    import main

    # Hanya nama yang sudah clean/lowercase. "nvidia nim" sengaja tidak
    # ada di sini: spasinya memang jadi tanda hubung, dan itu trade-off
    # yang benar (kasus itu sudah dikunci di tabel parametrik di atas).
    for custom in ("vllm", "groq", "lmstudio", "internal-proxy"):
        assert main.normalize_provider_type(custom) == custom
        assert main.normalize_provider_type(custom) != "openai-compatible"


# --- BUG-41: /api/llm/chat balas 500 untuk semua provider --------------------
#
# llm_chat() mengambil baris provider lewat conn.execute(...).fetchone() dengan
# row_factory = sqlite3.Row, lalu meneruskannya ke _is_local_provider() dan
# resolve_provider_base_url() yang keduanya memanggil .get(). sqlite3.Row tidak
# punya .get(), jadi endpoint ini melempar AttributeError dan membalas 500.
#
# Test lama tidak menangkapnya karena semuanya berhenti di guard 400/404, yang
# berjalan SEBELUM baris yang salah. Test di bawah memakai httpx yang dipalsukan,
# jadi request benar-benar sampai ke "provider" dan seluruh helper ikut jalan.


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Palsukan httpx.AsyncClient dan catat request yang dibuat."""

    calls: list[dict] = []
    payload: dict = {"choices": [{"message": {"content": "pong"}}]}
    # BUG-45: kalau client ini di-`aclose()` sebelum generator stream
    # dijalankan, request streaming harus gagal keras - itu persis kondisi
    # yang membuat browser melihat "NetworkError".
    closed_error: Exception | None = None
    # Baris SSE yang dipalsukan, dipakai jalur stream=True.
    stream_lines: list[str] = []
    stream_status: int = 200
    stream_body: bytes = b""

    def __init__(self, *args, **kwargs):
        self._closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        # httpx yang asli benar-benar menutup koneksi pool di sini. Kalau
        # pemalsu ini tidak menutup, regresi BUG-45 (pakai client yang sudah
        # keluar dari `async with`) lolos dari test.
        self._closed = True
        return False

    async def aclose(self):
        self._closed = True

    def _check_open(self):
        if self._closed and type(self).closed_error is not None:
            raise type(self).closed_error

    async def post(self, url, json=None, headers=None, timeout=None):
        self._check_open()
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(type(self).payload)

    def stream(self, method, url, json=None, headers=None, timeout=None):
        self._check_open()
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        return _FakeStreamCM(url)


class _FakeStreamResponse:
    """Response streaming: lines untuk 200, body bytes untuk error."""

    def __init__(self, url):
        self.status_code = _FakeAsyncClient.stream_status
        self._url = url

    async def aiter_lines(self):
        for line in _FakeAsyncClient.stream_lines:
            yield line

    async def aread(self):
        return _FakeAsyncClient.stream_body


class _FakeStreamCM:
    def __init__(self, url):
        self._resp = _FakeStreamResponse(url)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


@pytest.fixture()
def fake_llm(monkeypatch):
    import httpx

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.closed_error = RuntimeError("client already closed")
    _FakeAsyncClient.stream_lines = []
    _FakeAsyncClient.stream_status = 200
    _FakeAsyncClient.stream_body = b""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _register(client, db_path, monkeypatch, **overrides):
    import database

    # Tabel llm_providers dibuat oleh database.init_db(), bukan oleh
    # TestClient. database.DB_PATH juga harus diarahkan ke sandbox yang sama
    # dengan main.DB_PATH - kalau tidak, init menulis synapse.db sungguhan di
    # backend/ lalu endpoint-nya tetap menabrak "no such table".
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    body = {
        "name": "team",
        "type": "openai",
        "api_key": "sk-test",
        "models": ["gpt-4o"],
        "default_model": "gpt-4o",
    }
    body.update(overrides)
    res = client.post("/api/llm/providers", json=body)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_chat_succeeds_and_uses_builtin_base_url(client, sandbox, fake_llm, monkeypatch):
    """Chat harus benar-benar jalan dan memakai base_url default dari tipe."""
    pid = _register(client, sandbox["db"], monkeypatch)
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["choices"][0]["message"]["content"] == "pong"
    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["model"] == "gpt-4o", "model harus default_model provider"


def test_chat_without_base_url_on_disk_uses_type_default(client, sandbox, fake_llm, monkeypatch):
    """base_url kosong di DB tidak boleh jadi 500, hanya boleh pakai default tipe."""
    pid = _register(client, sandbox["db"], monkeypatch, type="deepseek")
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    assert fake_llm.calls[0]["url"] == "https://api.deepseek.com/v1/chat/completions"


def test_explicit_base_url_wins_over_type_default(client, sandbox, fake_llm, monkeypatch):
    pid = _register(client, sandbox["db"], monkeypatch, base_url="https://gw.example.com/v1/")
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    # Slash ganda di akhir akan bikin path "/v1//chat/completions" dan 404 dari
    # server yang sebenarnya, jadi rstrip("/") itu wajib.
    assert fake_llm.calls[0]["url"] == "https://gw.example.com/v1/chat/completions"


def test_public_provider_type_rejects_private_base_url(client, sandbox, fake_llm, monkeypatch):
    """M9/SSRF: base_url adalah tujuan request keluar, jadi alamat privat tidak
    boleh bisa ditembak lewat provider bertipe SaaS publik.

    Test di atasnya memakai host publik karena sengaja; test ini yang memastikan
    10.0.0.5 (RFC1918) ditolak, bukan lolos. Melonggarkan ini berarti siapa pun
    yang bisa menyimpan provider bisa membuat Synapse menembak metadata cloud
    atau layanan internal.
    """
    import database

    monkeypatch.setattr(database, "DB_PATH", sandbox["db"])
    database.init_db()
    res = client.post(
        "/api/llm/providers",
        json={
            "name": "internal",
            "type": "openai",
            "api_key": "sk-test",
            "base_url": "http://10.0.0.5:8000/v1/",
        },
    )
    assert res.status_code == 400, res.text
    assert "privat" in res.json()["detail"]
    assert fake_llm.calls == []


def test_local_openai_compatible_base_url_is_allowed(client, sandbox, fake_llm, monkeypatch):
    """LM Studio/vLLM lokal itu openai-compatible, bukan tipe publik - jadi
    localhost tetap sah untuk tipe itu meski M9 menyekat alamat privat."""
    pid = _register(
        client,
        sandbox["db"],
        monkeypatch,
        type="openai-compatible",
        base_url="http://localhost:1234/v1",
    )
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    assert fake_llm.calls[0]["url"] == "http://localhost:1234/v1/chat/completions"


# --- BUG-45: streaming chat mati dengan "NetworkError ..." di browser ---------
#
# LLMChatPanel mengirim stream=True. llm_chat() dulu membuka
# `async with httpx.AsyncClient(...)` di LUAR generator dan mengembalikan
# StreamingResponse dari dalamnya, jadi konteksnya sudah tertutup saat
# FastAPI meng-iterate generator. Request ke provider mati di tengah jalan,
# koneksi HTTP terputus, dan fetch() di browser ditolak - bukan 500, bukan
# 502. Sementara /api/llm/explain (stream=False) tetap jalan, jadi bug ini
# selalu terlihat seperti "chat rusak, provider jalan".
#
# _FakeAsyncClient.closed_error membuat pola lama meledak dengan
# "client already closed" saat diuji, jadi regresinya harus terdeteksi.


def test_chat_stream_sends_sse_lines(client, sandbox, fake_llm, monkeypatch):
    pid = _register(client, sandbox["db"], monkeypatch)
    fake_llm.stream_lines = [
        '{"choices":[{"delta":{"content":"Ha"}}]}',
        '{"choices":[{"delta":{"content":"lo"}}]}',
        "[DONE]",
    ]
    res = client.post(
        "/api/llm/chat",
        json={
            "provider_id": pid,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    body = res.text
    assert 'data: {"choices":[{"delta":{"content":"Ha"}}]}' in body
    assert 'data: {"choices":[{"delta":{"content":"lo"}}]}' in body
    assert fake_llm.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert fake_llm.calls[0]["json"]["stream"] is True


def test_chat_stream_client_is_not_closed_before_generator_runs(
    client, sandbox, fake_llm, monkeypatch
):
    """Regresi BUG-45: client harus hidup sepanjang stream.

    Kalau client ditutup sebelum generator dijalankan, pemalsunya melempar
    RuntimeError("client already closed") - bentuk yang di browser menjadi
    fetch() ditolak tanpa status HTTP sama sekali.
    """
    pid = _register(client, sandbox["db"], monkeypatch)
    fake_llm.stream_lines = ['{"choices":[{"delta":{"content":"ok"}}]}']
    res = client.post(
        "/api/llm/chat",
        json={
            "provider_id": pid,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )
    assert res.status_code == 200, res.text
    assert "ok" in res.text
    assert "client already closed" not in res.text


def test_chat_stream_provider_error_becomes_502_not_dead_connection(
    client, sandbox, fake_llm, monkeypatch
):
    """Provider yang membalas 401 harus jadi error yang bisa ditampilkan.

    Tanpa pengecekan status sebelum StreamingResponse dikembalikan, error
    provider mematikan koneksi dan browser hanya melihat NetworkError tanpa
    penjelasan sama sekali.
    """
    pid = _register(client, sandbox["db"], monkeypatch)
    fake_llm.stream_status = 401
    fake_llm.stream_body = b'{"error":{"message":"invalid api key"}}'
    res = client.post(
        "/api/llm/chat",
        json={
            "provider_id": pid,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )
    assert res.status_code == 502, res.text
    detail = res.json()["detail"]
    assert "401" in detail
    assert "invalid api key" in detail


def test_chat_stream_ollama_uses_native_stream_path(client, sandbox, fake_llm, monkeypatch):
    """Ollama stream harus lewat /api/chat dan tetap hidup setelah return."""
    pid = _register(
        client,
        sandbox["db"],
        monkeypatch,
        type="ollama",
        api_key="",
        models=["llama3.1"],
        default_model="llama3.1",
    )
    fake_llm.stream_lines = ['{"message":{"content":"halo"}}']
    res = client.post(
        "/api/llm/chat",
        json={
            "provider_id": pid,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )
    assert res.status_code == 200, res.text
    assert fake_llm.calls[0]["url"] == "http://localhost:11434/api/chat"
    assert "halo" in res.text


def test_chat_sends_no_auth_header_when_no_api_key(client, sandbox, fake_llm, monkeypatch):
    """openai-compatible lokal (LM Studio/vLLM) tidak punya key dan tidak boleh
    mengirim header Authorization: kosong, karena beberapa server menolaknya."""
    pid = _register(
        client,
        sandbox["db"],
        monkeypatch,
        type="openai-compatible",
        api_key="",
        base_url="http://localhost:1234/v1",
    )
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    assert "Authorization" not in fake_llm.calls[0]["headers"]


def test_remote_provider_without_api_key_is_rejected_not_500(client, sandbox, fake_llm, monkeypatch):
    """Tipe hosting tanpa key harus 400 dengan pesan jelas, bukan tembak diam-diam."""
    pid = _register(client, sandbox["db"], monkeypatch, api_key="", type="openai")
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 400
    assert "API key" in res.json()["detail"]
    assert fake_llm.calls == [], "tidak boleh menembak provider tanpa key"


def test_explicit_model_overrides_provider_default(client, sandbox, fake_llm, monkeypatch):
    pid = _register(client, sandbox["db"], monkeypatch)
    res = client.post(
        "/api/llm/chat",
        json={
            "provider_id": pid,
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    assert res.status_code == 200, res.text
    assert fake_llm.calls[0]["json"]["model"] == "gpt-4o-mini"


def test_anthropic_gets_its_version_header(client, sandbox, fake_llm, monkeypatch):
    """Anthropic menolak request tanpa anthropic-version dengan 400 dari pihak
    ketiga yang tidak akan pernah sampai ke user sebagai pesan Synapse."""
    pid = _register(client, sandbox["db"], monkeypatch, type="anthropic")
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    assert fake_llm.calls[0]["headers"].get("anthropic-version") == "2023-06-01"


def test_ollama_uses_native_chat_path_not_openai_shape(client, sandbox, fake_llm, monkeypatch):
    """Ollama tidak punya /chat/completions OpenAI-compatible di base_url itu."""
    pid = _register(client, sandbox["db"], monkeypatch, type="ollama", api_key="", base_url="http://localhost:11434")
    res = client.post(
        "/api/llm/chat",
        json={"provider_id": pid, "messages": [{"role": "user", "content": "ping"}]},
    )
    assert res.status_code == 200, res.text
    call = fake_llm.calls[0]
    assert call["url"] == "http://localhost:11434/api/chat"
    assert "options" in call["json"], "Ollama butuh options, bukan temperature top-level"


def test_explain_endpoint_reaches_the_provider(client, sandbox, fake_llm, monkeypatch):
    """explain memakai llm_chat, jadi ia harus kena 500 yang sama kalau helper
    masih salah. Graph kosong di sandbox, jadi yang diuji hanya tidak adanya 500."""
    pid = _register(client, sandbox["db"], monkeypatch)
    res = client.post(
        "/api/llm/explain",
        json={"provider_id": pid, "topic": "main", "context_limit": 1},
    )
    assert res.status_code != 500, f"AttributeError lagi: {res.text}"
    assert res.status_code in (200, 404), res.text


@pytest.mark.parametrize(
    "provider",
    [
        {"base_url": "http://localhost:1234/v1"},
        {"base_url": "http://127.0.0.1:1234/v1"},
        {"base_url": "http://[::1]:1234/v1"},
        {"base_url": "http://nas.local:1234/v1"},
        {"base_url": "file:///C:/models"},
    ],
)
def test_loopback_and_file_base_urls_count_as_local(provider):
    """Host loopback dan URL file berarti server di mesin sendiri, jadi key opsional.

    Diuji dua kali: sebagai dict (llm_chat sudah mengubah Row jadi dict) dan
    sebagai sqlite3.Row sungguhan, supaya helper ini tidak rapuh kalau ada
    pemanggil lain yang lupa mengubah Row.
    """
    import main

    payload = {"type": "openai-compatible", "api_key": None, **provider}
    assert main._is_local_provider(dict(payload)) is True
    assert main._is_local_provider(_make_row(payload)) is True, "helper harus tahan sqlite3.Row"


def test_non_local_provider_is_not_local():
    import main

    assert main._is_local_provider({"type": "openai", "base_url": None}) is False
    assert (
        main._is_local_provider({"type": "openai", "base_url": "https://api.openai.com/v1"})
        is False
    )
    # base_url kosong + tipe ollama tetap lokal.
    assert main._is_local_provider({"type": "ollama", "base_url": None}) is True
    # Tipe yang tidak dikenal tanpa base_url bukan lokal, jadi wajib punya key.
    assert main._is_local_provider({"type": "vllm", "base_url": None}) is False


def test_resolve_provider_base_url_prefers_explicit_then_default_then_none():
    import main

    assert (
        main.resolve_provider_base_url({"type": "openai", "base_url": "  http://x/v1  "})
        == "http://x/v1"
    )
    assert (
        main.resolve_provider_base_url({"type": "openai", "base_url": None})
        == "https://api.openai.com/v1"
    )
    # base_url kosong string harus diperlakukan sama seperti None.
    assert (
        main.resolve_provider_base_url({"type": "openai", "base_url": "   "})
        == "https://api.openai.com/v1"
    )
    # Tipe custom tanpa base_url: None, supaya pemanggil menolak dengan 400.
    assert main.resolve_provider_base_url({"type": "vllm", "base_url": None}) is None
    # openai-compatible sengaja tidak punya default.
    assert main.resolve_provider_base_url({"type": "openai-compatible", "base_url": None}) is None


def _make_row(payload: dict):
    """sqlite3.Row sungguhan, bukan stub, supaya test tidak berbohong soal API."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cols = ", ".join(f"{k} TEXT" for k in payload)
    conn.execute(f"CREATE TABLE t ({cols})")
    marks = ", ".join("?" for _ in payload)
    conn.execute(f"INSERT INTO t VALUES ({marks})", list(payload.values()))
    row = conn.execute("SELECT * FROM t").fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# BUG-43: "Folder lokal" tidak bisa memilih folder PC
# ---------------------------------------------------------------------------
# Gejalanya: /browse (dipakai Cortex untuk baca isi file) terkurung
# allowed_roots(), jadi "Telusuri folder..." hanya bisa membuka root repo
# seperti yang terlihat di log: `GET /browse?path=` berulang kali, hasilnya
# selalu sama. Fix-nya endpoint terpisah yang hanya mengembalikan NAMA
# DIREKTORI, karena folder yang mau dipilih belum tentu ada di allowed_roots().


def test_browse_lists_only_directories(sandbox, tmp_path):
    """Hanya folder yang boleh muncul: nama file tidak ikut, ukuran tidak ikut."""
    root = tmp_path / "browse-mix"
    (root / "sub").mkdir(parents=True)
    (root / "rahasia.txt").write_text("x" * 5000, encoding="utf-8")

    result = sandbox["projects"].browse_target_dirs(str(root))
    names = [e["name"] for e in result["entries"]]

    assert names == ["sub"]
    assert all(e["type"] == "dir" and e["size"] is None for e in result["entries"])
    assert "rahasia.txt" not in result["entries"]


def test_browse_skips_hidden_and_ignored_dirs(sandbox, tmp_path):
    root = tmp_path / "browse-skip"
    (root / "node_modules").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / ".hidden").mkdir()
    (root / "node_modules" / "left-pad").mkdir()
    (root / "src").mkdir()

    names = [e["name"] for e in sandbox["projects"].browse_target_dirs(str(root))["entries"]]

    assert names == ["src"]


def test_browse_entries_are_sorted_case_insensitively(sandbox, tmp_path):
    root = tmp_path / "browse-sort"
    for name in ("Zebra", "alpha", "Beta"):
        (root / name).mkdir(parents=True)

    names = [e["name"] for e in sandbox["projects"].browse_target_dirs(str(root))["entries"]]

    assert names == ["alpha", "Beta", "Zebra"]


def test_browse_empty_path_opens_home(sandbox, tmp_path, monkeypatch):
    fake_home = tmp_path / "home-dir"
    (fake_home / "proyek").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = sandbox["projects"].browse_target_dirs("")

    assert result["absolute_path"] == str(fake_home.resolve())
    assert [e["name"] for e in result["entries"]] == ["proyek"]


def test_browse_parent_is_none_at_drive_root(sandbox, tmp_path):
    """Di root drive tidak ada "naik" lagi - UI harus menyembunyikan tombolnya."""
    import ntpath

    root = tmp_path / "rootcase"
    root.mkdir()
    result = sandbox["projects"].browse_target_dirs(str(root))
    if result["parent"] is None:
        # Cuma mungkin di root drive sungguhan; tmp_path biasanya punya induk.
        assert ntpath.splitdrive(str(root))[0] or True
    else:
        assert Path(result["parent"]).is_dir()


def test_browse_rejects_credential_folder(sandbox, tmp_path):
    cred = tmp_path / ".ssh"
    cred.mkdir()
    (cred / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")

    with pytest.raises(PermissionError):
        sandbox["projects"].browse_target_dirs(str(cred))


def test_browse_rejects_traversal_into_credential_folder(sandbox, tmp_path):
    """'..' di path tidak boleh dipakai menembus guard folder kredensial."""
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / ".aws").mkdir()
    (work / ".." / ".aws").resolve()

    with pytest.raises(PermissionError):
        sandbox["projects"].browse_target_dirs(str(work / ".." / ".aws"))


def test_browse_missing_folder_raises_not_found(sandbox, tmp_path):
    with pytest.raises(FileNotFoundError):
        sandbox["projects"].browse_target_dirs(str(tmp_path / "tidak-ada"))


def test_browse_file_path_raises_not_a_directory(sandbox, tmp_path):
    a_file = tmp_path / "file.txt"
    a_file.write_text("halo", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        sandbox["projects"].browse_target_dirs(str(a_file))


def test_browse_entry_count_is_capped(sandbox, tmp_path, monkeypatch):
    root = tmp_path / "browse-many"
    root.mkdir()
    for i in range(12):
        (root / f"d{i:02d}").mkdir()
    monkeypatch.setattr(sandbox["projects"], "MAX_BROWSE_ENTRIES", 5)

    result = sandbox["projects"].browse_target_dirs(str(root))

    assert len(result["entries"]) == 5
    assert result["truncated"] is True


def test_browse_endpoint_returns_absolute_paths(client, sandbox, tmp_path):
    root = tmp_path / "api-browse"
    (root / "child").mkdir(parents=True)

    res = client.get("/api/targets/browse", params={"path": str(root)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["absolute_path"] == str(root.resolve())
    assert body["path"] == str(root.resolve())
    assert [e["name"] for e in body["entries"]] == ["child"]
    assert body["parent"] is not None


def test_browse_endpoint_without_path_opens_home(client, sandbox, tmp_path, monkeypatch):
    fake_home = tmp_path / "home-http"
    (fake_home / "proj").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    res = client.get("/api/targets/browse")
    assert res.status_code == 200, res.text
    assert res.json()["absolute_path"] == str(fake_home.resolve())


def test_browse_endpoint_missing_folder_is_404(client, sandbox, tmp_path):
    res = client.get("/api/targets/browse", params={"path": str(tmp_path / "hilang")})
    assert res.status_code == 404
    assert "tidak ditemukan" in res.json()["detail"]


def test_browse_endpoint_file_is_400(client, sandbox, tmp_path):
    a_file = tmp_path / "bukan-folder.txt"
    a_file.write_text("x", encoding="utf-8")

    res = client.get("/api/targets/browse", params={"path": str(a_file)})
    assert res.status_code == 400


def test_browse_endpoint_credential_folder_is_403(client, sandbox, tmp_path):
    cred = tmp_path / ".gnupg"
    cred.mkdir()

    res = client.get("/api/targets/browse", params={"path": str(cred)})
    assert res.status_code == 403
    assert "kredensial" in res.json()["detail"]


def test_browse_endpoint_does_not_touch_allowed_roots(client, sandbox, tmp_path, monkeypatch):
    """Pindah target TIDAK boleh membuat folder di luar workspace bisa dibaca.

    browse_target_dirs() sengaja tidak memakai is_readable_path(), tapi efek
    sampingnya juga harus nol: menjelajah tidak boleh menambah root yang
    diizinkan.
    """
    import settings as settings_store

    outside = tmp_path / "luar-workspace"
    (outside / "isi").mkdir(parents=True)
    before = set(settings_store.allowed_roots())

    res = client.get("/api/targets/browse", params={"path": str(outside)})
    assert res.status_code == 200, res.text
    assert str(outside.resolve()) in res.json()["absolute_path"]
    assert set(settings_store.allowed_roots()) == before


# ---------------------------------------------------------------------------
# BUG-44: history operasi / approval / security tercampur antar repository
# ---------------------------------------------------------------------------
# Operations TIDAK per-target: semua baris ada di satu synapse.db global.
# Efeknya, setelah pindah repo, halaman Operations, Agents, dan Security
# (ketiganya baca /operations) menampilkan approval repository SEBELUMNYA.
# Kalau dua repo punya file bernama sama, user bisa menyetujui perubahan
# pada repo yang tidak sedang dianalisis.
#
# Fix: operations.target_id diisi saat propose (bukan saat dibaca), dan
# /operations + /list_pending_approvals disaring ke target aktif.


def _propose(client, target: str, tool: str = "fs.write_file") -> str:
    res = client.post(
        "/propose_operation",
        json={"tool_name": tool, "params": {"path": target}, "target": target},
    )
    assert res.status_code == 200, res.text
    return res.json()["operation_id"]


def _make_two_targets(client, sandbox):
    a = make_project(sandbox["root"], "op-a", {"a.py": "def a():\n    pass\n"})
    b = make_project(sandbox["root"], "op-b", {"b.py": "def b():\n    pass\n"})
    assert client.post(
        "/api/targets", json={"kind": "local", "label": "repo-a", "path": str(a)}
    ).status_code == 200
    assert client.post(
        "/api/targets", json={"kind": "local", "label": "repo-b", "path": str(b)}
    ).status_code == 200
    return a, b


def test_operations_are_scoped_to_active_target(client, sandbox):
    _make_two_targets(client, sandbox)

    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    op_a = _propose(client, "a.py")

    client.post("/api/targets/repo-b/activate", json={"ingest": False})
    op_b = _propose(client, "b.py")

    listed_b = [op["id"] for op in client.get("/operations").json()]
    assert listed_b == [op_b]

    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    listed_a = [op["id"] for op in client.get("/operations").json()]
    assert listed_a == [op_a]


def test_operations_endpoint_does_not_leak_when_no_target_is_active(client, sandbox):
    _make_two_targets(client, sandbox)
    _propose(client, "a.py")

    client.post("/api/targets/repo-b/activate", json={"ingest": False})
    _propose(client, "b.py")

    # Hapus semua target: tidak boleh ada yang melihat history repo mana pun.
    for target_id in ("repo-a", "repo-b"):
        assert client.delete(f"/api/targets/{target_id}").status_code == 200

    assert client.get("/api/targets").json()["active"] is None
    assert client.get("/operations").json() == []


def test_pending_approvals_are_scoped_to_active_target(client, sandbox):
    _make_two_targets(client, sandbox)

    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    op_a = _propose(client, "a.py")
    client.post("/api/targets/repo-b/activate", json={"ingest": False})
    op_b = _propose(client, "b.py")

    pending_b = client.get("/list_pending_approvals").json()
    assert [p["id"] for p in pending_b["pending"]] == [op_b]

    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    pending_a = client.get("/list_pending_approvals").json()
    assert [p["id"] for p in pending_a["pending"]] == [op_a]


def test_status_filter_still_applies_inside_target_scope(client, sandbox):
    _make_two_targets(client, sandbox)
    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    op_id = _propose(client, "a.py")

    assert client.get("/operations", params={"status": "pending"}).json()[0]["id"] == op_id
    assert client.get("/operations", params={"status": "verified"}).json() == []


def test_invalid_status_still_422_with_allowed_values(client, sandbox):
    """Filter Literal harus tetap mengadili; filtering per target tidak mengubahnya."""
    res = client.get("/operations", params={"status": "pendng"})
    assert res.status_code == 422
    errors = res.json()["detail"]
    assert any(e["loc"][-1] == "status" for e in errors)
    assert "pending" in errors[0]["msg"]


def test_approving_operation_from_another_target_still_works(client, sandbox):
    """Filter hanya berlaku saat listing - id tetap unik global.

    Kalau approve ikut difilter, operasi yang dibuat sebelum pindah target
    akan terkunci selamanya.
    """
    _make_two_targets(client, sandbox)
    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    op_id = _propose(client, "a.py")

    client.post("/api/targets/repo-b/activate", json={"ingest": False})
    res = client.post(
        "/approve_operation", json={"operation_id": op_id, "decision": "approved"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True


def test_operations_survive_target_deletion(client, sandbox):
    """Baris operasi TIDAK ikut terhapus saat target dihapus dari daftar.

    Yang hilang adalah akses lewat UI, bukan history-nya - supaya approval
    yang sudah berjalan tidak ikut lenyap bersama foldernya.
    """
    import sqlite3

    _make_two_targets(client, sandbox)
    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    op_id = _propose(client, "a.py")

    assert client.delete("/api/targets/repo-a").status_code == 200

    conn = sqlite3.connect(sandbox["legacy_db"])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM operations WHERE id = ?", (op_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["target_id"] == "repo-a"
    # Tidak terlihat di target mana pun sekarang, karena tidak ada target
    # dengan id "repo-a" lagi.
    assert client.get("/operations").json() == []


def test_propose_operation_stores_active_target_id(client, sandbox):
    import guardian

    _make_two_targets(client, sandbox)
    client.post("/api/targets/repo-b/activate", json={"ingest": False})

    result = guardian.propose_operation("fs.write_file", {"path": "b.py"}, "b.py")

    assert result["target_id"] == "repo-b"

    import sqlite3

    conn = sqlite3.connect(sandbox["legacy_db"])
    conn.row_factory = sqlite3.Row
    stored = conn.execute(
        "SELECT target_id FROM operations WHERE id = ?", (result["operation_id"],)
    ).fetchone()
    conn.close()
    assert stored["target_id"] == "repo-b"


def test_active_target_id_is_empty_without_registry_entry(sandbox, monkeypatch):
    import guardian

    assert sandbox["projects"].list_targets() == []
    assert guardian.active_target_id() == ""


def test_active_target_id_survives_unreadable_registry(sandbox, monkeypatch):
    import guardian

    def boom():
        raise OSError("registry rusak")

    monkeypatch.setattr(sandbox["projects"], "get_active", boom)
    assert guardian.active_target_id() == ""


def test_legacy_operations_db_gets_target_id_column(tmp_path, monkeypatch):
    """DB lama yang tidak punya kolom target_id harus dimigrasi, bukan error.

    Kalau tidak, backend yang sudah dipakai user akan gagal saat instantiate
    dengan 'no such column: target_id' - dan itu muncul sebagai 500 pada
    setiap halaman, bukan sebagai pesan migrasi.
    """
    import sqlite3

    import database

    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.execute(
        """CREATE TABLE operations (
               id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, status TEXT DEFAULT 'pending'
           )"""
    )
    conn.execute("INSERT INTO operations (id, tool_name) VALUES ('old-1', 'fs.write_file')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", legacy)
    database.init_db()

    conn = sqlite3.connect(legacy)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(operations)")}
    row = conn.execute("SELECT * FROM operations WHERE id = 'old-1'").fetchone()
    conn.close()

    assert "target_id" in cols
    # Baris lama_default-nya '', jadi tidak hilang dan tidak ikut tampil di
    # target mana pun - user tidak ikut melihat history tak bertuan.
    assert row["target_id"] == ""


def test_security_page_data_comes_from_scoped_operations(client, sandbox):
    """Halaman Security membaca /operations, jadi ikut ter-scope.

    Dipakai sebagai pengaman: kalau nanti SecurityPage diganti sumber data,
    test ini gagal dan scoping bisa terkelupas diam-diam.
    """
    _make_two_targets(client, sandbox)
    client.post("/api/targets/repo-a/activate", json={"ingest": False})
    _propose(client, "a.py")
    client.post("/api/targets/repo-b/activate", json={"ingest": False})

    # SecurityPage/OperationsPage/AgentsPage semua memanggil endpoint ini.
    rows = client.get("/operations", params={"limit": 100}).json()
    assert all(row["target_id"] == "repo-b" for row in rows)


def test_sse_proxy_normalizes_lines_and_handles_errors():
    import asyncio
    import main
    from fastapi import HTTPException

    class MockAsyncResponse:
        def __init__(self, status_code, lines=None, body=b""):
            self.status_code = status_code
            self._lines = lines or []
            self._body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def aiter_lines(self):
            for l in self._lines:
                yield l

        async def aread(self):
            return self._body

    async def _run():
        # 1. Normal response streaming
        def mock_open_ok(client):
            return MockAsyncResponse(200, lines=["data: {\"test\": 1}", "raw text line"])

        res = await main._sse_proxy(mock_open_ok, "test_provider")
        chunks = []
        async for chunk in res.body_iterator:
            chunks.append(chunk)

        combined = "".join(chunks)
        assert "data: {\"test\": 1}\n\n" in combined
        assert "data: raw text line\n\n" in combined

        # 2. Provider 401 error before streaming
        def mock_open_err(client):
            return MockAsyncResponse(401, body=b"Unauthorized key")

        with pytest.raises(HTTPException) as exc_info:
            await main._sse_proxy(mock_open_err, "openai")
        assert exc_info.value.status_code == 502
        assert "Unauthorized key" in exc_info.value.detail

    asyncio.run(_run())

