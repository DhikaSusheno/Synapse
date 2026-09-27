"""Persistent platform settings and safe workspace browsing."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

SETTINGS_PATH = os.environ.get(
    "SYNAPSE_SETTINGS_PATH", os.path.join(BASE_DIR, "synapse_settings.json")
)

DEFAULTS: Dict[str, Any] = {
    "platform_name": "Synapse",
    "environment": "Production",
    "log_level": "INFO",
    "dev_mode": False,
    "workspace_path": "./workspace",
    "default_branch": "main",
    "auto_migrate": True,
    "conflict_detect": True,
    "sse_enabled": True,
    "approval_mode": "Manual (human required)",
    "conflict_auto_deny": True,
}

ENUMS: Dict[str, List[str]] = {
    "environment": ["Production", "Staging", "Development"],
    "log_level": ["DEBUG", "INFO", "WARNING", "ERROR"],
    "approval_mode": [
        "Manual (human required)",
        "Auto-approve low risk",
        "Auto-deny all",
    ],
}

BOOL_KEYS = (
    "dev_mode",
    "auto_migrate",
    "conflict_detect",
    "sse_enabled",
    "conflict_auto_deny",
)

STR_KEYS = (
    "platform_name",
    "workspace_path",
    "default_branch",
)

IGNORED_DIRS = {
    ".git",
    ".next",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
}


def _coerce(key: str, value: Any) -> Any:
    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if key in ENUMS:
        text = str(value).strip()
        return text if text in ENUMS[key] else DEFAULTS[key]
    if key in STR_KEYS:
        text = str(value).strip()
        if not text:
            return DEFAULTS[key]
        if key == "platform_name" and len(text) > 64:
            return text[:64]
        if key in ("workspace_path", "default_branch") and len(text) > 400:
            return text[:400]
        return text
    return value


def load() -> Dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    data[key] = _coerce(key, stored[key])
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        pass
    return data


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = load()
    if isinstance(patch, dict):
        for key, value in patch.items():
            if key in DEFAULTS:
                current[key] = _coerce(key, value)
    directory = os.path.dirname(SETTINGS_PATH) or "."
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
    )
    try:
        with handle:
            json.dump(current, handle, indent=2, ensure_ascii=False)
        os.replace(handle.name, SETTINGS_PATH)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return current


def reset() -> Dict[str, Any]:
    try:
        os.unlink(SETTINGS_PATH)
    except OSError:
        pass
    return dict(DEFAULTS)


def allowed_roots() -> List[str]:
    """
    Root yang boleh dibaca endpoint Synapse: repo + workspace_path.

    Target yang terdaftar (projects.py) juga diikutkan, karena target ARE
    repo/folder yang dianalisis - tanpa ini, `/understand_repo` pada target
    tersebut akan ditolak padahal target-nya sah. Operator yang tidak
    ingincabut trust ini bisa set SYNAPSE_ALLOW_TARGET_ROOTS=0.

    Import projects dilakukan di dalam fungsi supaya settings.py tetap bisa
    diimpor tanpa projects.py, dan supaya failure di registry tidak
    menjatuhkan seluruh endpoint.
    """
    roots = [REPO_ROOT]
    workspace = load()["workspace_path"]
    candidate = workspace if os.path.isabs(workspace) else os.path.join(REPO_ROOT, workspace)
    resolved = os.path.realpath(candidate)
    if os.path.isdir(resolved):
        roots.append(resolved)

    if os.environ.get("SYNAPSE_ALLOW_TARGET_ROOTS", "1").strip() in ("0", "false", "no"):
        return roots
    try:
        import projects
    except Exception:
        return roots
    try:
        for target in projects.registered_paths():
            real = os.path.realpath(target)
            if os.path.isdir(real) and real not in roots:
                roots.append(real)
    except Exception:
        # Registry rusak tidak boleh menjatuhkan semua pembacaan file.
        pass
    return roots


def _is_allowed(target: str) -> bool:
    real = os.path.realpath(target)
    for root in allowed_roots():
        root_real = os.path.realpath(root)
        if real == root_real or real.startswith(root_real + os.sep):
            return True
    return False


# Nama file/folder yang tidak boleh dibaca endpoint mana pun.
#
# Ini penting karena allowlist root saja tidak cukup: file .env berada DI
# DALAM repo, jadi tetap lolos kalau hanya dicek against allowed_roots().
# Isinya memuat SYNAPSE_API_TOKEN dan FERNET_KEY, dan FERNET_KEY mengizinkan
# decrypt_token() membuka semua kredensial yang tersimpan di database.
SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        ".npmrc",
        ".netrc",
        ".pgpass",
        "credentials.json",
        "service-account.json",
    }
)
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".keystore", ".db", ".sqlite", ".sqlite3")


def _is_sensitive(real_path: str) -> bool:
    """True kalau path menunjuk file kredensial atau database."""
    base = os.path.basename(real_path).lower()
    if base in SENSITIVE_NAMES or base.startswith(".env."):
        return True
    if base.endswith(SENSITIVE_SUFFIXES):
        return True
    # Direktori /.ssh/, /.aws/ dan sejenisnya di dalam root yang diizinkan
    parts = {p.lower() for p in os.path.normpath(real_path).split(os.sep)}
    if parts & {".ssh", ".aws", ".gnupg", ".kube"}:
        return True
    return False


def is_readable_path(target: str) -> bool:
    """
    True kalau `target` boleh dibaca endpoint Synapse.

    Dua lapis, dan keduanya wajib:
      1. path harus berada di dalam allowed_roots() (repo + workspace)
      2. path tidak boleh menunjuk file kredensial atau database

    Dipakai bersama oleh endpoint yang menerima path dari request -
    /api/rag/ingest, /review_change, /understand_repo - supaya semuanya
    tunduk pada aturan yang sama.
    """
    if not target or not str(target).strip():
        return False
    try:
        real = os.path.realpath(os.path.expanduser(str(target)))
    except (OSError, ValueError):
        return False
    if not _is_allowed(real):
        return False
    if _is_sensitive(real):
        return False
    return True


def is_writable_path(target: str) -> bool:
    """
    True kalau `target` boleh DITULIS oleh guardian (config.write).

    Dua aturannya sama persis dengan is_readable_path(), dan sengaja memakai
    fungsi yang sama supaya kebijakan "mana yang boleh disentuh" tidak pernah
    terpecah jadi dua versi yang bisa berbeda:
      1. path harus di dalam allowed_roots() — repo + workspace
      2. path tidak boleh menunjuk file kredensial/database

    Pembedanya hanya di pemakaian dan di dokumentasi. Tanpa pemeriksaan ini
    _exec_config_write() menulis ke path apa pun yang bisa ditulis proses
    (.ssh/authorized_keys, .env yang memuat SYNAPSE_API_TOKEN + FERNET_KEY,
    file sistem lain di luar repo) — padahal config.write adalah primitive
    tulis paling umum di guardian.

    Caveat yang disadari: aturan ini tidak memblokir file source (.py/.sh)
    yang berada di dalam repo. Menulis source di dalam workspace memang
    lingkup kerja guardian; karena config.write kini butuh approval manusia,
    tulis semacam itu tidak bisa terjadi tanpa keputusan eksplisit.
    """
    return is_readable_path(target)


def browse(path: str = "") -> Dict[str, Any]:
    raw = (path or "").strip()
    target = os.path.join(REPO_ROOT, raw) if raw else REPO_ROOT
    real_target = os.path.realpath(target)

    # M11 FIX 1 — urutan pemeriksaan dibalik.
    #
    # Dulu `os.path.exists()` dicek SEBELUM `_is_allowed()`. Karena itu
    # endpoint ini berubah jadi oracle keberadaan path di luar workspace:
    #   `FileNotFoundError`  -> path itu tidak ada
    #   `PermissionError`    -> path itu ADA, hanya di luar root
    # Dua respon berbeda itu sudah cukup untuk memetakan filesystem milik
    # server tanpa punya izin apa pun. Validasi izin harus selalu didahulukan
    # supaya jawabannya sama saja untuk path yang ada maupun yang tidak ada.
    if not _is_allowed(real_target):
        raise PermissionError("Path di luar workspace yang diizinkan")

    # M11 FIX 2 — lapis kedua yang selama ini dilewat browse().
    #
    # `_is_allowed()` hanya memastikan path di DALAM workspace. Tapi `.env`
    # (berisi SYNAPSE_API_TOKEN + FERNET_KEY) dan `id_rsa` juga ada DI DALAM
    # workspace. Endpoint read-file lain sudah memakai `_is_sensitive()`
    # lewat is_readable_path(); browse() harus tunduk pada aturan yang sama,
    # kalau tidak penapisnya hanya setengah jalan.
    if _is_sensitive(real_target):
        raise PermissionError("File kredensial tidak bisa dibuka")

    if not os.path.exists(real_target):
        raise FileNotFoundError(f"Path tidak ditemukan: {raw}")
    if not os.path.isdir(real_target):
        raise NotADirectoryError(f"Bukan folder: {raw}")

    entries: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(real_target), key=str.lower)
    except OSError as exc:
        raise PermissionError(f"Gagal membaca folder: {exc}")

    for name in names:
        if name in IGNORED_DIRS:
            continue
        full = os.path.join(real_target, name)
        # M11: nama dan ukuran kredensial tidak ikut ditampilkan. Daftar itu
        # sendiri sudah membocorkan keberadaan `.env` / `id_rsa` beserta
        # ukurannya, dan penapisnya hanya satu baris.
        if _is_sensitive(full):
            continue
        is_dir = os.path.isdir(full)
        size = None
        if not is_dir:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
        entries.append({"name": name, "type": "dir" if is_dir else "file", "size": size})

    # M11 FIX 3 — `parent` salah hitung.
    #
    # Dulu: `relpath(target, dirname(target))` — yaitu jarak target ke
    # induknya sendiri, yang SELALU menghasilkan basename target. Tombol "↑"
    # di SettingsPage mengirim nilai itu kembali sebagai path, jadi ia
    # memuat ulang folder yang sama dan tidak pernah bisa naik satu level.
    # Yang dibutuhkan adalah path RELATIF milik induknya, dan induk itu juga
    # harus lolos allowed_roots() — dirname(REPO_ROOT) berada di luar root,
    # sehingga di root paling atas `parent` memang harus None.
    parent: str | None = None
    parent_real = os.path.realpath(os.path.dirname(real_target))
    if os.path.isdir(parent_real) and _is_allowed(parent_real):
        try:
            rel_parent = os.path.relpath(parent_real, REPO_ROOT).replace("\\", "/")
        except ValueError:
            rel_parent = ".."
        if rel_parent == ".":
            parent = "."
        elif not rel_parent.startswith(".."):
            parent = rel_parent

    try:
        rel = os.path.relpath(real_target, REPO_ROOT).replace("\\", "/")
    except ValueError:
        rel = "."
    return {
        "path": "." if rel == "." else rel,
        "absolute_path": os.path.realpath(real_target),
        "parent": parent,
        "entries": entries,
    }
