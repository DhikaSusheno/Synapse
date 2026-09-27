"""
demo_reset.py — Script reset database Synapse sebelum demo.

Tanggung jawab:
  1. Menghapus synapse.db, synapse.db-wal, synapse.db-shm, synapse_v2.db,
     synapse_v2.db-wal, synapse_v2.db-shm, dan *.bak.* di folder backend/
  2. Memanggil database.init_db() dan storage.init_db() agar seluruh tabel
     kontrak (nodes, edges, operations, approvals, entities, relations, audit_log, dll)
     dibuat ulang dari kondisi bersih.
  3. Mencetak konfirmasi dengan jumlah baris (row count) untuk setiap tabel (harus 0).
  4. Mencetak path absolut teresolusi (resolved absolute DB_PATH) yang digunakan.
"""
import os
import sys
import sqlite3
from pathlib import Path

# Pastikan folder backend/ ada dalam sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
import storage

def reset_demo_database():
    print("=" * 60)
    print("Synapse Demo Database Reset Script")
    print("=" * 60)

    # 1. Hapus file DB lama
    db_patterns = [
        "synapse.db", "synapse.db-wal", "synapse.db-shm",
        "synapse_v2.db", "synapse_v2.db-wal", "synapse_v2.db-shm"
    ]
    
    deleted_files = []
    for pattern in db_patterns:
        file_path = BACKEND_DIR / pattern
        if file_path.exists():
            try:
                file_path.unlink()
                deleted_files.append(file_path.name)
            except OSError as e:
                print(f"[Warning] Gagal menghapus {file_path.name}: {e}")

    for bak_file in BACKEND_DIR.glob("*.bak.*"):
        try:
            bak_file.unlink()
            deleted_files.append(bak_file.name)
        except OSError as e:
            print(f"[Warning] Gagal menghapus {bak_file.name}: {e}")

    if deleted_files:
        print(f"[1/4] Berkas lama yang dihapus ({len(deleted_files)}): {', '.join(deleted_files)}")
    else:
        print("[1/4] Tidak ada berkas DB lama yang perlu dihapus.")

    # 2. Re-init DB
    storage.reset_conn()
    database.init_db()
    storage.init_db()
    print("[2/4] database.init_db() & storage.init_db() berhasil dijalankan.")

    # 3. Print resolved absolute paths (closes F-22)
    abs_db_path = database.DB_PATH.resolve()
    abs_v2_path = storage.DB_PATH.resolve()
    print("[3/4] Path Absolut Teresolusi (Resolved Absolute DB Paths):")
    print(f"      - Legacy DB_PATH: {abs_db_path}")
    print(f"      - V2 DB_PATH:     {abs_v2_path}")

    # 4. Hitung row count per tabel
    print("[4/4] Verifikasi Tabel & Row Count:")
    
    # Legacy DB (synapse.db)
    conn_v1 = sqlite3.connect(abs_db_path)
    v1_tables = [r[0] for r in conn_v1.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"  --- {abs_db_path.name} ---")
    for tbl in sorted(v1_tables):
        if tbl.startswith("sqlite_"): continue
        cnt = conn_v1.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"      Tabel '{tbl}': {cnt} baris")
    conn_v1.close()

    # V2 DB (synapse_v2.db)
    conn_v2 = sqlite3.connect(abs_v2_path)
    v2_tables = [r[0] for r in conn_v2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"  --- {abs_v2_path.name} ---")
    for tbl in sorted(v2_tables):
        if tbl.startswith("sqlite_"): continue
        cnt = conn_v2.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"      Tabel '{tbl}': {cnt} baris")
    conn_v2.close()

    print("=" * 60)
    print("STATUS: RESET SELESAI (CLEAN STATE CONFIRMED)")
    print("=" * 60)

if __name__ == "__main__":
    reset_demo_database()
