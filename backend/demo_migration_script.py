"""
demo_migration_script.py — Skenario Demo Guardian (BE-1 DhikaSusheno)

Skrip ini menjalankan skenario demo Synapse secara berurutan lewat HTTP API:
  1. Propose + approve + execute migration SUKSES (tambah kolom 'tag')
  2. Propose migration KONFLIK (target sama, dalam window 15 menit)
  3. Propose + approve + execute migration GAGAL (SQL salah → auto-rollback)
  4. Verifikasi tabel masih utuh setelah rollback

Jalankan SETELAH uvicorn main:app berjalan:
  python demo_migration_script.py

Output: log tiap langkah + hasil verifikasi final
"""
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def api(method: str, path: str, body: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        return {"error": f"HTTP {e.code}", "detail": body_text}
    except Exception as e:
        return {"error": str(e)}


def sep(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def main():
    sep("0. Health check")
    r = api("GET", "/health")
    print(f"Server: {r}")
    if r.get("status") != "ok":
        print("❌ Server tidak merespons. Jalankan: uvicorn main:app --reload")
        sys.exit(1)
    print("✅ Server OK")

    # ──────────────────────────────────────────────────────────────────────
    sep("1. Migration SUKSES — tambah kolom 'tag' ke tabel nodes")
    # ──────────────────────────────────────────────────────────────────────
    r1 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "ALTER TABLE nodes ADD COLUMN tag TEXT DEFAULT NULL;"},
        "target": "synapse.db::nodes",
    })
    print(f"propose → {r1.get('status')} | blast={r1.get('blast_radius')} | "
          f"conflicts={len(r1.get('conflicts', []))}")
    op_id_1 = r1.get("operation_id")

    # Approve
    r_approve = api("POST", "/approve_operation", {
        "operation_id": op_id_1,
        "decision": "approved",
        "note": "demo: migration sukses",
    })
    print(f"approve → {r_approve.get('new_status')}")

    # Execute
    r_exec = api("POST", "/execute_operation", {"operation_id": op_id_1})
    print(f"execute → status={r_exec.get('status')} | "
          f"ok={r_exec.get('ok')} | {r_exec.get('verify_message', r_exec.get('exec_error', ''))}")
    assert r_exec.get("ok"), f"❌ Migration sukses gagal: {r_exec}"
    print("✅ Migration sukses — kolom 'tag' ditambahkan")

    time.sleep(0.5)

    # ──────────────────────────────────────────────────────────────────────
    sep("2. Migration KONFLIK — target sama dalam 15 menit terakhir")
    # ──────────────────────────────────────────────────────────────────────
    r2 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "ALTER TABLE nodes ADD COLUMN priority INTEGER DEFAULT 0;"},
        "target": "synapse.db::nodes",   # target SAMA dengan op1 → konflik!
    })
    conflicts = r2.get("conflicts", [])
    print(f"propose → conflicts={len(conflicts)} | "
          f"requires_approval={r2.get('requires_approval')}")
    print(f"message: {r2.get('message')}")
    assert len(conflicts) > 0, "❌ Konflik seharusnya terdeteksi!"
    assert r2.get("requires_approval") is True, "❌ require_approval harus True saat konflik!"
    print("✅ Konflik terdeteksi — approval wajib, tidak bisa auto-execute")

    time.sleep(0.5)

    # ──────────────────────────────────────────────────────────────────────
    sep("3. Migration GAGAL (SQL rusak) → auto-rollback")
    # ──────────────────────────────────────────────────────────────────────
    r3 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "THIS IS NOT VALID SQL @@@@;"},
        "target": "synapse.db::broken_target",  # target berbeda agar tidak konflik dengan op1
    })
    op_id_3 = r3.get("operation_id")
    print(f"propose → {r3.get('status')} | blast={r3.get('blast_radius')}")

    # Approve (paksa jalan meskipun SQL rusak)
    api("POST", "/approve_operation", {
        "operation_id": op_id_3,
        "decision": "approved",
        "note": "demo: sengaja rusak untuk trigger rollback",
    })

    r_exec3 = api("POST", "/execute_operation", {"operation_id": op_id_3})
    print(f"execute → ok={r_exec3.get('ok')} | status={r_exec3.get('status')}")
    print(f"exec_error: {r_exec3.get('exec_error', '')}")
    print(f"rollback_ok: {r_exec3.get('rollback_ok')} | {r_exec3.get('rollback_message', '')}")
    assert r_exec3.get("ok") is False, "❌ Harusnya gagal!"
    assert r_exec3.get("status") in ("rolled_back", "failed"), "❌ Status harus rolled_back/failed"
    print(f"✅ Migration gagal terdeteksi → auto-rollback ke status: {r_exec3.get('status')}")

    # ──────────────────────────────────────────────────────────────────────
    sep("4. Fail-closed — tool tidak dikenal wajib ditolak")
    # ──────────────────────────────────────────────────────────────────────
    r4 = api("POST", "/propose_operation", {
        "tool_name": "unknown.dangerous_tool",
        "params": {},
        "target": "production-db",
    })
    print(f"propose → blast={r4.get('blast_radius')} | "
          f"requires_approval={r4.get('requires_approval')}")
    assert r4.get("blast_radius") == "unknown", "❌ blast_radius harus 'unknown'"
    assert r4.get("requires_approval") is True, "❌ harus require approval"
    print("✅ Fail-closed: tool tidak dikenal → wajib approval manusia")

    # ──────────────────────────────────────────────────────────────────────
    sep("5. Verifikasi final — tabel DB masih utuh")
    # ──────────────────────────────────────────────────────────────────────
    try:
        conn = sqlite3.connect("synapse.db")
        tables = {
            row[0] for row in
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        required = {"nodes", "edges", "operations", "approvals"}
        missing = required - tables
        if missing:
            print(f"❌ Tabel hilang: {missing}")
        else:
            print(f"✅ Semua tabel kontrak masih ada: {required}")
    except Exception as e:
        print(f"❌ Tidak bisa koneksi ke synapse.db: {e}")

    # ──────────────────────────────────────────────────────────────────────
    sep("6. Operasi history")
    # ──────────────────────────────────────────────────────────────────────
    ops = api("GET", "/operations")
    print(f"Total operasi tercatat: {len(ops)}")
    for op in ops:
        print(f"  [{op.get('status', '?').upper():25}] {op.get('tool_name')} → {op.get('target_node_id')}")

    sep("✅ DEMO SELESAI — semua skenario berhasil diverifikasi")


if __name__ == "__main__":
    main()
