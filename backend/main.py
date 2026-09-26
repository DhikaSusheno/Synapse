"""
main.py — Synapse MCP Server
BE-2 Masrendra: Cortex endpoints + SSE stream + fitur unik
BE-1 DhikaSusheno: Guardian endpoints (propose_operation, execute_operation, approvals)

Jalankan: uvicorn main:app --reload
Docs    : http://localhost:8000/docs

Fitur unik BE-2 (Masrendra):
  GET  /repo_health          — skor kesehatan repo: dead code, coverage, complexity
  GET  /complexity_report    — ranking fungsi paling kompleks
  POST /find_path            — jalur terpendek antar dua entitas di graph
  POST /suggest_refactor     — saran refactor berbasis graph connectivity
"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import init_db
import cortex
import guardian

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Synapse Backend",
    description="Reversible, conflict-aware understanding layer for AI coding agents",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    print("[Synapse] Server ready. Visit http://localhost:8000/docs")


# ---------------------------------------------------------------------------
# Request schemas
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


# ---------------------------------------------------------------------------
# CORTEX endpoints (BE-2 — Masrendra)
# ---------------------------------------------------------------------------

@app.post("/understand_repo", tags=["Cortex"])
def understand_repo(req: UnderstandRepoRequest):
    """
    Ingest sebuah repo ke SQLite graph.
    - Parse AST via tree-sitter (file, fungsi, kelas, import)
    - Baca file doc (README, .md, .txt) → edge DOCUMENTS ke kode
    - Emit SSE 'graph_update' dengan semua node baru
    """
    result = cortex.understand_repo(req.repo_path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/explain_topic", tags=["Cortex"])
def explain_topic(req: ExplainTopicRequest):
    """
    Jawab pertanyaan tentang suatu topik/modul dari knowledge graph.
    Return: definition → mental_model → example (snippet kode), related_nodes.
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
    Verdict: pass | needs_work | block.
    """
    result = cortex.review_artifact(req.path_or_diff)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# FITUR UNIK BE-2 endpoints
# ---------------------------------------------------------------------------

@app.get("/repo_health", tags=["Cortex - Unik"])
def repo_health():
    """
    📊 Laporan kesehatan repo berbasis graph.
    - Health score 0-100
    - Coverage dokumentasi (% file yang punya dokumentasi)
    - Dead code candidates (simbol tanpa caller)
    - Fungsi dengan complexity tinggi
    - Hub nodes (entitas paling banyak terhubung)
    - Isolated nodes (entitas tidak terhubung ke siapapun)
    """
    return cortex.repo_health()


@app.get("/complexity_report", tags=["Cortex - Unik"])
def complexity_report(top_n: int = Query(default=10, ge=1, le=50)):
    """
    📈 Ranking fungsi/kelas paling kompleks di repo.
    Berguna untuk menentukan prioritas refactor.
    Risk level: low | medium | high | critical
    """
    return cortex.complexity_report(top_n=top_n)


@app.post("/find_path", tags=["Cortex - Unik"])
def find_path(req: FindPathRequest):
    """
    🔍 Cari jalur terpendek antara dua entitas di knowledge graph.
    Menjawab: "Bagaimana modul A mempengaruhi modul B?"
    Contoh: from_node="main", to_node="database"
    """
    result = cortex.find_path(req.from_node, req.to_node)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/suggest_refactor", tags=["Cortex - Unik"])
def suggest_refactor(req: SuggestRefactorRequest):
    """
    🔧 Saran refactor berbasis graph untuk sebuah entitas.
    Analisis: complexity, God Object, dead code, missing docs.
    """
    result = cortex.suggest_refactor(req.node_name)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# SSE stream endpoint (BE-2 — dikonsumsi frontend live)
# ---------------------------------------------------------------------------

@app.get("/stream", tags=["SSE"])
async def stream_events():
    """
    Server-Sent Events stream.
    Frontend subscribe ke endpoint ini untuk menerima update real-time:
      - graph_update  : node/edge baru ditambahkan ke graph
      - operation_*   : state transition operasi (Guardian)
      - review_done   : hasil review artifact
    Format: text/event-stream, setiap event: 'data: <json>\\n\\n'
    """
    q = cortex.subscribe_sse()

    async def event_generator() -> AsyncGenerator[str, None]:
        # Kirim ping awal agar koneksi tidak langsung ditutup browser
        yield "data: {\"event\": \"connected\", \"data\": {}}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat agar koneksi tetap hidup
                    yield "data: {\"event\": \"heartbeat\", \"data\": {}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            cortex.unsubscribe_sse(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Graph query endpoints (helper untuk frontend)
# ---------------------------------------------------------------------------

@app.get("/graph/nodes", tags=["Graph"])
def get_all_nodes(type: str = None):
    """Ambil semua node dari graph. Filter by type opsional."""
    import sqlite3
    from database import DB_PATH
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
    import sqlite3
    from database import DB_PATH
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
    """Ringkasan graph: jumlah node per type, jumlah edge per relationship."""
    import sqlite3
    from database import DB_PATH
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
# GUARDIAN endpoints (BE-1 — DhikaSusheno, integrated by Masrendra)
# ---------------------------------------------------------------------------

class ProposeOperationRequest(BaseModel):
    tool_name: str
    params: dict = {}
    target: str


class ApproveOperationRequest(BaseModel):
    decision: str  # 'approved' | 'denied'
    note: str = ""


@app.post("/propose_operation", tags=["Guardian"])
def propose_operation(req: ProposeOperationRequest):
    """
    🛡️ Guardian Step 1: Klasifikasi risiko + conflict check + rencana rollback.
    - blast_radius: low | medium | high | unknown
    - Conflict detection: cek operasi lain di target yang sama (window 10 menit)
    - Snapshot otomatis sebelum eksekusi
    - Return: operation_id, requires_approval, conflicts, plan
    """
    return guardian.propose_operation(req.tool_name, req.params, req.target)


@app.post("/execute_operation/{operation_id}", tags=["Guardian"])
def execute_operation(operation_id: str):
    """
    🛡️ Guardian Step 2: Eksekusi operasi yang sudah disetujui.
    - Auto-rollback jika eksekusi atau verifikasi gagal
    - Emit SSE di setiap state transition
    - Status: executing → verified | rolled_back | failed
    """
    result = guardian.execute_operation(operation_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/pending_approvals", tags=["Guardian"])
def list_pending_approvals():
    """🛡️ Daftar operasi yang menunggu approval manusia."""
    return guardian.list_pending_approvals()


@app.post("/approve_operation/{operation_id}", tags=["Guardian"])
def approve_operation(operation_id: str, req: ApproveOperationRequest):
    """
    🛡️ Approve atau deny sebuah operasi.
    decision: 'approved' | 'denied'
    """
    result = guardian.approve_operation(operation_id, req.decision, req.note)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "synapse-backend"}
