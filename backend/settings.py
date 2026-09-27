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


def browse(path: str = "") -> Dict[str, Any]:
    raw = (path or "").strip()
    target = os.path.join(REPO_ROOT, raw) if raw else REPO_ROOT
    if not os.path.exists(target):
        raise FileNotFoundError(f"Path tidak ditemukan: {raw}")
    if not os.path.isdir(target):
        raise NotADirectoryError(f"Bukan folder: {raw}")
    if not _is_allowed(target):
        raise PermissionError("Path di luar workspace yang diizinkan")

    entries: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(target), key=str.lower)
    except OSError as exc:
        raise PermissionError(f"Gagal membaca folder: {exc}")

    for name in names:
        if name in IGNORED_DIRS:
            continue
        full = os.path.join(target, name)
        is_dir = os.path.isdir(full)
        size = None
        if not is_dir:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
        entries.append({"name": name, "type": "dir" if is_dir else "file", "size": size})

    parent_real = os.path.realpath(os.path.dirname(target))
    parent = None
    if any(
        parent_real == os.path.realpath(r) or parent_real.startswith(os.path.realpath(r) + os.sep)
        for r in allowed_roots()
    ):
        parent = os.path.relpath(target, parent_real).replace("\\", "/") or "."

    try:
        rel = os.path.relpath(target, REPO_ROOT).replace("\\", "/")
    except ValueError:
        rel = "."
    return {
        "path": "." if rel == "." else rel,
        "absolute_path": os.path.realpath(target),
        "parent": parent,
        "entries": entries,
    }
