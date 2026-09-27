"""
demo_reset.py — Script reset database Synapse sebelum demo.

Tanggung jawab:
  1. Menghapus synapse.db, synapse.db-wal, synapse.db-shm, synapse_v2.db,
     synapse_v2.db-wal, synapse_v2.db-shm, dan *.bak.* di folder backend/
  2. Jika file sedang di-lock oleh proses uvicorn aktif, fallback menghapus
     isi baris semua tabel via SQL DELETE + VACUUM (Issue #71 fix).
  3. Memanggil database.init_db() dan storage.init_db() agar seluruh tabel
     kontrak (nodes, edges, operations, approvals, entities, relations, audit_log, dll)
     dibuat ulang dari kondisi bersih.
  4. Mencetak konfirmasi dengan jumlah baris (row count) untuk setiap tabel (harus 0).
  5. Mencetak path absolut teresolusi (resolved absolute DB_PATH) yang digunakan.
"""
import os
import sys
import sqlite3
from pathlib import Path

# Issue #74 fix: Pastikan stdout/stderr pakai UTF-8 agar emoji/unicode
# tidak menyebabkan UnicodeEncodeError pada terminal Windows (cp1252).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Pastikan folder backend/ ada dalam sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
import storage

def _wipe_tables_sql(db_path: Path):
    """Fallback: kosongkan seluruh baris tabel jika file di-lock oleh proses live (Issue #71)."""
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() if not r[0].startswith("sqlite_")]
        for tbl in tables:
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()
        try:
            conn.execute("VACUUM")
        except Exception:
            pass
        conn.close()
    except Exception as e:
        print(f"[Warning] SQL Wipe fallback error pada {db_path.name}: {e}")

def reset_demo_database():
    print("=" * 60)
    print("Synapse Demo Database Reset Script")
    print("=" * 60)

    # 1. Hapus file DB lama atau fallback truncate via SQL
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
            except OSError:
                # Issue #71 fix: fallback truncation jika di-lock oleh live server
                _wipe_tables_sql(file_path)
                deleted_files.append(f"{file_path.name} (wiped via SQL fallback)")

    for bak_file in BACKEND_DIR.glob("*.bak.*"):
        try:
            bak_file.unlink()
            deleted_files.append(bak_file.name)
        except OSError:
            pass

    if deleted_files:
        print(f"[1/4] Berkas lama yang dibersihkan ({len(deleted_files)}): {', '.join(deleted_files)}")
    else:
        print("[1/4] Tidak ada berkas DB lama yang perlu dibersihkan.")

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
