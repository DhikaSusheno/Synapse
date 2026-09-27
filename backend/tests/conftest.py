"""
Fixture bersama untuk seluruh test backend.

BUG-11 menambah autentikasi token ke semua route (kecuali /health, /docs,
/openapi.json). Test yang ada sebelumnya memakai TestClient tanpa header,
jadi setelah gerbang token dipasang semuanya dapat 401.

Daripada mengubah puluhan call site di test lama, fixture ini menyuntikkan
header token ke setiap request TestClient secara otomatis. Test yang memang
mau menguji penolakan token tetap bisa memakai TestClient langsung di luar
fixture, atau meng-override header secara eksplisit.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402

TEST_TOKEN = "test-suite-token-0123456789abcdef"
auth.API_TOKEN = TEST_TOKEN


@pytest.fixture(autouse=True)
def inject_api_token(monkeypatch):
    from starlette.testclient import TestClient

    original_request = TestClient.request

    def request_with_token(self, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault(auth.TOKEN_HEADER, auth.API_TOKEN)
        kwargs["headers"] = headers
        return original_request(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_token)
    yield
