"""
github_sync.py — Unduh repository GitHub ke folder lokal, lalu bisa di-ingest.

KENAPA TARBALL, BUKAN `git clone`
---------------------------------
Tiga alasan, semuanya nyata:

1. `engine.ingest_repository()` hanya menerima path lokal. Ia mem-parsing
   dengan tree-sitter, menghitung kompleksitas, dan menautkan dokumen -
   pipeline lengkap yang sudah benar. Kalau repo datang sebagai file
   individual dari GitHub API, semua itu harus ditulis ulang, dan hasilnya
   pasti lebih buruk dari ingest folder.

2. Git untuk Windows harus ada di PATH. Kalau tidak, sync gagal dengan
   error yang membingungkan ("git is not recognized"), padahal Synapse
   sendiri tidak butuh git sama sekali.

3. GitHub API membatasinya 60 request/jam per token tanpa autentikasi, dan
   tetap 5.000/jam dengan token. Satu repo 500 file yang diambil per-file
   akan menghabiskan kuota hanya untuk satu target. Tarball = 1 request.

TARANAMAN
---------
Tarball GitHub adalah gzip yang bisa berisi apa saja, dan nama file di
dalamnya tidak bisa dipercaya. `tarfile.extractall` tanpa filter adalah
path traversal klasik (`../../.ssh/authorized_keys`). Semua anggota DIJERITA
pembatasnya lewat `filter="data"` (Python 3.12+) sebelum diekstrak, dan
ukuran total dibatasi supaya tarball bom tidak menghabiskan disk.
"""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import settings as settings_store

# Batas keras per repo. Repo Synapse sendiri sekitar 2-3 MB; 512 MB
# memberi ruang untuk repo besar tanpa membiarkan zip bombape exhausting disk.
MAX_TARBALL_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 200_000
DOWNLOAD_TIMEOUT = 180

# Owner/repo hanya boleh karakter yang sah di GitHub. Ini bukan sekadar
# sanitasi: nilai ini masuk ke path filesystem, jadi harus ketat.
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

# Folder di dalam tarball yang tidak pernah diekstrak. GitHub tidak pernah
# mengikutsertakannya, tapi kita tidak bergantung pada jaminan itu.
_SKIP_TOP = {".git"}


class SyncError(RuntimeError):
    """Kegagalan sync yang layak ditampilkan ke user apa adanya."""


def validate_source(source: str) -> tuple[str, str]:
    """
    Pecah "owner/repo" dan pastikan keduanya aman untuk path filesystem.

    Mengembalikan (owner, repo). Melempar ValueError kalau bentuknya salah.
    """
    if not source or not source.strip():
        raise ValueError("source wajib diisi dengan format 'owner/repo'")
    parts = source.strip().strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(
            f"Format source harus 'owner/repo', dapat: {source!r}"
        )
    owner, repo = parts
    for label, value in (("owner", owner), ("repo", repo)):
        if not _REPO_RE.match(value):
            raise ValueError(
                f"{label} {value!r} tidak sah. Huruf, angka, titik, "
                "underscore, dan tanda hubung saja."
            )
    # Pathological: repo bernama "." atau ".." lolos regex tapi menunjuk
    # parent directory saat dipakai sebagai path.
    if repo in (".", "..") or owner in (".", ".."):
        raise ValueError(f"source tidak sah: {source!r}")
    return owner, repo


def validate_branch(branch: str) -> str:
    """Branch harus berupa referensi Git yang wajar, tanpa path traversal."""
    if not branch or not branch.strip():
        raise ValueError("branch wajib diisi")
    cleaned = branch.strip()
    if len(cleaned) > 200:
        raise ValueError("branch terlalu panjang")
    if cleaned.startswith("-") or ".." in cleaned:
        raise ValueError(f"branch tidak sah: {branch!r}")
    if not re.match(r"^[A-Za-z0-9._/-]+$", cleaned):
        raise ValueError(f"branch tidak sah: {branch!r}")
    return cleaned


def workspace_repos_root() -> Path:
    """Folder tempat checkout GitHub disimpan: workspace_path/repos.

    Dipakai, bukan dibuat, supaya penempatan file tetap tunduk pada
    settings.is_readable_path() - kalau operator mengubah workspace_path
    ke lokasi yang tidak diizinkan, sync gagal dengan jelas.
    """
    raw = settings_store.load()["workspace_path"]
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path(settings_store.REPO_ROOT) / candidate
    return candidate.resolve() / "repos"


def checkout_dir(source: str) -> Path:
    """Folder checkout untuk sebuah repo. Nama pakai owner__repo."""
    owner, repo = validate_source(source)
    return workspace_repos_root() / f"{owner}__{repo}"


def _download_tarball(
    source: str, branch: str, token: Optional[str]
) -> Path:
    """Unduh tarball repo ke file sementara. Mengembalikan path-nya."""
    import requests

    owner, repo = validate_source(source)
    branch = validate_branch(branch)
    url = (
        f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
        f"/tarball/{quote(branch, safe='')}"
    )
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    tmp = tempfile.NamedTemporaryFile(
        prefix="synapse-tarball-", suffix=".tar.gz", delete=False
    )
    tmp_path = Path(tmp.name)
    written = 0
    try:
        with requests.get(
            url, headers=headers, stream=True, timeout=DOWNLOAD_TIMEOUT
        ) as resp:
            if resp.status_code == 401:
                raise SyncError(
                    "Token GitHub ditolak. Sambungkan ulang di "
                    "Settings > GitHub."
                )
            if resp.status_code == 403:
                raise SyncError(
                    "GitHub menolak akses (403). Cek token, atau repo ini "
                    "private dan tokennya kurang scope 'repo'."
                )
            if resp.status_code == 404:
                raise SyncError(
                    f"Repo {source} atau branch {branch} tidak ditemukan."
                )
            if resp.status_code != 200:
                raise SyncError(
                    f"Gagal mengunduh repo (HTTP {resp.status_code})."
                )
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_TARBALL_BYTES:
                    raise SyncError(
                        f"Repo melebihi batas unduhan "
                        f"({MAX_TARBALL_BYTES // (1024 * 1024)} MB)."
                    )
                tmp.write(chunk)
    except requests.RequestException as exc:
        raise SyncError(f"Gagal menghubungi GitHub: {exc}") from exc
    finally:
        tmp.close()

    if written == 0:
        tmp_path.unlink(missing_ok=True)
        raise SyncError("Tarball dari GitHub kosong.")
    return tmp_path


def _extract_safely(tar_path: Path, dest: Path) -> dict:
    """
    Ekstrak tarball ke `dest`, merapikan satu direktori teratas.

    Keamanan, urut dari yang paling penting:
      - `filter="data"` menolak symlink keluar dest, hardlink ke luar,
        nama path absolut, dan `..` SEBELUM file ditulis. Ini yang mencegah
        "../../.ssh/authorized_keys".
      - satu direktori teratas dibuang, karena GitHub membungkus isi repo
        di folder bernama "owner-repo-<sha>".
      - batas jumlah entri, supaya arsip dengan jutaan header tidak
        membuat prosesnya berhenti merespons.
    """
    dest.mkdir(parents=True, exist_ok=True)
    files = 0
    dirs = 0
    skipped = 0
    seen_top: set[str] = set()

    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            members = 0
            for member in tar:
                members += 1
                if members > MAX_ENTRIES:
                    raise SyncError(
                        "Repo memiliki terlalu banyak entri untuk dipindai."
                    )
                parts = [p for p in member.name.split("/") if p not in ("", ".")]
                if not parts:
                    continue
                # Buang direktori teratas milik GitHub.
                top = parts[0]
                if len(parts) == 1:
                    if top in _SKIP_TOP:
                        continue
                    seen_top.add(top)
                    continue
                if top in _SKIP_TOP:
                    skipped += 1
                    continue

                if member.isdir():
                    dirs += 1
                elif member.isfile():
                    files += 1
                else:
                    # symlink/hardlink/fifo/device: dilewati, bukan diekstrak.
                    skipped += 1
                    continue

                # filter="data" yang benar-benar menolak traversal. Member
                # dimodifikasi in-place, jadi.strip harus jalan SEBELUM
                # extractall membaca ulang.
                stripped = tarfile.TarInfo(
                    name="/".join(parts[1:])
                )
                stripped.size = member.size
                stripped.mode = member.mode
                stripped.mtime = member.mtime
                stripped.type = member.type
                stripped.linkname = member.linkname
                stripped.uid = 0
                stripped.gid = 0
                stripped.uname = ""
                stripped.gname = ""
                try:
                    stripped = tarfile.data_filter(stripped, dest)
                except tarfile.FilterError:
                    skipped += 1
                    continue
                # filter="data" dieksplisitkan, bukan mengandalkan default.
                # Python 3.14 mengubah default menjadi "menolak file yang
                # mencurigakan", jaditanpa ini_sync bisa gagal diam-diam
                # setelah upgrade interpreter.>data_filter di atas sudah
                # menyaring member; pemanggilan kedua bersifat idempoten
                # dan memastikan tidak ada jalur yang lolos.
                try:
                    tar.extract(stripped, dest, filter="data")
                except tarfile.FilterError:
                    skipped += 1
    except tarfile.TarError as exc:
        raise SyncError(f"Tarball rusak atau ditolak: {exc}") from exc

    if files == 0 and dirs == 0:
        raise SyncError("Tarball tidak berisi file yang bisa dipindai.")
    return {
        "files": files,
        "dirs": dirs,
        "skipped": skipped,
        "top_dirs": sorted(seen_top)[:3],
    }


def sync_repo(
    *,
    source: str,
    branch: str,
    token: Optional[str],
    dest: Optional[Path] = None,
) -> dict:
    """
    Unduh `source@branch` ke folder lokal dan kembalikan statistik.

    Folder tujuan DIHAPUS dulu supaya hasilnya benar-benar replace: file
    yang sudah dihapus di branch baru tidak akan menghantui sebagai sisa
    checkout lama. Penghapusan hanya terjadi di dalam dest, yang selalu
    dihitung dari owner/repo yang tervalidasi.
    """
    validate_source(source)
    validate_branch(branch)

    if dest is None:
        dest = checkout_dir(source)
    dest = Path(dest).resolve()

    # Pasti: dest harus di dalam roots yang diizinkan, DAN harus punya
    # kedalaman cukup supaya tidak menimpa folder yang lebih penting.
    if not settings_store.is_readable_path(str(dest)):
        raise SyncError(
            f"Folder tujuan {dest} berada di luar area yang diizinkan. "
            "Cek settings workspace_path."
        )
    if dest.name in ("", ".", "..") or dest.parent == dest:
        raise SyncError("Folder tujuan tidak valid.")

    tar_path = _download_tarball(source, branch, token)
    staging = dest.with_name(dest.name + ".synapse-new")
    try:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        stats = _extract_safely(tar_path, staging)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        staging.rename(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        tar_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "source": source,
        "branch": branch,
        "path": str(dest),
        **stats,
    }
