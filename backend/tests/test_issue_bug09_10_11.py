"""
Regression test untuk BUG-09, BUG-10, dan BUG-11.

BUG-09 [HIGH] approve_operation() bisa menimpa operasi yang sedang 'executing'.
  Guard sebelumnya hanya menolak status TERMINAL. 'executing' dan
  'executed_unverified' tidak termasuk terminal, jadi keduanya lolos dan
  statusnya ditulis ulang jadi 'approved'. Karena CAS di execute_operation()
  mengizinkan status 'approved', operasi itu lalu bisa dieksekusi lagi:
  propose -> execute -> approve -> execute = double execution.

BUG-10 [MEDIUM] list_pending_approvals() membaca kolom DB, execute_operation()
  membaca rule engine. Kalau aturan berubah setelah propose, kolom DB jadi
  basi: operasi butuh approval saat dieksekusi tapi tidak pernah muncul di
  daftar pending -> dead-end yang tidak bisa di-approve dan tidak bisa jalan.

BUG-11 [CRITICAL] tidak ada autentikasi + CORS allow_origins="*".
  Halaman web mana pun bisa propose + approve + execute sendiri dari browser.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth  # noqa: E402
import guardian  # noqa: E402

SCHEMA = """
CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, name TEXT,
                    meta_json TEXT DEFAULT '{}');
CREATE TABLE edges (id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
                    relationship TEXT, confidence REAL DEFAULT 1.0);
CREATE TABLE operations (
    id TEXT PRIMARY KEY, tool_name TEXT NOT NULL,
    params_json TEXT DEFAULT '{}', target_node_id TEXT,
    blast_radius TEXT, reversibility_class TEXT,
    status TEXT DEFAULT 'pending', snapshot_ref TEXT, rollback_command TEXT,
    requires_approval INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    executed_at TEXT, verified_at TEXT);
CREATE TABLE approvals (operation_id TEXT PRIMARY KEY, decision TEXT,
                        decided_at TEXT, note TEXT DEFAULT '');
"""


def _mk_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def _add_op(db: Path, op_id: str, tool: str, status: str, requires: int) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        """INSERT INTO operations
           (id, tool_name, params_json, target_node_id, blast_radius,
            reversibility_class, status, requires_approval, created_at)
           VALUES (?, ?, '{}', ?, 'high', 'needs_snapshot', ?, ?,
                   '2026-01-01T00:00:00')""",
        (op_id, tool, f"operation_target::{op_id}", status, requires),
    )
    conn.commit()
    conn.close()


def _status_of(db: Path, op_id: str) -> str:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM operations WHERE id=?", (op_id,)).fetchone()
    conn.close()
    return row["status"]


# ---------------------------------------------------------------------------
# BUG-09
# ---------------------------------------------------------------------------

def test_approvable_statuses_excludes_inflight():
    assert guardian.APPROVABLE_STATUSES == frozenset({"pending", "approved"})
    assert "executing" not in guardian.APPROVABLE_STATUSES
    assert "executed_unverified" not in guardian.APPROVABLE_STATUSES


def test_approvable_is_stricter_than_terminal_allowlist():
    for status in ("executing", "executed_unverified", "verified",
                   "rolled_back", "failed", "denied"):
        assert status not in guardian.APPROVABLE_STATUSES, (
            f"{status!r} tidak boleh bisa di-approve"
        )


@pytest.mark.parametrize("busy_status", ["executing", "executed_unverified"])
def test_approve_cannot_overwrite_inflight_operation(tmp_path, monkeypatch, busy_status):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-busy", "file.delete", busy_status, 1)

    result = guardian.approve_operation("op-busy", "approved")

    assert result["ok"] is False, f"{busy_status} tidak boleh bisa di-approve"
    after = _status_of(db, "op-busy")
    assert after == busy_status, f"status berubah dari {busy_status!r} jadi {after!r}"


def test_deny_cannot_overwrite_inflight_operation(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-busy", "file.delete", "executing", 1)

    result = guardian.approve_operation("op-busy", "denied")

    assert result["ok"] is False
    assert _status_of(db, "op-busy") == "executing"


def test_approve_and_deny_still_work_from_pending(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-1", "file.delete", "pending", 1)
    _add_op(db, "op-2", "file.delete", "pending", 1)

    assert guardian.approve_operation("op-1", "approved")["ok"] is True
    assert guardian.approve_operation("op-2", "denied")["ok"] is True
    assert _status_of(db, "op-1") == "approved"
    assert _status_of(db, "op-2") == "denied"


def test_deny_can_revoke_existing_approval(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-x", "file.delete", "pending", 1)

    assert guardian.approve_operation("op-x", "approved")["ok"] is True
    result = guardian.approve_operation("op-x", "denied")
    assert result["ok"] is True
    assert result["status"] == "denied"
    assert _status_of(db, "op-x") == "denied"


@pytest.mark.parametrize("terminal", ["verified", "rolled_back", "failed", "denied"])
def test_terminal_statuses_still_rejected(tmp_path, monkeypatch, terminal):
    db = tmp_path / f"g-{terminal}.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-t", "file.delete", terminal, 1)

    assert guardian.approve_operation("op-t", "approved")["ok"] is False
    assert _status_of(db, "op-t") == terminal


# ---------------------------------------------------------------------------
# BUG-10
# ---------------------------------------------------------------------------

def test_pending_uses_rule_engine_not_stale_column(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    # kolom DB = 1 -> tetap butuh approval
    _add_op(db, "op-legacy", "service.restart", "pending", 1)
    # kolom DB = 0 tapi rule fail-closed bilang butuh approval
    _add_op(db, "op-newrule", "tools.unknown_thing", "pending", 0)

    pending_ids = {row["id"] for row in guardian.list_pending_approvals()["pending"]}
    assert "op-legacy" in pending_ids, "kolom DB=1 harus tetap masuk daftar"
    assert "op-newrule" in pending_ids, (
        "BUG-10: rule engine bilang butuh approval, jadi harus muncul di daftar "
        "pending walau kolom DB = 0"
    )


def test_list_pending_follows_rule_change_after_propose(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-drift", "service.restart", "pending", 0)

    before = {row["id"] for row in guardian.list_pending_approvals()["pending"]}
    assert "op-drift" not in before, "sebelum aturan berubah memang tidak butuh approval"

    original_rules = list(guardian.RULES)
    try:
        guardian.RULES.insert(0, {
            "match": "service.restart",
            "blast_radius": "medium",
            "reversibility": "needs_snapshot",
            "require_approval": True,
            "prefix_match": True,
        })
        after = {row["id"] for row in guardian.list_pending_approvals()["pending"]}
        assert "op-drift" in after, (
            "BUG-10: setelah aturan berubah jadi butuh approval, operasi harus "
            "muncul di daftar pending supaya tidak dead-end"
        )
    finally:
        guardian.RULES[:] = original_rules


def test_operations_without_approval_stay_out_of_pending(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op-noappr", "service.restart", "pending", 0)

    ids = {row["id"] for row in guardian.list_pending_approvals()["pending"]}
    assert "op-noappr" not in ids


@pytest.mark.parametrize("status", ["approved", "executing", "verified", "failed"])
def test_non_pending_operations_not_listed(tmp_path, monkeypatch, status):
    db = tmp_path / f"g-{status}.db"
    _mk_db(db)
    monkeypatch.setattr(guardian, "_db_path", lambda: str(db))
    _add_op(db, "op", "file.delete", status, 1)
    assert guardian.list_pending_approvals()["count"] == 0, (
        f"status {status!r} tidak boleh muncul di pending"
    )


def test_effective_requires_approval_matches_execute_derivation():
    """Helper yang dipakai list_pending harus sama dengan yang dipakai execute."""
    class FakeOp(dict):
        pass

    for tool, db_flag in (
        ("file.delete", 0),
        ("file.delete", 1),
        ("service.restart", 0),
        ("service.restart", 1),
        ("tools.unknown_thing", 0),
        ("tools.unknown_thing", 1),
    ):
        op = FakeOp(tool_name=tool, requires_approval=db_flag)
        expected = bool(guardian._get_rule(tool)["require_approval"]) or db_flag == 1
        assert guardian._effective_requires_approval(op) is expected, (
            f"{tool} requires_approval={db_flag} tidak konsisten"
        )


# ---------------------------------------------------------------------------
# BUG-11
# ---------------------------------------------------------------------------

def test_api_token_always_exists():
    assert auth.API_TOKEN, "token API harus selalu ada (fail-closed)"
    assert len(auth.API_TOKEN) >= 16


def test_cors_origins_never_wildcard():
    origins = auth.allowed_origins()
    assert origins, "harus ada minimal satu origin"
    assert "*" not in origins, "allow_origins tidak boleh '*' (BUG-11)"


def test_verify_token_rejects_missing_and_wrong():
    assert auth.verify_token(None) is False
    assert auth.verify_token("") is False
    assert auth.verify_token("token-palsu") is False
    assert auth.verify_token(auth.API_TOKEN) is True


def test_public_paths_allowlist():
    for path in ("/health", "/docs", "/openapi.json"):
        assert auth.is_public_path(path), f"{path} seharusnya publik"


def test_guard_paths_are_not_public():
    for path in ("/propose_operation", "/approve_operation", "/execute_operation"):
        assert not auth.is_public_path(path), f"{path} tidak boleh publik"
