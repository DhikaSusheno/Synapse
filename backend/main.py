"""
main.py — Synapse MCP Server
BE-2 Masrendra : Cortex endpoints + SSE stream + 4 fitur unik
BE-1 DhikaSusheno: Guardian endpoints (terintegrasi oleh Masrendra)

Jalankan: uvicorn main:app --reload
Docs    : http://localhost:8000/docs

=== Semua Endpoint ===
[Cortex - BE-2 Masrendra]
  POST /understand_repo       — ingest repo ke graph (AST + docs)
  POST /explain_topic         — tanya tentang modul/fungsi dari graph
  POST /review_artifact       — scoring file/diff 4 dimensi
  GET  /repo_health           — skor kesehatan repo (UNIK)
  GET  /complexity_report     — ranking fungsi paling kompleks (UNIK)
  POST /find_path             — jalur antar dua entitas di graph (UNIK)
  POST /suggest_refactor      — saran refactor berbasis graph (UNIK)

[Guardian - BE-1 DhikaSusheno]
  POST /propose_operation     — klasifikasi risiko + conflict check + plan
  POST /execute_operation     — eksekusi + verifikasi + auto-rollback
  GET  /list_pending_approvals— daftar operasi pending approval
  POST /approve_operation     — approve / deny operasi
  GET  /operations            — riwayat semua operasi

[Graph - Helper Frontend]
  GET  /graph/nodes           — semua node di graph
  GET  /graph/edges           — semua edge di graph
  GET  /graph/summary         — ringkasan jumlah node & edge

[SSE]
  GET  /stream                — Server-Sent Events real-time

[System]
  GET  /health                — health check
"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sqlite3

from database import init_db, DB_PATH
import storage
import cortex
import guardian

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Synapse Backend",
    description="Reversible, conflict-aware understanding layer for AI coding agents",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    init_db()
    # Skema v2 (storage.py) -> file TERPISA synapse_v2.db, bukan synapse.db.
    # Tetap di-init di startup supaya tabel entities/relations/actions/decisions/
    # audit_log selalu ada; kalau tidak, pemakai pertama akan kena
    # "no such table: entities" saat runtime.
    storage.init_db()
    # BUG-08 FIX: set event loop reference di cortex agar _emit() thread-safe
    # (Guardian endpoint adalah sync, dipanggil dari threadpool — perlu call_soon_threadsafe)
    # BUG-E FIX: get_running_loop() adalah cara yang benar dalam async context (Python 3.7+)
    # get_event_loop() deprecated di Python 3.10+ dan error di Python 3.12+
    import asyncio
    cortex.set_event_loop(asyncio.get_running_loop())
    print("[Synapse] Server ready. Visit http://localhost:8000/docs")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class UnderstandRepoRequest(BaseModel):
    repo_path: str

class ExplainTopicRequest(BaseModel):
    topic: str

class ReviewArtifactRequest(BaseModel):
    path_or_diff: str

class FindPathRequest(BaseModel):
    from_node: str
    to_node: str

class SuggestRefactorRequest(BaseModel):
    node_name: str

class ProposeOperationRequest(BaseModel):
    tool_name: str
    params: dict = {}
    target: str

class ExecuteOperationRequest(BaseModel):
    operation_id: str

class ApproveOperationRequest(BaseModel):
    operation_id: str
    decision: str  # 'approved' | 'denied'
    note: str = ""


# ---------------------------------------------------------------------------
# CORTEX endpoints — BE-2 Masrendra
# ---------------------------------------------------------------------------

@app.post("/understand_repo", tags=["Cortex"])
def understand_repo(req: UnderstandRepoRequest):
    """
    Ingest sebuah repo ke SQLite graph.
    - Parse AST via tree-sitter (file, fungsi, kelas, import) + complexity score
    - Baca file doc → edge DOCUMENTS ke kode
    - Emit SSE 'ingest_progress' per-doc + 'graph_update' di akhir
    """
    result = cortex.understand_repo(req.repo_path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/explain_topic", tags=["Cortex"])
def explain_topic(req: ExplainTopicRequest):
    """
    Jawab pertanyaan tentang suatu topik/modul dari knowledge graph.
    Return: definition → mental_model → example (snippet kode),
            related_nodes, callers, how_to_use, complexity_note.
    """
    result = cortex.explain_topic(req.topic)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/review_artifact", tags=["Cortex"])
def review_artifact(req: ReviewArtifactRequest):
    """
    Scoring artifact (path file atau teks diff) pada 4 dimensi:
    completeness, clarity, correctness_vs_spec, risk.
    Deteksi otomatis apakah input adalah git diff (churn analysis).
    Verdict: pass | needs_work | block.
    """
    result = cortex.review_artifact(req.path_or_diff)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# CORTEX — Fitur Unik BE-2
# ---------------------------------------------------------------------------

@app.get("/repo_health", tags=["Cortex - Unik"])
def repo_health():
    """
    📊 Laporan kesehatan repo berbasis knowledge graph.
    - Health score 0–100
    - Coverage dokumentasi (% file punya DOCUMENTS edge)
    - Dead code candidates (simbol tanpa incoming edge / caller)
    - High complexity symbols (McCabe >= 10)
    - Isolated nodes & hub nodes
    """
    return cortex.repo_health()


@app.get("/complexity_report", tags=["Cortex - Unik"])
def complexity_report(top_n: int = Query(default=10, ge=1, le=50)):
    """
    📈 Ranking fungsi/kelas paling kompleks di repo.
    Risk level: low (< 5) | medium (5–9) | high (10–14) | critical (≥ 15).
    Berguna untuk menentukan prioritas refactor.
    """
    return cortex.complexity_report(top_n=top_n)


@app.post("/find_path", tags=["Cortex - Unik"])
def find_path(req: FindPathRequest):
    """
    🔍 Cari jalur terpendek antara dua entitas di knowledge graph.
    Menjawab: "Bagaimana modul A mempengaruhi modul B?"
    Contoh: { "from_node": "main", "to_node": "database" }
    """
    result = cortex.find_path(req.from_node, req.to_node)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/suggest_refactor", tags=["Cortex - Unik"])
def suggest_refactor(req: SuggestRefactorRequest):
    """
    🔧 Saran refactor otomatis berbasis graph untuk sebuah entitas.
    Mendeteksi: complexity tinggi, God Object, dead code, missing docs.
    """
    result = cortex.suggest_refactor(req.node_name)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# GUARDIAN endpoints — BE-1 DhikaSusheno (diintegrasikan oleh Masrendra)
# ---------------------------------------------------------------------------

@app.post("/propose_operation", tags=["Guardian"])
def propose_operation(req: ProposeOperationRequest):
    """
    🛡️ Guardian Step 1: Propose operasi berisiko.
    - Klasifikasi blast_radius via rule table (SYNAPSE.md 4.4)
    - Conflict detection: cek operasi lain yg menyentuh target sama (window 10 menit)
    - Buat reversibility plan (snapshot strategy)
    - Simpan ke DB dengan status 'pending'

    Contoh DB migration:
      { "tool_name": "db.run_migration",
        "params": {"sql": "ALTER TABLE nodes ADD COLUMN tag TEXT"},
        "target": "synapse.db" }
    """
    result = guardian.propose_operation(req.tool_name, req.params, req.target)
    return result


@app.post("/execute_operation", tags=["Guardian"])
def execute_operation(req: ExecuteOperationRequest):
    """
    🛡️ Guardian Step 2: Eksekusi operasi yang sudah diapprove.
    - Snapshot otomatis sebelum eksekusi
    - Jalankan operasi
    - Verifikasi post-conditions
    - Auto-rollback jika verifikasi gagal
    - Emit SSE di setiap state transition

    Status flow:
      pending → approved → executing → verified
                                     ↘ rolled_back (jika gagal)
    """
    result = guardian.execute_operation(req.operation_id)
    return result


@app.get("/list_pending_approvals", tags=["Guardian"])
def list_pending_approvals():
    """🛡️ Daftar semua operasi yang menunggu approval manusia."""
    return guardian.list_pending_approvals()


@app.post("/approve_operation", tags=["Guardian"])
def approve_operation(req: ApproveOperationRequest):
    """
    ✅ Approve atau deny operasi yang sedang pending.
    decision: 'approved' | 'denied'
    """
    result = guardian.approve_operation(req.operation_id, req.decision, req.note)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/operations", tags=["Guardian"])
def list_operations(
    status: str = None,
    limit: int = Query(default=20, ge=1, le=100)
):
    """
    📋 Riwayat semua operasi. Filter by status opsional.
    Status: pending | approved | executing | executed_unverified |
            verified | failed | rolled_back | denied
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if status:
        rows = conn.execute(
            "SELECT * FROM operations WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM operations ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    
    ops = [dict(r) for r in rows]
    
    # Tambahkan conflicts dari edges table (relationship = 'CONFLICTS_WITH')
    if ops:
        op_ids = [op["id"] for op in ops]
        placeholders = ",".join("?" * len(op_ids))
        conflict_rows = conn.execute(
            f"""
            SELECT source_id, target_id
            FROM edges
            WHERE relationship = 'CONFLICTS_WITH'
              AND source_id IN ({placeholders})
            """,
            op_ids
        ).fetchall()
        
        conflicts_by_op = {}
        for row in conflict_rows:
            conflicts_by_op.setdefault(row["source_id"], []).append(row["target_id"])
        
        for op in ops:
            op["conflicts"] = conflicts_by_op.get(op["id"], [])
    
    conn.close()
    return ops


# ---------------------------------------------------------------------------
# SSE stream — dikonsumsi frontend live
# ---------------------------------------------------------------------------

@app.get("/stream", tags=["SSE"])
async def stream_events():
    """
    📡 Server-Sent Events stream — semua event real-time dari Cortex & Guardian.

    Event yang dikirim:
      graph_update       — node/edge baru setelah understand_repo
      ingest_progress    — progress per-doc saat ingest
      operation_proposed — Guardian: operasi baru diusulkan
      operation_executing— Guardian: operasi sedang berjalan
      operation_verified — Guardian: operasi sukses terverifikasi
      operation_rolled_back — Guardian: operasi di-rollback
      operation_failed   — Guardian: operasi gagal tanpa rollback
      operation_approved / operation_denied — keputusan approval
      review_done        — hasil review artifact
      health_report      — hasil repo_health
      refactor_suggestion— hasil suggest_refactor

    Format: text/event-stream → data: <json>\\n\\n
    """
    q = cortex.subscribe_sse()

    async def event_generator() -> AsyncGenerator[str, None]:
        yield 'data: {"event": "connected", "data": {}}\n\n'
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"event": "heartbeat", "data": {}}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            cortex.unsubscribe_sse(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Graph query — helper untuk frontend
# ---------------------------------------------------------------------------

@app.get("/graph/nodes", tags=["Graph"])
def get_all_nodes(type: str = None):
    """Ambil semua node dari graph. Filter by type opsional."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if type:
        rows = conn.execute(
            "SELECT * FROM nodes WHERE type=? ORDER BY created_at DESC", (type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM nodes ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/graph/edges", tags=["Graph"])
def get_all_edges(relationship: str = None):
    """Ambil semua edge dari graph. Filter by relationship opsional."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if relationship:
        rows = conn.execute(
            "SELECT * FROM edges WHERE relationship=? ORDER BY created_at DESC",
            (relationship,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM edges ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/graph/summary", tags=["Graph"])
def get_graph_summary():
    """Ringkasan graph: jumlah node per type dan edge per relationship."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    node_counts = {
        row["type"]: row["cnt"]
        for row in conn.execute(
            "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type"
        ).fetchall()
    }
    edge_counts = {
        row["relationship"]: row["cnt"]
        for row in conn.execute(
            "SELECT relationship, COUNT(*) as cnt FROM edges GROUP BY relationship"
        ).fetchall()
    }
    total_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "nodes_by_type": node_counts,
        "edges_by_relationship": edge_counts,
    }


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "synapse-backend", "version": "0.2.0"}
