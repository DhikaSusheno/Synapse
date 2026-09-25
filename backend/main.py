"""
main.py — Synapse MCP Server
BE-2 Masrendra: Cortex endpoints + SSE stream
BE-1 DhikaSusheno: Guardian endpoints (propose_operation, execute_operation, approvals)

Jalankan: uvicorn main:app --reload
"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import init_db
import cortex

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
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "synapse-backend"}
