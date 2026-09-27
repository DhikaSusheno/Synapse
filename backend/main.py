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
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import sqlite3

from database import init_db, DB_PATH
from database import BUSY_TIMEOUT_MS
import storage
import engine
import cortex
import guardian
import auth
import settings as settings_store


def _enable_wal(conn: sqlite3.Connection) -> None:
    """
    Set journal_mode=WAL kalau belum, dan telenkan "database is locked".

    PRAGMA journal_mode=WAL butuh lock eksklusif sesaat, dan lock eksklusif
    tidak dihormati busy_timeout - SQLite mengembalikan SQLITE_BUSY seketika.
    Mode WAL sendiri persisten di dalam file DB, jadi setelah pertama kali
    berhasil, pemanggilan berikutnya hanya membaca "wal" dan tidak butuh lock
    eksklusif. Kegagalan yang tersisa cuma pada koneksi pertama ke file baru
    ketika ada writer lain yang sedang aktif; DB tetap benar, hanya tanpa
    concurrent read yang menjadi keunggulan WAL.
    """
    try:
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass


def _db_conn(path=None, **kwargs) -> sqlite3.Connection:
    """
    sqlite3.connect() dengan busy_timeout + WAL + foreign_keys aktif.

    Semua koneksi DB v1 di main.py lewat sini. Alasannya konkret: default
    sqlite3 punya busy_timeout=0, jadi begitu ada writer lain yang sedang
    commit, koneksi ini langsung melempar "database is locked". Di path ingest
    dan approve-operation itu berarti request gagal padahal DB-nya sehat -
    dan karena itu sering muncul sebagai "bug acak" yang sulit direproduksi.

    Sengaja membaca DB_PATH global modul INI, bukan database.DB_PATH, karena
    test meng-override main.DB_PATH (backend/tests/test_issue_regressions.py).
    Kalau memanggil database.connect(), override itu tidak ikut terbaca dan
    test ikut gagal. kwargs diteruskan ke sqlite3.connect.

    PRAGMA foreign_keys=ON tidak disetel di sini: main.py membuka DB ini hanya
    untuk SELECT pada helper _load_provider_row, jadi tidak ada INSERT yang
    bisa melanggar FK, dan PRAGMA yang tak terpakai hanya menambah pekerjaan
    di setiap koneksi.
    """
    conn = sqlite3.connect(
        str(path if path is not None else DB_PATH),
        timeout=BUSY_TIMEOUT_MS / 1000.0,
        **kwargs,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    _enable_wal(conn)
    return conn


# ---------------------------------------------------------------------------
# Batas ukuran ingest
# ---------------------------------------------------------------------------
# Endpoint /api/rag/ingest membaca file dari disk dan meneruskannya ke provider
# LLM. Tanpa plafon, satu request bisa menarik file sebesar pun ke memory dan
# membakar kuota token. 2 MiB jauh di atas file sumber kode normal.
MAX_INGEST_FILE_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Migrasi dari decorator startup event yang sudah deprecated di FastAPI 0.109+.

    Perilaku-nya sama persis: init_db() legacy, init_db() v2, set event loop
    reference untuk _emit() yang thread-safe. Bedanya, lifespan di-charge
    sebelum aplikasi mulai melayani request, jadi tidak ada jendela di mana
    tabel v2 belum ada tapi endpoint sudah dipanggil.
    """
    init_db()
    # Skema v2 (storage.py) -> file TERPISA synapse_v2.db, bukan synapse.db.
    # Tetap di-init di startup supaya tabel entities/relations/actions/decisions/
    # audit_log selalu ada; kalau tidak, pemakai pertama akan kena
    # "no such table: entities" saat runtime.
    storage.init_db()
    # BUG-08 FIX: set event loop reference di cortex agar _emit() thread-safe
    # (Guardian endpoint adalah sync, dipanggil dari threadpool — perlu call_soon_threadsafe
    # BUG-E FIX: get_running_loop() adalah cara yang benar dalam async context (Python 3.7+)
    # get_event_loop() deprecated di Python 3.10+ dan error di Python 3.12+
    import asyncio
    cortex.set_event_loop(asyncio.get_running_loop())
    print("[Synapse] Server ready. Visit http://localhost:8000/docs")
    yield


app = FastAPI(
    title="Synapse Backend",
    description="Reversible, conflict-aware understanding layer for AI coding agents",
    version="0.2.0",
    lifespan=lifespan,
)

# BUG-11 FIX: CORS tidak lagi memakai wildcard origin.
# Wildcard membuat halaman web mana pun bisa membaca respons API kita
# dan mengirim request bertoken. Origin sekarang
# dibatasi ke daftar eksplisit; set lewat env SYNAPSE_ALLOWED_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=auth.allowed_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", auth.TOKEN_HEADER, "Authorization"],
    allow_credentials=False,
    max_age=600,
)

# BUG-11 FIX: gerbang token untuk semua route yang butuh proteksi.
# Exempt: /health, /docs, /redoc, /openapi.json (publik) dan preflight OPTIONS
# (preflight memang tidak boleh membawa header kustom).
@app.middleware("http")
async def enforce_api_token(request: Request, call_next):
    if request.method == "OPTIONS" or auth.is_public_path(request.url.path):
        return await call_next(request)
    token = auth._extract_token(request)
    if not auth.verify_token(token):
        return JSONResponse(
            status_code=401,
            content={
                "detail": (
                    "Token API hilang atau tidak valid. Kirim header "
                    f"'{auth.TOKEN_HEADER}: <token>' atau "
                    "'Authorization: Bearer <token>'."
                )
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


# Handler startup sudah dipindah ke lifespan() di atas.


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
# SETTINGS — persistensi platform + browse workspace
# ---------------------------------------------------------------------------

class SettingsPatch(BaseModel):
    platform_name: Optional[str] = None
    environment: Optional[str] = None
    log_level: Optional[str] = None
    dev_mode: Optional[bool] = None
    workspace_path: Optional[str] = None
    default_branch: Optional[str] = None
    auto_migrate: Optional[bool] = None
    conflict_detect: Optional[bool] = None
    sse_enabled: Optional[bool] = None
    approval_mode: Optional[str] = None
    conflict_auto_deny: Optional[bool] = None


@app.get("/settings", tags=["Settings"])
def get_settings():
    return {
        "settings": settings_store.load(),
        "defaults": settings_store.DEFAULTS,
        "storage": _storage_overview(),
    }


@app.post("/settings", tags=["Settings"])
def update_settings(patch: SettingsPatch):
    payload = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=400, detail="Tidak ada perubahan untuk disimpan")
    # workspace_path jangan jadi pintu keluar dari proteksi path: kalau
    # nilainya diterima, allowed_roots() ikut melebar dan seluruh isi
    # filesystem jadi bisa dibaca. Jadi tolak eksplisit, jangan diam-diam
    # mengabaikan -- jawaban "ditolak" jauh lebih berguna daripada diam,
    # dan penolakannya eksplisit seperti guard #63/#66.
    workspace = payload.get("workspace_path")
    if workspace is not None:
        candidate = (
            workspace if os.path.isabs(workspace)
            else os.path.join(settings_store.REPO_ROOT, workspace)
        )
        try:
            resolved = os.path.realpath(os.path.expanduser(candidate))
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="workspace_path tidak valid")
        trusted = [settings_store.REPO_ROOT] + settings_store.extra_workspace_roots()
        if not any(
            resolved == root or resolved.startswith(root + os.sep)
            for root in trusted
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "workspace_path di luar repo dan di luar "
                    "SYNAPSE_EXTRA_WORKSPACE_ROOTS, jadi tidak disimpan. "
                    "Backend hanya boleh membaca path di dalam repo. Kalau "
                    "memang butuh workspace lain, tambahkan path-nya ke env "
                    "SYNAPSE_EXTRA_WORKSPACE_ROOTS saat deployment."
                ),
            )
    return {
        "ok": True,
        "settings": settings_store.save(payload),
        "storage": _storage_overview(),
    }


@app.post("/settings/reset", tags=["Settings"])
def reset_settings():
    return {
        "ok": True,
        "settings": settings_store.reset(),
        "storage": _storage_overview(),
    }


@app.get("/browse", tags=["Settings"])
def browse(path: str = Query("", description="Path relatif terhadap repo root")):
    try:
        return settings_store.browse(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _storage_overview() -> dict:
    tables: Dict[str, List[str]] = {}
    files: List[dict] = []
    for name, path in (("legacy", DB_PATH), ("v2", getattr(storage, "DB_PATH", None))):
        if not path or not os.path.exists(path):
            continue
        files.append(
            {
                "label": name,
                "file": os.path.basename(path),
                "size_bytes": os.path.getsize(path),
            }
        )
        try:
            conn = _db_conn(path)
            tables[name] = sorted(
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            )
            conn.close()
        except sqlite3.Error:
            tables[name] = []
    return {"files": files, "tables": tables}


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
# Endpoint dengan nama engine.py yang baru
# ---------------------------------------------------------------------------
# Alias dari ketujuh endpoint di atas. Endpoint lama (/understand_repo,
# /explain_topic, ...) sengaja dibiarkan karena frontend memakai nama itu;
# endpoint baru supaya kode baru tidak perlu lewat path "/understand_repo".

@app.post("/ingest_repository", tags=["Engine"], include_in_schema=False)
def ingest_repository(req: UnderstandRepoRequest):
    result = engine.ingest_repository(req.repo_path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/ask_about", tags=["Engine"], include_in_schema=False)
def ask_about(req: ExplainTopicRequest):
    result = engine.ask_about(req.topic)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@app.post("/review_change", tags=["Engine"], include_in_schema=False)
def review_change(req: ReviewArtifactRequest):
    result = engine.review_change(req.path_or_diff)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/health_report", tags=["Engine"], include_in_schema=False)
def health_report():
    return engine.health_report()


@app.get("/rank_complexity", tags=["Engine"], include_in_schema=False)
def rank_complexity(top_n: int = Query(default=10, ge=1, le=50)):
    return engine.rank_complexity(top_n=top_n)


@app.post("/trace_connection", tags=["Engine"], include_in_schema=False)
def trace_connection(req: FindPathRequest):
    result = engine.trace_connection(req.from_node, req.to_node)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/propose_refactor", tags=["Engine"], include_in_schema=False)
def propose_refactor(req: SuggestRefactorRequest):
    result = engine.propose_refactor(req.node_name)
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
    status: Optional[Literal[
        "pending", "approved", "executing", "executed_unverified",
        "verified", "failed", "rolled_back", "denied",
    ]] = None,
    limit: int = Query(default=20, ge=1, le=100)
):
    """
    📋 Riwayat semua operasi. Filter by status opsional.
    Status: pending | approved | executing | executed_unverified |
            verified | failed | rolled_back | denied

    ISSUE-35 FIX: `status` sekarang Literal, bukan `str` bebas. Sebelumnya
    `?status=pendng` (typo) atau `?status=anything` dijawab `200 []` tanpa
    feedback apa pun, sehingga developer tidak tahu filter-nya tidak
    berlaku dan tidak bisa bedakan "filter tidak cocok" dari "salah ketik".

    Dengan Literal, FastAPI mengembalikan 422 + daftar nilai yang diizinkan,
    dan enum-nya ikut muncul di OpenAPI docs.
    """
    conn = _db_conn(DB_PATH)
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
# Timeout panggilan GitHub
# ---------------------------------------------------------------------------
# Semua endpoint GitHub pakai requests (sinkron) dan berjalan sebagai `def`,
# jadi dieksekusi di threadpool anyio. Tanpa timeout, satu koneksi yang
# di-blackhole (proxy kantor, DNS menggantung, insiden GitHub) menahan thread
# selamanya. Default anyio cuma 40 thread, jadi 40 request seperti itu sudah
#enough untuk membuat seluruh backend tidak merespons - termasuk /health.
#
# Dipisah connect/read karena OAuth token exchange boleh lebih lambat dari
# GET biasa.
GITHUB_TIMEOUT = (10, 30)   # (connect, read) dalam detik


# ---------------------------------------------------------------------------
# Graph query — helper untuk frontend
# ---------------------------------------------------------------------------

@app.get("/graph/nodes", tags=["Graph"])
def get_all_nodes(type: str = None, kind: str = None):
    """
    Semua entitas graph, dalam bentuk yang dikonsumsi frontend.

    Sumbernya storage.py (entities/relations di synapse_v2.db), bukan tabel
    legacy nodes. Mapping ke bentuk frontend dilakukan di engine:
      entities.kind         -> type
      entities.label        -> name
      entities.attributes_json -> meta

    Parameter `type` (nama lama) tetap diterima sebagai alias `kind` supaya
    tidak ada caller yang ikut pecah.
    """
    return engine.get_graph_snapshot(kind=kind or type)


@app.get("/graph/edges", tags=["Graph"])
def get_all_edges(relationship: str = None, relation_type: str = None):
    """
    Semua sisi graph, dalam bentuk frontend: source/target/relationship.

    Mapping: relations.from_id -> source, relations.to_id -> target,
    relations.relation_type -> relationship, relations.weight -> confidence.
    """
    return engine.get_graph_edges(relationship=relationship or relation_type)


@app.get("/graph/summary", tags=["Graph"])
def get_graph_summary():
    """Ringkasan graph: jumlah entitas per kind dan sisi per relasi."""
    stats = engine.graph_stats()
    return {
        "total_nodes": stats["node_count"],
        "total_edges": stats["edge_count"],
        "nodes_by_type": stats["nodes_by_kind"],
        "nodes_by_kind": stats["nodes_by_kind"],
        "edges_by_relationship": stats["edges_by_relationship"],
        "db_path": stats["db_path"],
    }


# ---------------------------------------------------------------------------
# GitHub Integration
# ---------------------------------------------------------------------------

class GitHubOAuthStartRequest(BaseModel):
    redirect_uri: str = "http://localhost:3000/auth/github/callback"

class GitHubPATRequest(BaseModel):
    pat: str
    scopes: list[str] = ["repo", "read:org", "read:user"]

@app.get("/api/github/auth/url", tags=["GitHub"])
def github_oauth_url(redirect_uri: str = "http://localhost:3000/auth/github/callback"):
    """Get GitHub OAuth authorization URL."""
    import os
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="GITHUB_CLIENT_ID not configured")
    scope = "repo read:org read:user"
    url = f"https://github.com/login/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope={scope}&state=synapse"
    return {"url": url, "state": "synapse"}

@app.get("/api/github/callback", tags=["GitHub"])
def github_callback(code: str, state: str = "", redirect_uri: str = "http://localhost:3000/auth/github/callback"):
    """Handle GitHub OAuth callback, exchange code for access token."""
    import os
    import requests
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    
    # Exchange code for token
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {resp.text}")
    
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token in response")
    
    # Get user info
    user_resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")
    
    user = user_resp.json()
    
    # Store connection
    import sqlite3
    from datetime import datetime
    from auth import encrypt_token
    conn = _db_conn(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO github_connections 
           (id, type, access_token, scope, user_login, user_avatar, updated_at)
           VALUES (?, 'oauth', ?, ?, ?, ?, ?)""",
        (f"oauth:{user['login']}", encrypt_token(access_token), "repo,read:org,read:user", 
         user["login"], user.get("avatar_url", ""), guardian._utcnow_iso())
    )
    conn.commit()
    conn.close()
    
    return {"ok": True, "user": {"login": user["login"], "avatar": user.get("avatar_url", "")}, "redirect": "http://localhost:3000/settings?tab=github"}

@app.post("/api/github/auth/pat", tags=["GitHub"])
def github_pat(req: GitHubPATRequest):
    """Validate and store GitHub Personal Access Token."""
    import requests
    import sqlite3
    from datetime import datetime
    from auth import encrypt_token
    
    # Token ditaruh di header Authorization. Karakter non-ASCII atau newline
    # membuat requests melempar UnicodeEncodeError / InvalidHeader yang tidak
    # tertangkap -> 500. GitHub token selalu ASCII, jadi tolak lebih dulu
    # dengan 400 yang jelas. Lihat _validate_header_token().
    _validate_header_token(req.pat, "pat")
    
    # Validate token
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {req.pat}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid PAT")
    
    user = resp.json()
    scopes = req.scopes
    
    conn = _db_conn(DB_PATH)
    from auth import encrypt_token
    conn.execute(
        """INSERT OR REPLACE INTO github_connections 
           (id, type, access_token, scope, user_login, user_avatar, updated_at)
           VALUES (?, 'pat', ?, ?, ?, ?, ?)""",
        (f"pat:{user['login']}", encrypt_token(req.pat), ",".join(scopes), 
         user["login"], user.get("avatar_url", ""), guardian._utcnow_iso())
    )
    conn.commit()
    conn.close()
    
    return {"ok": True, "user": {"login": user["login"], "avatar": user.get("avatar_url", "")}}

@app.get("/api/github/user", tags=["GitHub"])
def github_user():
    """Get current authenticated GitHub user."""
    import sqlite3
    from auth import decrypt_token
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "connected": False}
    token = decrypt_token(row["access_token"])
    import requests
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        return {"ok": False, "connected": False, "error": "Token expired or invalid"}
    return {"ok": True, "connected": True, "user": resp.json(), "type": row["type"]}

@app.get("/api/github/repos", tags=["GitHub"])
def github_repos(per_page: int = 100, page: int = 1):
    """List repositories accessible by the authenticated user."""
    import sqlite3
    from auth import decrypt_token
    import requests
    
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="No GitHub connection")
    
    token = decrypt_token(row["access_token"])
    import requests
    resp = requests.get(
        f"https://api.github.com/user/repos?per_page={per_page}&page={page}&sort=updated",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Failed to fetch repos")
    return {"ok": True, "repos": resp.json()}

@app.get("/api/github/repos/{owner}/{repo}/tree", tags=["GitHub"])
def github_repo_tree(owner: str, repo: str, branch: str = "main", recursive: bool = True):
    """Get repository file tree."""
    import sqlite3
    from auth import decrypt_token
    import requests
    
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="No GitHub connection")
    
    token = decrypt_token(row["access_token"])
    import requests
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive={1 if recursive else 0}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch tree: {resp.text}")
    return resp.json()

@app.get("/api/github/repos/{owner}/{repo}/contents", tags=["GitHub"])
def github_file_content(owner: str, repo: str, path: str, branch: str = "main"):
    """Get file content from repository."""
    import sqlite3
    from auth import decrypt_token
    import requests
    
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="No GitHub connection")
    
    token = decrypt_token(row["access_token"])
    import requests
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=GITHUB_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch file: {resp.text}")
    return resp.json()


# ---------------------------------------------------------------------------
# LLM Provider Registry
# ---------------------------------------------------------------------------

# Host endpoint cloud-metadata. Menunjuk base_url LLM ke sini tidak pernah
# sah, dan ini target SSRF paling umum (kredensial instance bocor keluar).
_BLOCKED_LLM_HOSTS = frozenset({
    "169.254.169.254",      # AWS / Azure / GCP / OpenStack IMDS
    "metadata.google.internal",
    "metadata.goog",
    "100.100.100.200",      # Alibaba Cloud
    "fd00:ec2::254",        # AWS IMDSv6
})

# Panjang wajar untuk base_url. Cukup untuk URL provider, terlalu panjang
# hampir pasti input jahat atau tidak sengaja.
_MAX_BASE_URL_LEN = 2048


def _validate_llm_base_url(base_url: str | None) -> str | None:
    """
    Validasi base_url milik LLM provider sebelum disimpan maupun sebelum dipakai.

    Kenapa perlu: base_url diisi user, lalu dipakai server untuk melakukan
    request HTTP keluar sambil menempelkan API key yang sudah didekripsi di
    header Authorization. Tanpa validasi, siapa pun yang bisa memanggil
    /api/llm/providers bisa membuat server menembak jaringan internal
    (SSRF) sekaligus mengirim key itu ke host yang dia pilih, karena respons
    internal juga dikembalikan ke pemanggil.

    Yang DICEGAH di sini (tanpa merusak use case sah):
      - skema selain http/https (file://, gopher://, ...)
      - URL tanpa host
      - userinfo di URL (http://evil@host) yang dipakai menipu pembaca
      - karakter kontrol/spasi di URL, yang membuat header HTTP rusak
      - host cloud-metadata

    Yang SENGAJA TIDAK dicegah: alamat privat seperti localhost atau
    127.0.0.1. Ollama (http://localhost:11434) dan server OpenAI-compatible
    self-hosted (vLLM, LM Studio, LiteLLM) adalah use case normal untuk
    aplikasi ini. Memblokirnya akan merusak fitur, bukan menutup risiko.
    """
    if base_url is None:
        return None
    if not isinstance(base_url, str):
        raise HTTPException(status_code=400, detail="base_url must be a string")
    # URL kosong ekuivalen "pakai default endpoint provider".
    if not base_url.strip():
        return None
    if len(base_url) > _MAX_BASE_URL_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"base_url too long (max {_MAX_BASE_URL_LEN} characters)",
        )
    # Karakter kontrol membuat httpx/requests gagal saat menulis header, dan
    # bisa dipakai menyisipkan header baru.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch.isspace() for ch in base_url):
        raise HTTPException(
            status_code=400,
            detail="base_url must not contain whitespace or control characters",
        )

    from urllib.parse import urlsplit

    try:
        parts = urlsplit(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base_url: {exc}")

    if parts.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="base_url must use http or https",
        )
    if not parts.hostname:
        raise HTTPException(status_code=400, detail="base_url must include a host")
    if parts.username or parts.password:
        raise HTTPException(
            status_code=400,
            detail="base_url must not embed credentials",
        )
    if parts.hostname.lower() in _BLOCKED_LLM_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="base_url host is not allowed",
        )
    return base_url


def _validate_header_token(value: str, field: str) -> str:
    """
    Pastikan nilai yang akan ditaruh di HTTP header hanya berisi karakter yang
    benar-benar bisa di-encode sebagai header.

    requests/httpx mengubah header ke Latin-1. Kalau input user memuat
    karakter di luar itu, atau newline/CR, pemanggilannya melempar
    UnicodeEncodeError / InvalidHeader yang tidak tertangkap -> HTTP 500
    "Internal Server Error" untuk input yang sebenarnya cuma salah. GitHub
    token selalu ASCII, jadi menolak non-ASCII tidak merusak apa pun.
    """
    for ch in value:
        code = ord(ch)
        if code < 0x21 or code > 0x7E:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{field} contains characters that cannot be sent in an "
                    "HTTP header; use printable ASCII only"
                ),
            )
    if len(value) > 4096:
        raise HTTPException(
            status_code=400, detail=f"{field} is too long (max 4096 characters)"
        )
    return value


class LLMProviderCreate(BaseModel):
    name: str
    type: Literal["openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama", "openai-compatible"]
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] = []
    default_model: str = ""
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_vision: bool = False
    enabled: bool = True

class LLMProviderUpdate(BaseModel):
    name: str | None = None
    type: Literal["openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama", "openai-compatible"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    default_model: str | None = None
    max_tokens: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    enabled: bool | None = None

@app.get("/api/llm/providers", tags=["LLM"])
def list_llm_providers():
    """List all configured LLM providers."""
    import sqlite3
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, type, base_url, models, default_model, max_tokens, supports_tools, supports_vision, enabled, created_at, updated_at FROM llm_providers ORDER BY created_at"
    ).fetchall()
    conn.close()
    providers = []
    for row in rows:
        import json
        providers.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "base_url": row["base_url"],
            "models": json.loads(row["models"]) if row["models"] else [],
            "default_model": row["default_model"],
            "max_tokens": row["max_tokens"],
            "supports_tools": bool(row["supports_tools"]),
            "supports_vision": bool(row["supports_vision"]),
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return {"ok": True, "providers": providers}

@app.post("/api/llm/providers", tags=["LLM"])
def create_llm_provider(req: LLMProviderCreate):
    """Create a new LLM provider configuration."""
    import sqlite3
    import json
    from auth import encrypt_token
    from datetime import datetime
    
    # Validasi SEBELUM menyentuh DB: URL yang tidak sah jangan sampai tersimpan.
    _validate_llm_base_url(req.base_url)
    
    conn = _db_conn(DB_PATH)
    provider_id = f"{req.type}:{req.name}"
    try:
        conn.execute(
            """INSERT INTO llm_providers 
               (id, name, type, base_url, api_key, models, default_model, max_tokens, 
                supports_tools, supports_vision, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provider_id, req.name, req.type, req.base_url,
                encrypt_token(req.api_key) if req.api_key else None,
                json.dumps(req.models), req.default_model or req.models[0] if req.models else "",
                req.max_tokens, int(req.supports_tools), int(req.supports_vision),
                int(req.enabled), guardian._utcnow_iso(), guardian._utcnow_iso()
            )
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Provider already exists")
    finally:
        conn.close()
    return {"ok": True, "id": provider_id}

@app.patch("/api/llm/providers/{provider_id}", tags=["LLM"])
def update_llm_provider(provider_id: str, req: LLMProviderUpdate):
    """Update an LLM provider configuration."""
    import sqlite3
    import json
    from auth import encrypt_token
    from datetime import datetime
    
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Provider not found")
    
    updates = []
    params = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.type is not None:
        updates.append("type = ?")
        params.append(req.type)
    if req.base_url is not None:
        _validate_llm_base_url(req.base_url)
        updates.append("base_url = ?")
        params.append(req.base_url)
    if req.api_key is not None:
        updates.append("api_key = ?")
        params.append(encrypt_token(req.api_key))
    if req.models is not None:
        updates.append("models = ?")
        params.append(json.dumps(req.models))
    if req.default_model is not None:
        updates.append("default_model = ?")
        params.append(req.default_model)
    if req.max_tokens is not None:
        updates.append("max_tokens = ?")
        params.append(req.max_tokens)
    if req.supports_tools is not None:
        updates.append("supports_tools = ?")
        params.append(int(req.supports_tools))
    if req.supports_vision is not None:
        updates.append("supports_vision = ?")
        params.append(int(req.supports_vision))
    if req.enabled is not None:
        updates.append("enabled = ?")
        params.append(int(req.enabled))
    
    if updates:
        updates.append("updated_at = ?")
        params.append(guardian._utcnow_iso())
        params.append(provider_id)
        conn.execute(f"UPDATE llm_providers SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    
    conn.close()
    return {"ok": True, "id": provider_id}

@app.delete("/api/llm/providers/{provider_id}", tags=["LLM"])
def delete_llm_provider(provider_id: str):
    """Delete a custom LLM provider (built-in providers cannot be deleted)."""
    import sqlite3
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Provider not found")
    # Allow deletion of custom providers only
    if existing["type"] in ["openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Cannot delete built-in provider")
    conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": provider_id}

@app.get("/api/llm/providers/{provider_id}/models", tags=["LLM"])
def list_provider_models(provider_id: str):
    """List available models for a provider."""
    import sqlite3
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT models, default_model FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    import json
    models = json.loads(row["models"]) if row["models"] else []
    return {"ok": True, "provider_id": provider_id, "models": models, "default": row["default_model"]}


# ---------------------------------------------------------------------------
# LLM Chat & Tools
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None

class ChatCompletionRequest(BaseModel):
    provider_id: str
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = 4096
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | None = None


def _load_provider_row(provider_id: str):
    """
    Baca satu baris llm_providers. Sengaja sinkron, SELALU dipanggil lewat
    asyncio.to_thread() dari dalam async def.

    Kenapa harus di-thread: sqlite3 itu blocking. dipanggil langsung di dalam
    `async def`, dia membekukan event loop FastAPI, dan karena hanya ada satu
    thread event loop, /health ikut mati. Terukur: 500 baris sqlite = 2,7 detik
    freeze, 2.000 baris = 11,3 detik, sementara /health yang tidak menyentuh
    SQLite sama sekali tidak responsif.
    """
    import sqlite3

    conn = _db_conn(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM llm_providers WHERE id = ? AND enabled = 1", (provider_id,)
        ).fetchone()
    finally:
        conn.close()


@app.post("/api/llm/chat", tags=["LLM"])
async def llm_chat(req: ChatCompletionRequest):
    """Chat completion with LLM provider."""
    import sqlite3
    import json
    import asyncio
    import httpx
    from auth import decrypt_token

    # sqlite3 = blocking -> lewat threadpool, bukan langsung di event loop.
    provider = await asyncio.to_thread(_load_provider_row, req.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")
    
    api_key = decrypt_token(provider["api_key"]) if provider["api_key"] else None
    if not api_key and provider["type"] != "ollama":
        raise HTTPException(status_code=400, detail="Provider not configured with API key")
    
    model = req.model or provider["default_model"]
    
    if provider["type"] == "ollama":
        # Ollama local
        base_url = _validate_llm_base_url(provider["base_url"]) or "http://localhost:11434"
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in req.messages],
                "stream": req.stream,
                "options": {"temperature": req.temperature, "num_predict": req.max_tokens},
            }
            if req.stream:
                async def stream_response():
                    async with client.stream("POST", f"{base_url}/api/chat", json=payload, timeout=60.0) as resp:
                        async for line in resp.aiter_lines():
                            if line:
                                yield f"data: {line}\n\n"
                return StreamingResponse(stream_response(), media_type="text/event-stream")
            else:
                resp = await client.post(f"{base_url}/api/chat", json=payload, timeout=60.0)
                return resp.json()
    else:
        # OpenAI-compatible (OpenAI, Anthropic, etc.)
        base_url = _validate_llm_base_url(provider["base_url"]) or ("https://api.openai.com/v1" if provider["type"] == "openai" else 
                      "https://api.anthropic.com/v1" if provider["type"] == "anthropic" else
                      "https://integrate.api.nvidia.com/v1" if provider["type"] == "nvidia" else
                      "https://api.deepseek.com/v1" if provider["type"] == "deepseek" else
                      "https://api.openai.com/v1")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider["type"] == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": req.stream,
        }
        if req.tools:
            payload["tools"] = req.tools
            payload["tool_choice"] = req.tool_choice or "auto"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            if req.stream:
                async def stream_response():
                    async with client.stream("POST", f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60.0) as resp:
                        async for line in resp.aiter_lines():
                            if line:
                                yield f"data: {line}\n\n"
                return StreamingResponse(stream_response(), media_type="text/event-stream")
            else:
                resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60.0)
                return resp.json()


class ExplainRequest(BaseModel):
    provider_id: str
    model: str | None = None
    topic: str
    context_limit: int = 5

class ReviewRequest(BaseModel):
    provider_id: str
    model: str | None = None
    path_or_diff: str
    context: str | None = None

class RefactorRequest(BaseModel):
    provider_id: str
    model: str | None = None
    node_name: str

@app.post("/api/llm/explain", tags=["LLM"])
async def llm_explain(req: ExplainRequest):
    """Explain a topic using LLM with graph context."""
    import json
    import asyncio
    # engine.ask_about() query SQLite sinkron -> to_thread.
    context = await asyncio.to_thread(engine.ask_about, req.topic)
    if not context.get("ok"):
        return context
    system_prompt = (
        f"You are a senior software engineer explaining code from a knowledge graph.\n"
        f"Topic: {req.topic}\n"
        f"Graph Context: {json.dumps(context, indent=2)}\n"
        f"Provide: definition -> mental model -> example -> complexity note -> how to use -> related nodes"
    )
    # BUG-NEW-6 FIX: tidak boleh `from main import llm_chat` (circular import).
    # Panggil langsung — kita sudah berada di dalam module main.
    return await llm_chat(ChatCompletionRequest(
        provider_id=req.provider_id,
        model=req.model or "",
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"Explain: {req.topic}"),
        ],
        temperature=0.3,
        max_tokens=2048,
    ))

@app.post("/api/llm/review", tags=["LLM"])
async def llm_review(req: ReviewRequest):
    """Review artifact using LLM with graph context."""
    import json
    import asyncio
    # engine.review_change() baca file + query SQLite -> to_thread.
    context = await asyncio.to_thread(engine.review_change, req.path_or_diff)
    system_prompt = (
        f"You are a senior code reviewer. Review the artifact using the knowledge graph.\n"
        f"Artifact: {req.path_or_diff}\n"
        f"Graph Context: {json.dumps(context, indent=2)}\n"
        f"Score: completeness, clarity, correctness_vs_spec, risk (0-10 each)\n"
        f"Verdict: pass | needs_work | block"
    )
    return await llm_chat(ChatCompletionRequest(
        provider_id=req.provider_id,
        model=req.model or "",
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content="Review this artifact"),
        ],
        temperature=0.2,
        max_tokens=2048,
    ))

@app.post("/api/llm/refactor", tags=["LLM"])
async def llm_refactor(req: RefactorRequest):
    """Suggest refactor using LLM with graph context."""
    import json
    import asyncio
    # engine.propose_refactor() query SQLite sinkron -> to_thread.
    context = await asyncio.to_thread(engine.propose_refactor, req.node_name)
    if not context.get("ok"):
        return context
    system_prompt = (
        f"You are a senior architect. Suggest refactors for this entity.\n"
        f"Node: {req.node_name}\n"
        f"Graph Context: {json.dumps(context, indent=2)}\n"
        f"Provide: type (split_file_or_function/god_object/extract_method/etc), priority, message, example"
    )
    return await llm_chat(ChatCompletionRequest(
        provider_id=req.provider_id,
        model=req.model or "",
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"Suggest refactors for {req.node_name}"),
        ],
        temperature=0.3,
        max_tokens=2048,
    ))


# ---------------------------------------------------------------------------
# Project LLM Config
# ---------------------------------------------------------------------------

class ProjectLLMConfigRequest(BaseModel):
    project_id: str
    provider_id: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 4096
    system_prompt: str | None = None
    rag_enabled: bool = True
    rag_top_k: int = 5

@app.get("/api/projects/{project_id}/llm-config", tags=["LLM"])
def get_project_llm_config(project_id: str):
    """Get LLM configuration for a project."""
    import sqlite3
    conn = _db_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM project_llm_configs WHERE project_id = ?", (project_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"ok": True, "config": None}
    return {"ok": True, "config": dict(row)}

@app.put("/api/projects/{project_id}/llm-config", tags=["LLM"])
def upsert_project_llm_config(project_id: str, req: ProjectLLMConfigRequest):
    """Create or update LLM configuration for a project."""
    import sqlite3
    import json
    from datetime import datetime
    
    conn = _db_conn(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO project_llm_configs
           (project_id, provider_id, model, temperature, max_tokens, system_prompt, rag_enabled, rag_top_k, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            req.project_id, req.provider_id, req.model, req.temperature, req.max_tokens,
            req.system_prompt, int(req.rag_enabled), req.rag_top_k, guardian._utcnow_iso()
        )
    )
    conn.commit()
    conn.close()
    return {"ok": True, "project_id": project_id}

# ---------------------------------------------------------------------------
# RAG Endpoints
# ---------------------------------------------------------------------------

class RAGIngestRequest(BaseModel):
    provider_id: str
    model: str | None = None
    api_key: str | None = None   # BUG-NEW-4 FIX: field hilang, dipakai di baris 1288
    files: list[str]  # file paths or contents
    chunk_size: int = 1000
    chunk_overlap: int = 200

class RAGSearchRequest(BaseModel):
    provider_id: str
    model: str | None = None
    query: str
    top_k: int = 5

def _looks_like_path(value: str) -> bool:
    r"""
    Heuristik: apakah string ini diperlakukan sebagai path filesystem, atau konten literal?

    Konten inline yang dikirim frontend bisa saja satu baris pendek tanpa
    newline, jadi tidak bisa/resource diheuristik 100% akurat. Karena itu
    jalur yang ambigu TIDAK di-fallback diam-diam: kalau path-nya benar-benar
    ada tapi terlarang, endpoint tetap menolak. Lihat _resolve_ingest_entry.
    """
    return (
        len(value) < 4096
        and "\n" not in value
        and not value.lstrip().startswith(("{", "[", "<", "#", "-", "/*"))
    )


def _resolve_ingest_entry(entry: str) -> str:
    """
    Ubah satu entri RAGIngestRequest.files menjadi konten teks.

    req.files menerima dua bentuk: path filesystem ATAU konten langsung.
    Bentuk path wajib lolos settings_store.is_readable_path() sebelum dibuka,
    kalau tidak endpoint ini membaca file apa pun di mesin - termasuk .env
    yang berisi FERNET_KEY - lalu MENGIRIM isinya ke provider LLM pihak
    ketiga. Jadi ini exfiltrasi, bukan sekadar file read.

    Perilaku yang dipertahankan: entri yang jelas-jelas bukan path (multiline,
    diawali '{' atau '<' dan sejenisnya) dipakai apa adanya.
    """
    if not _looks_like_path(entry):
        return entry

    expanded = os.path.expanduser(entry)

    if not settings_store.is_readable_path(entry):
        if os.path.exists(expanded):
            # Ada di disk tapi di luar allowlist, atau file sensitif.
            # Bug lama menutupi ini dengan `except:` yang diam-diam memakai
            # string path sebagai konten, sehingga file terlarang ikut
            # ter-embed di vector store. Sekarang ditolak eksplisit.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Path tidak boleh dibaca: {entry!r}. File di luar workspace "
                    "yang diizinkan, atau file kredensial (env, private key, "
                    "database), ditolak."
                ),
            )
        # Bukan path yang ada -> perlakukan sebagai konten literal.
        return entry

    try:
        with open(expanded, "r", encoding="utf-8") as handle:
            content = handle.read(MAX_INGEST_FILE_BYTES + 1)
    except (OSError, UnicodeDecodeError) as exc:
        # Binary file dan permission error harus kelihatan, bukan jadi konten.
        raise HTTPException(
            status_code=400, detail=f"Gagal membaca {entry!r}: {exc}"
        ) from exc

    if len(content) > MAX_INGEST_FILE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File terlalu besar untuk di-ingest: {entry!r}"
        )
    return content


def _chunk_texts(texts: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Potong beberapa teks menjadi potongan overlap. SINKRON, wajib via to_thread.

    Perilaku sengaja dipertahankan persis seperti loop inline yang
    menggantikannya, termasuk `chunk_overlap // 50` yang terlihat aneh -
    mengubahnya akan mengubah batas chunk dan karena itu mengubah fingerprint
    md5 yang dipakai sebagai PRIMARY KEY rag_chunks. Itu keputusan sendiri,
    bukan bagian dari perbaikan event loop.
    """
    chunks: list[str] = []
    for content in texts:
        lines = content.split('\n')
        chunk: list[str] = []
        for line in lines:
            chunk.append(line)
            if len('\n'.join(chunk)) >= chunk_size:
                chunks.append('\n'.join(chunk))
                overlap = chunk[-chunk_overlap // 50:] if chunk_overlap else []
                chunk = overlap
        if chunk:
            chunks.append('\n'.join(chunk))
    return chunks


def _store_rag_chunks(embeddings: list[dict], provider_id: str, model: str) -> int:
    """
    Tulis embedding ke rag_chunks. SINKRON, wajib via to_thread.

    Satu transaksi untuk semua baris, bukan commit per baris. Versi lama
    melakukan conn.execute + conn.commit() di dalam loop - itu 1.000 commit
    untuk 1.000 chunk, dan masing-masing commit Blogs file lock, jadi ada
    jendela di mana writer lain Transiently gagal dengan
    "database is locked".
    """
    import hashlib
    import json
    import sqlite3

    if not embeddings:
        return 0

    conn = _db_conn(DB_PATH)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS rag_chunks (
            id TEXT PRIMARY KEY,
            chunk TEXT NOT NULL,
            embedding TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        rows = [
            (
                hashlib.md5(emb["chunk"].encode()).hexdigest(),
                emb["chunk"],
                json.dumps(emb["embedding"]),
                json.dumps({"provider": provider_id, "model": model}),
            )
            for emb in embeddings
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO rag_chunks (id, chunk, embedding, metadata, created_at)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(embeddings)


@app.post("/api/rag/ingest", tags=["RAG"])
async def rag_ingest(req: RAGIngestRequest):
    """Ingest files into RAG vector store."""
    import sqlite3
    import json
    import hashlib
    import asyncio
    import httpx
    from auth import decrypt_token

    # Validasi SELURUH entri lebih dulu, sebelum query DB, decrypt_token, atau
    # panggilan jaringan apa pun. Kalau validasi dilakukan setelahnya,
    # request berbahaya bisa lolos, atau pun tertutup 404 "Provider not found"
    # sehingga penolakan aslinya tidak pernah terlihat. _resolve_ingest_entry()
    # menyentuh disk, jadi ikut di-thread.
    resolved = await asyncio.to_thread(
        lambda: [_resolve_ingest_entry(entry) for entry in req.files]
    )

    # sqlite3 blocking -> to_thread.
    provider = await asyncio.to_thread(_load_provider_row, req.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")

    api_key = decrypt_token(req.api_key) if req.api_key else None
    model = req.model or "text-embedding-3-small"

    # Chunking murni CPU + join string, blocking -> to_thread.
    chunks = await asyncio.to_thread(_chunk_texts, resolved, req.chunk_size, req.chunk_overlap)

    # Generate embeddings
    embeddings = []
    # Decrypt sekali, bukan per chunk, dan base_url divalidasi sebelum dipakai.
    provider_key = decrypt_token(provider["api_key"]) if provider["api_key"] else None
    base_url = _validate_llm_base_url(provider["base_url"]) or "https://api.openai.com/v1"
    headers = {"Authorization": f"Bearer {provider_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"model": model, "input": chunk}
            resp = await client.post(f"{base_url}/embeddings", json=payload, headers=headers, timeout=30.0)
            if resp.status_code == 200:
                embeddings.append({"chunk": chunk, "embedding": resp.json()["data"][0]["embedding"]})
    
    # Store in DB - blocking -> to_thread. Satu transaksi, bukan commit per baris.
    written = await asyncio.to_thread(
        _store_rag_chunks, embeddings, req.provider_id, model
    )

    return {"ok": True, "chunks": written}

@app.post("/api/rag/search", tags=["RAG"])
async def rag_search(req: RAGSearchRequest):
    """Search RAG vector store for relevant chunks."""
    import sqlite3
    import json
    import numpy as np
    import asyncio
    import httpx
    from auth import decrypt_token

    # sqlite3 blocking -> to_thread.
    provider = await asyncio.to_thread(_load_provider_row, req.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")

    # Generate query embedding
    model = req.model or "text-embedding-3-small"
    api_key = decrypt_token(provider["api_key"])
    base_url = _validate_llm_base_url(provider["base_url"]) or "https://api.openai.com/v1"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": req.query},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30.0
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        query_embedding = np.array(resp.json()["data"][0]["embedding"])

    # Baca DB + hitung cosine similarity: blocking (I/O + numpy di atas SEMUA
    # baris) -> to_thread, supaya /health tetap responsif selama pencarian.
    return await asyncio.to_thread(
        _rag_search_sync, query_embedding, req.top_k
    )


def _rag_search_sync(query_embedding, top_k: int) -> dict:
    """Bagian sinkron dari rag_search. Selalu dipanggil via asyncio.to_thread."""
    import json
    import sqlite3
    import numpy as np

    conn = _db_conn(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, chunk, embedding, metadata FROM rag_chunks"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"ok": True, "results": []}

    # Compute cosine similarity
    results = []
    for row in rows:
        emb = np.array(json.loads(row["embedding"]))
        sim = np.dot(query_embedding, emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(emb))
        if sim > 0.3:  # threshold
            results.append({
                "id": row["id"],
                "chunk": row["chunk"][:500],
                "similarity": float(sim),
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return {"ok": True, "results": results[:top_k]}


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "synapse-backend", "version": "0.2.0"}
