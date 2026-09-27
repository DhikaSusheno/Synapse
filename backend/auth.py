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

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader

_LOG = logging.getLogger("synapse.auth")

TOKEN_HEADER = "X-Synapse-Token"

PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    # GitHub Integration (public for OAuth flow)
    "/api/github/auth/url",
    "/api/github/callback",
    "/api/github/auth/pat",
    "/api/github/user",
    "/api/github/repos",
    "/api/github/repos/",
    "/api/github/repos/{owner}/{repo}/tree",
    "/api/github/repos/{owner}/{repo}/contents",
    # LLM Provider Registry (read-only public)
    "/api/llm/providers",
    "/api/llm/providers/",
    "/api/llm/providers/{provider_id}",
    "/api/llm/providers/{provider_id}/models",
    # Graph (read-only)
    "/graph/nodes",
    "/graph/edges",
    "/graph/summary",
}

_ENV_TOKEN = os.environ.get("SYNAPSE_API_TOKEN", "").strip()
API_TOKEN: str = _ENV_TOKEN if _ENV_TOKEN else secrets.token_urlsafe(32)

if not _ENV_TOKEN:
    _LOG.warning(
        "SYNAPSE_API_TOKEN tidak disetel - backend membuat token acak. "
        "Token untukdevelopment ini: %s",
        API_TOKEN,
    )
else:
    if len(API_TOKEN) < 16:
        _LOG.warning(
            "SYNAPSE_API_TOKEN terlalu pendek (<16 karakter) - disarankan pakai "
            "token acak yang panjang."
        )

if not _ENV_TOKEN:
    _LOG.warning(
        "SYNAPSE_API_TOKEN tidak disetel - backend membuat token acak. "
        "Token untukdevelopment ini: %s",
        API_TOKEN,
    )
else:
    if len(API_TOKEN) < 16:
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
    _fernet = Fernet(_FERNET_KEY.encode() if len(_FERNET_KEY) == 32 else base64.urlsafe_b64decode(_FERNET_KEY + "=" * (-len(_FERNET_KEY) % 4)))


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
    return path in PUBLIC_PATHS


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
