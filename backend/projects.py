"""
projects.py — Target aktif: repository atau folder lokal yang dianalisis Synapse.

MASALAH YANG DISELESAIKAN
-------------------------
Dulu hanya ada satu target implisit: path yang dikirim ke /understand_repo,
dityimpan di global engine._repo_root, dan hilang saat restart. Graph-nya
juga global, sehingga meng-ingest repo kedua langsung menabrak entitas yang
sudah ada (id entity berupa "file::<path relatif>", tanpa namespace).

MODEL YANG DIPAKAI
------------------
Setiap target punya:
    - id       slug stabil, jadi aman jadi nama file DB
    - kind     "local" atau "github"
    - path     folder lokal yang dianalisis
    - label    nama untuk ditampilkan di UI
    - source   "owner/repo" untuk kind=github, None untuk lokal
    - branch   branch yang di-sync terakhir

Target aktif disimpan di registry (registry.json) DAN akibatnya di
storage.set_active_target(), yang membuat engine memakai file DB terpisah
per target. Registry disimpan sebagai file, bukan tabel, karena
database.py (skema v1) tidak punya tabel projects dan menambahkannya
berarti mengunci urutan migrasi yang sudah disepakati tim.

KEAMANAN
--------
- path WAJIB lolos settings_store.is_readable_path(). Registry tidak
  dipercaya: file bisa diedit manual, jadi validasi diulang saat load.
- kind=github TIDAK pernah membaca filesystem. Isi repo disinkronkan ke
  workspace oleh engine.sync_github_target(), bukan oleh file ini.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import settings as settings_store

BASE_DIR = Path(__file__).resolve().parent

REGISTRY_PATH = Path(
    os.environ.get(
        "SYNAPSE_PROJECTS_PATH", str(BASE_DIR / "projects_registry.json")
    )
)

# Slug hanya boleh karakter aman untuk nama file: alphanumeric, dash, underscore.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MAX_TARGETS = 50

# Batas entri per listing browse. Folder seperti C:\Users bisa punya ratusan
# anak; UI tidak pernah menampilkan lebih dari ini dalam satu daftar, dan
# capping membuat biaya endpoint ini sengaja dan terukur.
MAX_BROWSE_ENTRIES = 500

_lock = threading.RLock()


def slugify(text: str) -> str:
    """Slug stabil dari label bebas. Mengembalikan "" kalau tak ada yang cocok."""
    lowered = (text or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    # Slug kosong (label non-ASCII penuh, mis. Mandarin) dipangkas ke
    # "target" supaya tetap punya nama file yang sah.
    return cleaned or "target"


def is_valid_id(target_id: str) -> bool:
    return bool(target_id) and bool(_SLUG_RE.match(target_id))


def _empty() -> Dict[str, Any]:
    return {"active": None, "targets": []}


def _read_raw() -> Dict[str, Any]:
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    targets = data.get("targets")
    if not isinstance(targets, list):
        targets = []
    active = data.get("active")
    return {
        "active": active if isinstance(active, str) else None,
        "targets": [t for t in targets if isinstance(t, dict)],
    }


def _write_raw(data: Dict[str, Any]) -> None:
    tmp = REGISTRY_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, REGISTRY_PATH)


def registered_paths() -> List[str]:
    """Path target yang tercatat, TANPA validasi.

    Dipakai settings.allowed_roots() supaya folder yang sudah terdaftar
    ikut jadi root yang boleh dibaca. Sengaja tidak divalidasi di sini:
    validasi penuh butuh allowed_roots(), yang memanggil fungsi ini.
    """
    with _lock:
        data = _read_raw()
    out: List[str] = []
    for raw in data["targets"]:
        path = raw.get("path")
        if isinstance(path, str) and path.strip():
            out.append(path)
    return out


def _registerable_dir(path_str: str) -> Path:
    """
    Validasi folder yang mau DICATAT sebagai target, sebelum ada di registry.

    Ini bukan `settings_store.is_readable_path()`, dan itu disengaja:
    path yang baru didaftarkan BELUM ada di allowed_roots(), jadi
    is_readable_path() akan menolaknya. Yang dicek di sini adalah apakah
    folder itu layak menjadi target sama sekali:

      - ada, dan berupa directory
      - bukan root filesystem, drive, atau home user itu sendiri
        (membaca $HOME berarti membaca semua token & key di mesin)
      - tidak berada di dalam folder kredensial (.ssh, .aws, .gnupg, .kube)

    Setelah terdaftar, path-nya otomatis masuk allowed_roots() dan tunduk
    ke aturan SENSITIVE_NAMES seperti file lain.
    """
    if not path_str or not path_str.strip():
        raise ValueError("Path folder wajib diisi")
    try:
        resolved = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Path tidak bisa dibaca: {path_str} ({exc})") from exc
    if not resolved.exists():
        raise ValueError(f"Folder tidak ditemukan: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Bukan folder: {resolved}")

    if resolved.parent == resolved:
        raise ValueError(
            "Path root drive tidak boleh jadi target. Pilih folder "
            "di dalamnya, bukan akarnya."
        )
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and resolved == home:
        raise ValueError(
            f"Folder home ({home}) tidak boleh jadi target karena berisi "
            "token dan kunci API. Pilih subfolder proyeknya."
        )

    parts = {p.lower() for p in resolved.parts}
    blocked = parts & _credential_dirs()
    if blocked:
        raise ValueError(
            f"Path berada di dalam folder kredensial ({', '.join(sorted(blocked))}) "
            "dan tidak boleh dianalisis."
        )
    if resolved.name.lower() in {".git", "node_modules", "__pycache__"}:
        raise ValueError(
            f"{resolved.name!r} adalah folder teknis, bukan proyek. "
            "Pilih folder proyeknya."
        )
    return resolved


def _credential_dirs() -> set[str]:
    """Nama folder yang isinya rahasia, tidak boleh dijelajah lewat browse."""
    return {".ssh", ".aws", ".gnupg", ".kube", ".config/gcloud"}


def browse_target_dirs(path_str: str = "") -> Dict[str, Any]:
    """Daftar SUBFOLDER di bawah `path_str`, untuk memilih target tanpa mengetik.

    Beda dengan `settings_store.browse()`:

      - `/browse` terkurung `allowed_roots()` karena gunanya Cortex membaca
        ISI file. Endpoint ini hanya butuh NAMA folder, dan target yang belum
        terdaftar memang belum masuk allowed_roots() - jadi akan selalu ditolak
        kalau memakai aturan yang sama. Itu bug "Folder lokal": user tidak
        pernah bisa memilih folder di luar repo.
      - Hanya direktori yang dikembalikan. Tidak ada nama file, tidak ada
        ukuran, jadi ini bukan cara mendokumentasi isi disk.
      - Folder kredensial ditolak.

    Path relatif diinterpretasikan relatif ke home, jadi `path=""` (default)
    membuka folder home - titik awal yang wajar untuk memilih folder proyek.
    """
    raw = (path_str or "").strip()
    if raw:
        try:
            resolved = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Path tidak bisa dibaca: {raw} ({exc})") from exc
    else:
        try:
            resolved = Path.home().resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Folder home tidak bisa dibaca: {exc}") from exc

    if not resolved.exists():
        raise FileNotFoundError(f"Folder tidak ditemukan: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Bukan folder: {resolved}")

    blocked_parts = {p.lower() for p in resolved.parts} & _credential_dirs()
    if blocked_parts:
        raise PermissionError(
            f"Folder kredensial ({', '.join(sorted(blocked_parts))}) tidak "
            "boleh dijelajah."
        )

    ignored = settings_store.IGNORED_DIRS
    entries: List[Dict[str, Any]] = []
    try:
        names = sorted(resolved.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise PermissionError(f"Gagal membaca folder: {exc}") from exc

    for child in names:
        if child.name in ignored or child.name.startswith("."):
            continue
        try:
            if not child.is_dir():
                continue
        except OSError:
            # Symlink putus atau target-nya tidak bisa diakses. Lewati saja:
            # satu folder rusak tidak boleh menggagalkan seluruh listing.
            continue
        entries.append({"name": child.name, "type": "dir", "size": None})
        if len(entries) >= MAX_BROWSE_ENTRIES:
            break

    parent = resolved.parent
    return {
        "path": str(resolved),
        "absolute_path": str(resolved),
        "parent": str(parent) if parent != resolved else None,
        "entries": entries,
        "truncated": len(entries) >= MAX_BROWSE_ENTRIES,
    }


def _target_dir_ok(path_str: str) -> bool:
    """Path target harus ada, berupa directory, dan boleh dibaca Synapse."""
    if not path_str:
        return False
    try:
        resolved = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    if not resolved.is_dir():
        return False
    return settings_store.is_readable_path(str(resolved))


def _sanitize(target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalisasi satu entri registry, atau None kalau tidak layak pakai.

    Ini lapisan kedua setelah validasi saat create. Registry bisa saja
    corruption atau diedit tangan, dan target yang path-nya sudah tidak
    ada akan membuat /graph/* dan /repo_health gagal dengan error yang
    sangat tidak informatif.
    """
    target_id = target.get("id")
    if not isinstance(target_id, str) or not is_valid_id(target_id):
        return None
    kind = target.get("kind")
    if kind not in ("local", "github"):
        return None
    label = target.get("label")
    if not isinstance(label, str) or not label.strip():
        label = target_id
    path = target.get("path")
    if not isinstance(path, str) or not _target_dir_ok(path):
        # Target stale: path hilang atau berada di luar zona yang diizinkan.
        # Tetap dipertahankan di registry (user mungkin me-mount drive
        # kembali) tapi ditandai supaya UI bisa menjelaskannya.
        out = {
            "id": target_id,
            "kind": kind,
            "label": label,
            "path": path or "",
            "source": target.get("source") if isinstance(target.get("source"), str) else None,
            "branch": target.get("branch") if isinstance(target.get("branch"), str) else None,
            "available": False,
            "created_at": target.get("created_at") or "",
        }
        return out
    out = {
        "id": target_id,
        "kind": kind,
        "label": label,
        "path": path,
        "source": target.get("source") if isinstance(target.get("source"), str) else None,
        "branch": target.get("branch") if isinstance(target.get("branch"), str) else None,
        "available": True,
        "created_at": target.get("created_at") or "",
    }
    return out


def list_targets() -> List[Dict[str, Any]]:
    """Semua target yang tercatat, dengan flag `available` hasil validasi path."""
    with _lock:
        data = _read_raw()
    out: List[Dict[str, Any]] = []
    for raw in data["targets"]:
        clean = _sanitize(raw)
        if clean is not None:
            out.append(clean)
    return out


def get_target(target_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        data = _read_raw()
    for raw in data["targets"]:
        if raw.get("id") == target_id:
            return _sanitize(raw)
    return None


def get_active() -> Optional[Dict[str, Any]]:
    with _lock:
        data = _read_raw()
    active_id = data.get("active")
    if not active_id:
        return None
    for raw in data["targets"]:
        if raw.get("id") == active_id:
            return _sanitize(raw)
    return None


def create_target(
    *,
    kind: str,
    label: str,
    path: str,
    source: str | None = None,
    branch: str | None = None,
    make_active: bool = True,
) -> Dict[str, Any]:
    """Daftarkan target baru. Path divalidasi SEKARANG, bukan saat load."""
    if kind not in ("local", "github"):
        raise ValueError(f"kind tidak dikenal: {kind!r}")
    resolved = _registerable_dir(path)

    from guardian import _utcnow_iso

    with _lock:
        data = _read_raw()
        existing = [t.get("id") for t in data["targets"]]
        if len(existing) >= MAX_TARGETS:
            raise ValueError(f"Batas {MAX_TARGETS} target tercapai")

        # Slug unik: label sama di dua folder berbeda harus tetap bisa
        # dibedakan, jadi suffix angka ditambahkan saat bentrok.
        base = slugify(label)
        candidate = base
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}"
            counter += 1
            if counter > MAX_TARGETS + 10:
                raise ValueError("Tidak bisa membuat slug unik untuk target ini")

        entry = {
            "id": candidate,
            "kind": kind,
            "label": label.strip() or candidate,
            "path": str(resolved),
            "source": source,
            "branch": branch,
            "created_at": _utcnow_iso(),
        }
        data["targets"].append(entry)
        if make_active:
            data["active"] = candidate
        _write_raw(data)
    return _sanitize(entry)  # type: ignore[return-value]


def set_active(target_id: str) -> Dict[str, Any]:
    """Jadikan sebuah target yang aktif. Path-nya harus masih valid."""
    with _lock:
        data = _read_raw()
        found = None
        for raw in data["targets"]:
            if raw.get("id") == target_id:
                found = raw
                break
        if found is None:
            raise KeyError(target_id)
        clean = _sanitize(found)
        if clean is None or not clean.get("available"):
            raise PermissionError(
                f"Target {target_id!r} tidak bisa diaktifkan: folder-nya tidak "
                "ditemukan atau berada di luar workspace yang diizinkan."
            )
        data["active"] = target_id
        _write_raw(data)
    return clean  # type: ignore[return-value]


def update_target(
    target_id: str,
    *,
    label: str | None = None,
    branch: str | None = None,
) -> Dict[str, Any]:
    """Ubah field non-esensial sebuah target. Path sengaja tidak bisa diubah
    lewat sini: memindahkan path berarti graph lama tidak lagi cocok, dan
    itu harus lewat delete + create."""
    with _lock:
        data = _read_raw()
        for raw in data["targets"]:
            if raw.get("id") == target_id:
                if label is not None and label.strip():
                    raw["label"] = label.strip()
                if branch is not None:
                    raw["branch"] = branch
                _write_raw(data)
                return _sanitize(raw)  # type: ignore[return-value]
    raise KeyError(target_id)


def delete_target(target_id: str, *, remove_graph: bool = False) -> Dict[str, Any]:
    """Hapus target dari registry. Optionally hapus juga file graph-nya.

    Graph dihapus DITEMPATkan, tidak pernah lewat nama yang dihitung ulang
    dari input mentah: pemanggil/main.py sudah memvalidasi id lewat
    is_valid_id, dan storage.db_path_for_target() menyaring ulang.

    Mengembalikan ringkasan {"graph_removed": bool, "graph_path": str|None}.
    Field itu ada karena "hapus + graph" bisa gagal diam-diam: di Windows
    file SQLite yang masih dipegang connection thread lain tidak bisa
    di-unlink. Koneksi ditutup dulu, dan kalau file tetap selamat berarti ada
    yang menahan - caller wajib melaporkannya ke user, bukan mengklaim sukses.
    """
    import storage

    with _lock:
        data = _read_raw()
        remaining = [t for t in data["targets"] if t.get("id") != target_id]
        if len(remaining) == len(data["targets"]):
            raise KeyError(target_id)
        data["targets"] = remaining
        if data.get("active") == target_id:
            data["active"] = remaining[0]["id"] if remaining else None
        _write_raw(data)

    result: Dict[str, Any] = {"graph_removed": False, "graph_path": None}
    if remove_graph and is_valid_id(target_id):
        graph_path = storage.db_path_for_target(target_id)
        result["graph_path"] = str(graph_path)
        if graph_path.exists():
            # Tutup semua koneksi dulu.(get_conn() akan membuka lagi bila
            # ada request lanjutan, jadi tidak ada state yang tertinggal.)
            storage.close_all_connections()
        for candidate in (
            graph_path,
            graph_path.with_name(graph_path.name + "-wal"),
            graph_path.with_name(graph_path.name + "-shm"),
        ):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        result["graph_removed"] = not graph_path.exists()
    return result


def ensure_active_applied() -> Optional[Dict[str, Any]]:
    """Terapkan target aktif ke storage. Dipanggil saat startup.

    Dipisah dari get_active() supaya modul ini tidak mengimpor storage
    (dan tidak memicu siklus import) di jalur baca biasa.
    """
    import storage

    active = get_active()
    if active is None:
        storage.set_active_target(None)
        return None
    if not active.get("available"):
        # Target aktif hilang dari disk. Jangan diam-diam membuka DB graph
        # yang salah; turunkan ke mode tanpa target supaya user melihat
        # "belum ada target" alih-alih data repo yang salah.
        storage.set_active_target(None)
        return active
    storage.set_active_target(active["id"])
    return active
