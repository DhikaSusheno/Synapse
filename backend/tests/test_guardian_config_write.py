"""
Regression test untuk H2, H6, dan H7.

H6/F-22 [HIGH] database.DB_PATH dan storage.DB_PATH adalah path RELATIF,
    jadi mengikuti direktori kerja proses. Server yang dijalankan dari lokasi
    berbeda membuat file DB kosong yang berbeda dan state terbelah tanpa satu
    pun error. Kasus nyata di repo ini: synapse_v2.db kosong 98 KB / 0 row di
    root (dibuat saat demo_reset.py jalan dari root) berdampingan dengan
    backend/synapse_v2.db berisi 848 entities + 1010 relations.

H2 [HIGH] rule config.write punya require_approval=False, padahal eksekusinya
    adalah tulis file bebas ke path apa pun. Tanpa approval, agent yang bisa
    propose operasi memperoleh tulis file sembarang (.ssh/authorized_keys,
    .env berisi SYNAPSE_API_TOKEN + FERNET_KEY, hook git) -> code execution
    tanpa persetujuan manusia, melanggar approval_mode "Manual (human
    required)" yang ditulis Synapse sendiri.

H7/F-05 [HIGH] _exec_config_write() tidak memvalidasi path sama sekali dan
    menulis non-atomik (truncate lalu tulis). Dampaknya: tulis ke luar
    workspace, plus file config kosong/setengah tulis kalau proses mati di
    tengah.

Kasus yang sama juga ditutup untuk _exec_file_delete(), yang dulu bisa
menghapus file apa pun di luar workspace.

PERHATIAN: fixture guardian_db di bawah mengalihkan database.DB_PATH ke
tmp_path. backend/tests/conftest.py TIDAK melakukan itu (berbeda dengan
conftest di security/tests), jadi tanpa fixture ini setiap propose/execute
di test ini akan menulis ke database asli di backend/synapse.db.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
import guardian  # noqa: E402
import settings  # noqa: E402
import storage  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def guardian_db(tmp_path, monkeypatch):
    """DB SQLite kosong di tmp_path; guardian akan membacanya lewat _db_path()."""
    db_file = tmp_path / "guardian_test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    return db_file


@pytest.fixture()
def write_root(tmp_path, monkeypatch):
    """
    Tambahkan tmp_path sebagai root yang boleh ditulis.

    Guard guardian memang membatasi tulisan ke allowed_roots() (repo +
    workspace). Test tidak boleh menulis sampah ke dalam repo, jadi root-
    nya yang diperluas — guard-nya sendiri tetap diuji lewat kasus ditolak
    yang memakai lokasi yang memang tidak diizinkan.
    """
    original = settings.allowed_roots
    monkeypatch.setattr(
        settings, "allowed_roots", lambda: [*original(), str(tmp_path)]
    )
    return tmp_path


# ---------------------------------------------------------------------------
# H6 / F-22 — path DB harus di-anchor, bukan ikut CWD
# ---------------------------------------------------------------------------


class TestDbPathsAnchored:
    def test_database_db_path_absolut_dan_diatr_ke_modul(self):
        assert database.DB_PATH.is_absolute(), (
            f"DB_PATH relatif mengikuti CWD: {database.DB_PATH}"
        )
        assert database.DB_PATH == (BACKEND_DIR / "synapse.db")

    def test_storage_db_path_absolut_dan_diatr_ke_modul(self):
        assert storage.DB_PATH.is_absolute()
        assert storage.DB_PATH == (BACKEND_DIR / "synapse_v2.db")

    def test_path_tidak_bergantung_pada_cwd(self, tmp_path):
        """
        Inti H6: jalankan interpreter dari direktori lain — path DB yang
        dihasilkan harus identik. Inilah yang dulu gagal dan membelah state
        menjadi dua file .db yang saling tidak tahu-menahu.
        """
        probe = (
            f"import sys; sys.path.insert(0, r'{BACKEND_DIR}');"
            "import database, storage;"
            "print(database.DB_PATH); print(storage.DB_PATH)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-800:]
        lines = [
            line.strip()
            for line in proc.stdout.splitlines()
            if "synapse" in line and "db" in line
        ]
        assert lines[-2] == str((BACKEND_DIR / "synapse.db").resolve()), lines
        assert lines[-1] == str((BACKEND_DIR / "synapse_v2.db").resolve()), lines

    def test_env_override_tetap_dihormati(self, tmp_path):
        custom = tmp_path / "custom.db"
        probe = (
            f"import sys; sys.path.insert(0, r'{BACKEND_DIR}');"
            "import storage; print(storage.DB_PATH)"
        )
        env = dict(os.environ, SYNAPSE_DB_PATH=str(custom))
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-800:]
        assert str(custom.resolve()) in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# H2 — config.write wajib lewat approval manusia
# ---------------------------------------------------------------------------


class TestConfigWriteRequiresApproval:
    def test_rule_config_write_wajib_approval(self):
        rule = guardian._get_rule("config.write")
        assert rule["require_approval"] is True

    def test_propose_config_write_wajib_approval(self, guardian_db):
        result = guardian.propose_operation(
            "config.write", {"file_path": "x.conf", "content": "y"}, "t-h2-1"
        )
        assert result["requires_approval"] is True

    def test_execute_tanpa_approval_tidak_menyentuh_disk(
        self, guardian_db, write_root
    ):
        """
        Jantung H2: operasi config.write yang tidak pernah di-approve tidak
        boleh menyentuh disk sama sekali.
        """
        target = write_root / "no-approval.conf"
        proposal = guardian.propose_operation(
            "config.write",
            {"file_path": str(target), "content": "harus-tidak-tertulis"},
            f"cfg::{target.name}",
        )
        assert proposal["requires_approval"] is True

        result = guardian.execute_operation(proposal["operation_id"])
        assert result["ok"] is False, "execute tanpa approval harus ditolak"
        assert not target.exists(), (
            "file ditulis meskipun operasi tidak pernah di-approve"
        )

    def test_config_write_root_mismatch_tetap_fail_closed(self, guardian_db):
        """config.write.as.root tidak cocok dengan rule -> tetap fail-closed."""
        rule = guardian._get_rule("config.write.as.root")
        assert rule["require_approval"] is True
        assert rule["blast_radius"] == "unknown"


# ---------------------------------------------------------------------------
# H7/F-05 — guard path untuk config.write
# ---------------------------------------------------------------------------


def _write(path, content="isi"):
    return guardian._exec_config_write(
        {"file_path": str(path), "content": content}
    )


class TestConfigWritePathGuard:
    def test_tulis_di_luar_workspace_ditolak(self, tmp_path):
        outside = tmp_path / "luar" / "evil.conf"
        outside.parent.mkdir(parents=True, exist_ok=True)
        ok, msg = _write(outside, "pwned")
        assert ok is False, "tulisan di luar allowed_roots harus ditolak"
        assert "ditolak" in msg.lower()
        assert not outside.exists()

    @pytest.mark.parametrize("name", [
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "server.pem",
        "secret.key",
        "app.db",
        "creds.sqlite3",
    ])
    def test_tulis_file_sensitif_ditolak(self, write_root, name):
        """allowed_roots saja tidak cukup: file sensitif ada DI DALAM repo."""
        target = write_root / name
        ok, msg = _write(target, "x")
        assert ok is False, f"{name} harus ditolak meski di dalam root"
        assert not target.exists()

    def test_dir_ssh_ditolak(self, write_root):
        ssh_dir = write_root / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        target = ssh_dir / "authorized_keys"
        ok, _ = _write(target, "ssh-rsa AAAA")
        assert ok is False
        assert not target.exists()

    def test_tulis_di_dalam_root_belemasih(self, write_root):
        target = write_root / "app.conf"
        ok, msg = _write(target, "port = 8080")
        assert ok is True, msg
        assert target.read_text(encoding="utf-8") == "port = 8080"

    def test_file_path_kosong_ditolak(self):
        ok, msg = _write("", "x")
        assert ok is False
        assert "file_path" in msg

    def test_direktori_induk_tidak_ada_ditolak_dengan_pesan_jelas(self, write_root):
        target = write_root / "belum-ada" / "app.conf"
        ok, msg = _write(target, "x")
        assert ok is False
        assert not target.exists()

    def test_path_relative_keluar_root_ditolak_setelah_realpath(self, write_root):
        """`..` yang keluar dari root harus tertolak setelah di-resolve."""
        outside = write_root.parent / "di-luar.conf"
        ok, _ = _write(outside, "x")
        assert ok is False
        assert not outside.exists()

    def test_path_workspace_luar_repo_dihormati(self, tmp_path, monkeypatch):
        """
        Workspace yang dikonfigurasi di luar repo tetap boleh ditulis.

        Ini menjaga agar guard tidak "diperbaiki" jadi semacam
        `path harus di dalam REPO_ROOT` — allowed_roots() memang berisi repo
        PLUS workspace, dan menjatuhkan workspace akan memutus konfigurasi
        pengguna yang sah.
        """
        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setattr(
            settings,
            "load",
            lambda: {**settings.DEFAULTS, "workspace_path": str(workspace)},
        )
        target = workspace / "app.conf"
        ok, msg = _write(target, "x")
        assert ok is True, msg
        assert target.exists()


# ---------------------------------------------------------------------------
# H7 — tulisan harus atomik
# ---------------------------------------------------------------------------


class TestConfigWriteAtomicity:
    def test_tulis_baru_menghasilkan_isi_lengkap(self, write_root):
        target = write_root / "fresh.conf"
        ok, _ = _write(target, "A" * 5000)
        assert ok is True
        assert target.read_text(encoding="utf-8") == "A" * 5000

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "Windows tidak memiliki permission POSIX: chmod hanya mengatur "
            "bit read-only sehingga st_mode tidak pernah memuat 0640"
        ),
    )
    def test_overwrite_mempertahankan_permission_asli(self, write_root):
        target = write_root / "perm.conf"
        target.write_text("lama", encoding="utf-8")
        os.chmod(target, 0o640)

        ok, _ = _write(target, "baru")
        assert ok is True
        assert target.read_text(encoding="utf-8") == "baru"
        assert (os.stat(target).st_mode & 0o777) == 0o640

    def test_tidak_meninggalkan_file_tempurung(self, write_root):
        target = write_root / "tmp.conf"
        _write(target, "x")
        leftovers = [
            p.name
            for p in write_root.iterdir()
            if p.name.endswith(".tmp") or p.name.startswith(".")
        ]
        assert leftovers == [], f"file tempurung tertinggal: {leftovers}"

    def test_gagal_tulis_tidak_menghancurkan_file_lama(
        self, write_root, monkeypatch
    ):
        """
        Bukti sisi atomik: kalau replace gagal, isi file lama harus utuh.
        Tulis-langsung (truncate lalu tulis) akan menyisakan file kosong —
        persis kegagalan yang membuat konfigurasi boot jadi korup.
        """
        target = write_root / "keep.conf"
        target.write_text("KONTEN LAMA", encoding="utf-8")

        def boom(src, dst):
            raise OSError("disk penuh (simulasi)")

        monkeypatch.setattr(os, "replace", boom)
        ok, msg = guardian._exec_config_write(
            {"file_path": str(target), "content": "KONTEN BARU"}
        )
        assert ok is False
        assert target.read_text(encoding="utf-8") == "KONTEN LAMA", (
            "file lama harus tetap utuh kalau tulis gagal"
        )
        leftovers = [
            p.name for p in write_root.iterdir() if p.name.endswith(".tmp")
        ]
        assert leftovers == [], f"tempurung gagal tertinggal: {leftovers}"


# ---------------------------------------------------------------------------
# Guard yang sama untuk file.delete
# ---------------------------------------------------------------------------


class TestFileDeletePathGuard:
    def test_hapus_di_luar_workspace_ditolak(self, tmp_path):
        outside = tmp_path / "luar.conf"
        outside.write_text("isi", encoding="utf-8")
        ok, _ = guardian._exec_file_delete(
            {"file_path": str(outside)}, snapshot_ref=None
        )
        assert ok is False
        assert outside.exists(), "file di luar root tidak boleh dihapus"

    def test_hapus_file_sensitif_ditolak(self, write_root):
        env_file = write_root / ".env"
        env_file.write_text("SYNAPSE_API_TOKEN=x", encoding="utf-8")
        ok, _ = guardian._exec_file_delete(
            {"file_path": str(env_file)}, snapshot_ref=str(env_file)
        )
        assert ok is False
        assert env_file.exists(), ".env tidak boleh bisa dihapus lewat guardian"

    def test_hapus_file_valid_butuh_snapshot(self, write_root):
        target = write_root / "boleh.conf"
        target.write_text("isi", encoding="utf-8")
        ok, _ = guardian._exec_file_delete(
            {"file_path": str(target)}, snapshot_ref=None
        )
        assert ok is False
        assert target.exists()

    def test_hapus_file_valid_dengan_snapshot_valid(self, write_root):
        target = write_root / "boleh.conf"
        target.write_text("isi", encoding="utf-8")
        snapshot = write_root / "boleh.conf.bak.1"
        snapshot.write_text("isi", encoding="utf-8")
        ok, msg = guardian._exec_file_delete(
            {"file_path": str(target)}, snapshot_ref=str(snapshot)
        )
        assert ok is True, msg
        assert not target.exists()
