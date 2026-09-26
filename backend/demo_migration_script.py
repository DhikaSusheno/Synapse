"""
demo_migration_script.py - Skenario Demo Guardian (BE-1 DhikaSusheno)

Skenario:
  1. Propose op-A + approve  (status: approved, belum execute)
  2. Propose op-B target SAMA -> konflik terdeteksi (op-A masih approved)
  3. Execute op-A -> SUKSES verified
  4. Propose + approve + execute op-C SQL RUSAK -> auto-rollback
  5. Fail-closed: tool tidak dikenal -> blast=unknown, requires_approval=True
  6. Verifikasi tabel DB masih utuh

Jalankan:
  set PYTHONIOENCODING=utf-8 && python demo_migration_script.py
"""
import sys
import time
import json
import sqlite3
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


def api(method, path, body=None):
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
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


def sep(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def ok(msg):
    print(f"[PASS] {msg}")


def fail(msg):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main():
    sep("0. Health Check")
    r = api("GET", "/health")
    if r.get("status") != "ok":
        fail(f"Server tidak merespons: {r}")
    ok(f"Server UP (v{r.get('version','?')})")

    # ------------------------------------------------------------------
    sep("1. Propose op-A + Approve -> status: approved (belum execute)")
    # ------------------------------------------------------------------
    r1 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "ALTER TABLE nodes ADD COLUMN tag TEXT DEFAULT NULL;"},
        "target": "synapse.db::nodes",
    })
    if not r1.get("ok"):
        fail(f"propose op-A gagal: {r1}")
    op_id_a = r1["operation_id"]
    print(f"  propose -> blast={r1['blast_radius']} | requires_approval={r1['requires_approval']} | conflicts={len(r1.get('conflicts',[]))}")

    ra = api("POST", "/approve_operation", {
        "operation_id": op_id_a, "decision": "approved", "note": "demo step 1",
    })
    if not ra.get("ok"):
        fail(f"approve op-A gagal: {ra}")
    print(f"  approve -> status={ra.get('status')}")
    ok("op-A approved, belum di-execute")

    # ------------------------------------------------------------------
    sep("2. Konflik: op-B ke target SAMA saat op-A masih 'approved'")
    # ------------------------------------------------------------------
    r2 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "ALTER TABLE nodes ADD COLUMN priority INTEGER DEFAULT 0;"},
        "target": "synapse.db::nodes",
    })
    conflicts = r2.get("conflicts", [])
    print(f"  propose -> conflicts={len(conflicts)} | requires_approval={r2.get('requires_approval')}")
    if len(conflicts) == 0:
        fail("Konflik seharusnya terdeteksi! op-A masih approved")
    if not r2.get("requires_approval"):
        fail("requires_approval harus True saat ada konflik!")
    ok(f"Konflik terdeteksi ({len(conflicts)} op) - approval wajib")

    # ------------------------------------------------------------------
    sep("3. Execute op-A -> SUKSES, status: verified")
    # ------------------------------------------------------------------
    re_a = api("POST", "/execute_operation", {"operation_id": op_id_a})
    print(f"  execute -> ok={re_a.get('ok')} | status={re_a.get('status')}")
    if not re_a.get("ok") or re_a.get("status") != "verified":
        fail(f"Execute op-A gagal: {re_a}")
    ok("Migration sukses, status: verified")

    time.sleep(0.3)

    # ------------------------------------------------------------------
    sep("4. Migration GAGAL (SQL rusak) -> auto-rollback")
    # ------------------------------------------------------------------
    r3 = api("POST", "/propose_operation", {
        "tool_name": "db.run_migration",
        "params": {"sql": "THIS IS NOT VALID SQL @@@@;"},
        "target": "synapse.db::broken",
    })
    op_id_c = r3.get("operation_id")
    print(f"  propose -> blast={r3.get('blast_radius')}")
    api("POST", "/approve_operation", {
        "operation_id": op_id_c, "decision": "approved", "note": "sengaja rusak",
    })
    re_c = api("POST", "/execute_operation", {"operation_id": op_id_c})
    print(f"  execute -> ok={re_c.get('ok')} | status={re_c.get('status')}")
    print(f"  error   -> {str(re_c.get('error', re_c.get('exec_error', '')))[:80]}")
    if re_c.get("ok") is not False:
        fail("Seharusnya gagal karena SQL rusak!")
    if re_c.get("status") not in ("rolled_back", "failed"):
        fail(f"Status harus rolled_back/failed, dapat: {re_c.get('status')}")
    ok(f"Auto-rollback triggered, status: {re_c.get('status')}")

    time.sleep(0.3)

    # ------------------------------------------------------------------
    sep("5. Fail-closed: tool tidak dikenal")
    # ------------------------------------------------------------------
    r4 = api("POST", "/propose_operation", {
        "tool_name": "unknown.dangerous_tool",
        "params": {},
        "target": "production-db",
    })
    print(f"  propose -> blast={r4.get('blast_radius')} | requires_approval={r4.get('requires_approval')}")
    if r4.get("blast_radius") != "unknown":
        fail(f"blast_radius harus 'unknown', dapat: {r4.get('blast_radius')}")
    if not r4.get("requires_approval"):
        fail("requires_approval harus True untuk tool tidak dikenal!")
    ok("Fail-closed OK: tool tidak dikenal -> wajib approval")

    # ------------------------------------------------------------------
    sep("6. Verifikasi tabel DB masih utuh setelah rollback")
    # ------------------------------------------------------------------
    try:
        conn = sqlite3.connect("synapse.db")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        missing = {"nodes", "edges", "operations", "approvals"} - tables
        if missing:
            fail(f"Tabel hilang: {missing}")
        ok(f"Semua tabel kontrak ada: {sorted(tables & {'nodes','edges','operations','approvals'})}")
    except Exception as e:
        fail(f"DB error: {e}")

    # ------------------------------------------------------------------
    sep("7. Ringkasan operasi")
    # ------------------------------------------------------------------
    ops = api("GET", "/operations?limit=20")
    if isinstance(ops, list):
        print(f"  Total: {len(ops)}")
        for op in ops:
            print(f"    [{op.get('status','?').upper():20}] {op.get('tool_name')} -> {op.get('target_node_id','')[:40]}")

    sep("DEMO SELESAI - Semua skenario PASS")


if __name__ == "__main__":
    main()
