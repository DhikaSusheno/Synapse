"""API-token authentication and CORS origin policy for the Synapse backend.

BUG-11 FIX: sebelumnya tidak ada autentikasi sama sekali dan CORS memakai
wildcard origin. Akibatnya halaman web mana pun yang dibuka di browser
korban bisa mengirim POST /propose_operation + /approve_operation +
/execute_operation dan menjalankan operasi sendiri tanpa persetujuan manusia.

Desain:
  - Token WAJIB ada. Kalau env SYNAPSE_API_TOKEN tidak diisi, backend membuat
    token acak saat start (fail-closed) dan meng-log-nya sekali. Tidak pernah
    ada kondisi "tanpa auth".
  - Perbandingan token memakai secrets.compare_digest (timing-safe).
  - Preflight OPTIONS tidak pernah butuh token; itu duties CORS middleware.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader

_LOG = logging.getLogger("synapse.auth")

TOKEN_HEADER = "X-Synapse-Token"

# Path yang TIDAK memerlukan token.
#
# Sempit by design. Frontend tidak butuh satu pun entri di sini: semua
# request-nya lewat route handler proxy app/backend/[...path], yang
# menyuntikkan SYNAPSE_API_TOKEN dari sisi server. .env.local.example juga
# menyuruh memakai NEXT_PUBLIC_BACKEND_URL=/backend, bukan backend langsung.
#
# Daftar lama (sebelum #62) membuat 19 entri publik, termasuk /graph/* yang
# membocorkan seluruh graph dan /api/github/auth/pat yang menulis kredensial.
# Enam entri di antaranya berisi placeholder FastAPI seperti
# "/api/github/repos/{owner}/{repo}/contents" - path tersebut tidak pernah
# cocok karena request nyata mengirim path yang sudah disubstitusi, jadi
# config-nya terlihat memberi akses publik tapi efeknya justru mengunci.
PUBLIC_PATHS = frozenset({
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
})


def _extra_public_paths() -> frozenset:
    """
    Path tambahan yang diminta lewat env `SYNAPSE_PUBLIC_PATHS`.

    Dipisah pisah dari PUBLIC_PATHS supaya jelas mana yang default aman dan
    mana yang opt-in. Dipisah juga dari parameter route: is_public_path()
    bekerja pada path konkret, bukan pada template FastAPI.
    """
    raw = os.environ.get("SYNAPSE_PUBLIC_PATHS", "").strip()
    if not raw:
        return frozenset()
    items = {p.strip().rstrip("/") or "/" for p in raw.split(",") if p.strip()}
    return frozenset(items)

_ENV_TOKEN = os.environ.get("SYNAPSE_API_TOKEN", "").strip()
API_TOKEN: str = _ENV_TOKEN if _ENV_TOKEN else secrets.token_urlsafe(32)

if not _ENV_TOKEN:
    _LOG.warning(
        "SYNAPSE_API_TOKEN tidak disetel - backend membuat token acak. "
        "Token untuk development ini: %s",
        API_TOKEN,
    )
elif len(API_TOKEN) < 16:
    _LOG.warning(
        "SYNAPSE_API_TOKEN terlalu pendek (<16 karakter) - disarankan pakai "
        "token acak yang panjang."
    )

# Fernet key untuk encrypt/decrypt token (simpan di env FERNET_KEY)
_FERNET_KEY = os.environ.get("FERNET_KEY", "").strip()
if not _FERNET_KEY:
    _LOG.warning("FERNET_KEY tidak disetel - generate random key (token tidak persisten)")
    _fernet = Fernet(Fernet.generate_key())
else:
    # Fernet key must be 32 url-safe base64-encoded bytes (44 chars)
    # Accept both raw 32-byte key and base64-encoded 44-char key
    try:
        # Try to decode as base64 first
        key_bytes = base64.urlsafe_b64decode(_FERNET_KEY + "=" * (-len(_FERNET_KEY) % 4))
        if len(key_bytes) == 32:
            _fernet = Fernet(base64.urlsafe_b64encode(key_bytes).decode())
        else:
            raise ValueError("Fernet key must be 32 bytes")
    except Exception:
        # If base64 decode fails, try as raw key
        try:
            _fernet = Fernet(_FERNET_KEY.encode())
        except Exception:
            _LOG.error("Invalid FERNET_KEY, generating random key")
            _fernet = Fernet(Fernet.generate_key())


def encrypt_token(token: str) -> str:
    """Encrypt token untuk storage."""
    return _fernet.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt token dari storage."""
    return _fernet.decrypt(encrypted.encode()).decode()


_token_header_scheme = APIKeyHeader(name=TOKEN_HEADER, auto_error=False)

DEFAULT_ORIGINS = (
    "http://localhost:3000,"
    "http://127.0.0.1:3000,"
    "http://localhost:3001,"
    "http://127.0.0.1:3001"
)


def allowed_origins() -> List[str]:
    """Origin browser yang diizinkan. Tidak pernah '*'."""
    raw = os.environ.get("SYNAPSE_ALLOWED_ORIGINS", "").strip()
    if not raw:
        raw = DEFAULT_ORIGINS
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return [o for o in origins if o != "*"] or list(DEFAULT_ORIGINS.split(","))


def is_public_path(path: str) -> bool:
    """
    True kalau path boleh diakses tanpa token.

    Trailing slash dinormalisasi supaya `/health/` dan `/health` dianggap sama,
    karena FastAPI bisa menerima keduanya lewat redirect.
    """
    if not path:
        return False
    normalized = path.rstrip("/") or "/"
    return normalized in PUBLIC_PATHS or normalized in _extra_public_paths()


def _extract_token(request: Request) -> Optional[str]:
    header = request.headers.get(TOKEN_HEADER)
    if header and header.strip():
        return header.strip()
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate:
            return candidate
    return None


def verify_token(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(candidate, API_TOKEN)


def require_api_key(request: Request) -> str:
    """FastAPI dependency untuk protecting route tertentu."""
    token = _extract_token(request)
    if not verify_token(token):
        raise HTTPException(
            status_code=401,
            detail=(
                "Token API hilang atau tidak valid. Kirim header "
                f"'{TOKEN_HEADER}: <token>' atau 'Authorization: Bearer <token>'."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token
