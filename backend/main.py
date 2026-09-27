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
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
from urllib.parse import urlsplit
import sqlite3

from database import init_db, DB_PATH
import storage
import engine
import cortex
import guardian
import auth
import settings as settings_store
import projects


def _restore_active_target() -> None:
    """Terapkan target aktif dari registry ke storage + engine saat startup.

    Dipisah dari lifespan supaya bisa diuji tanpa menjalankan app. Kalau
    target aktif tidak valid (path hilang, di luar workspace), ini TIDAK
    diam-diam membuka graph target lain - storage diset ke None supaya user
    melihat "belum ada target", bukan data repository yang salah.
    """
    active = projects.ensure_active_applied()
    # Graph in-memory masih milik DB default setelah ganti target.
    engine.invalidate_graph_cache()
    if active is None:
        print("[Synapse] Tidak ada target aktif; pakai graph kosong.")
    elif not active.get("available"):
        print(
            f"[Synapse] Target aktif {active['id']!r} tidak tersedia "
            f"({active.get('path')!r}); graph dinonaktifkan."
        )
    else:
        print(f"[Synapse] Target aktif: {active['label']} ({active['path']})")

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
    # Target aktif (repository/folder yang dianalisis) disimpan di registry
    # terpisah, tapi efeknya ada di storage: file DB graph untuk target itu.
    # Dipanggil SEBELUM endpoint dilayani supaya /graph/* langsung membaca DB
    # yang benar, dan supaya DB target aktif pasti punya skema.
    _restore_active_target()
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

# ---------------------------------------------------------------------------
# Targets: repository / folder yang dianalisis
# ---------------------------------------------------------------------------

class TargetCreateRequest(BaseModel):
    kind: Literal["local", "github"] = "local"
    label: str
    path: str
    source: str | None = None
    branch: str | None = None
    make_active: bool = True
    ingest: bool = True

class TargetUpdateRequest(BaseModel):
    label: str | None = None
    branch: str | None = None

class IngestRequest(BaseModel):
    """Opsi ingest. Default-nya `true` supaya satu klik langsung berguna."""
    ingest: bool = True


def _target_payload(target: dict | None) -> dict:
    """Satu bentuk respons untuk semua endpoint target.

    `db_path` sengaja TIDAK ikut: path absolut server tidak berguna di
    browser dan hanya membocorkan struktur filesystem.
    """
    if target is None:
        return {"ok": True, "active": None, "target": None,
                "targets": [], "ingest": None}
    return {
        "ok": True,
        "active": target.get("id"),
        "target": target,
        "targets": projects.list_targets(),
        "ingest": None,
    }


def _active_target_id() -> str:
    """Id target aktif, atau "" kalau belum ada target.

    Dipakai untuk mengelompokkan history operasi & approval. Kalau tidak ada
    target aktif, hasilnya "" - itu BUKAN "semua target", jadi instalasi yang
    belum punya target melihat daftar kosong, bukan history repo lain yang
    bocor lewat layar kosong.
    """
    active = projects.get_active()
    if not isinstance(active, dict):
        return ""
    return active.get("id") or ""


def _switch_target(target_id: str) -> dict:
    """Aktifkan sebuah target dan jaga storage + engine tetap konsisten.

    Dua hal HARUS terjadi bersama-sama:
      - storage.set_active_target() : file DB yang dibaca berubah
      - engine.invalidate_graph_cache() : graph in-memory dibangun ulang

    Kalau hanya yang pertama, user berganti repo tapi /graph/*, /repo_health,
    /complexity_report masih melaporkan graph repo sebelumnya.
    """
    target = projects.set_active(target_id)
    storage.set_active_target(target_id)
    engine.invalidate_graph_cache()
    return target


@app.get("/api/targets/browse", tags=["Targets"])
def browse_target_dirs(path: str = ""):
    """Daftar subfolder di `path` untuk dipilih sebagai target analisis.

    BEDA dengan `/browse` (yang terkurung di dalam repo/workspace): endpoint ini
    ada supaya "Folder lokal" bisa membuka folder PC mana pun, karena folder
    yang mau dipilih belum tentu ada di allowed_roots(). Agar itu tetap aman,
    yang dikembalikan HANYA nama direktori - tidak ada nama file, tidak ada
    ukuran - dan folder kredential (.ssh, .aws, .gnupg, .kube, .config/gcloud)
    ditolak.

    Path kosong berarti folder home, titik awal yang wajar untuk memilih folder
    proyek. Folder home sendiri tetap TIDAK bisa dijadikan target; itu dicek
    terpisah di projects.create_target().
    """
    try:
        return projects.browse_target_dirs(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/targets", tags=["Targets"])
def list_targets():
    """Daftar target yang terdaftar, plus target aktif.

    `active` null berarti belum ada target, dan semua endpoint graph akan
    mengembalikan graph kosong. Itu kondisi normal untuk instalasi baru.
    """
    return {
        "ok": True,
        "active": (projects.get_active() or {}).get("id"),
        "target": projects.get_active(),
        "targets": projects.list_targets(),
    }


@app.post("/api/targets", tags=["Targets"])
def create_target(req: TargetCreateRequest):
    """Daftarkan target baru (folder lokal atau repo GitHub ter-sync).

    Path divalidasi di projects.create_target(): harus ada, berupa folder,
    dan lolos settings_store.is_readable_path(). Kegagalan validasi
    dikembalikan sebagai 400/403, bukan 500.
    """
    try:
        target = projects.create_target(
            kind=req.kind,
            label=req.label,
            path=req.path,
            source=req.source,
            branch=req.branch,
            make_active=req.make_active,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if req.make_active:
        _switch_target(target["id"])

    ingest = None
    if req.ingest and target.get("available"):
        # Ingest gagal tidak membatalkan pendaftaran target: target-nya
        # tetap valid, user bisa mencoba ulang tanpa daftar ulang.
        ingest = engine.ingest_repository(target["path"])
        if not ingest.get("ok"):
            target = projects.get_active() or target
    payload = _target_payload(target)
    payload["ingest"] = ingest
    return payload


@app.patch("/api/targets/{target_id}", tags=["Targets"])
def update_target(target_id: str, req: TargetUpdateRequest):
    """Ubah label/branch. Path tidak bisa diubah lewat endpoint ini."""
    if not projects.is_valid_id(target_id):
        raise HTTPException(status_code=400, detail="Target id tidak valid")
    try:
        target = projects.update_target(
            target_id, label=req.label, branch=req.branch
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Target not found")
    return _target_payload(target)


@app.post("/api/targets/{target_id}/activate", tags=["Targets"])
def activate_target(target_id: str, req: IngestRequest | None = None):
    """Pindahkan target aktif. Graph in-memory di-rebuild seketika.

    `ingest=true` (default) langsung memindai folder target itu, jadi user
    tidak perlu klik kedua untuk melihat data. Caller yang hanya ingin
    berpindah bisa kirim ingest=false.
    """
    if not projects.is_valid_id(target_id):
        raise HTTPException(status_code=400, detail="Target id tidak valid")
    try:
        target = _switch_target(target_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Target not found")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    want_ingest = True if req is None else bool(getattr(req, "ingest", True))
    ingest = None
    if want_ingest and target.get("available"):
        ingest = engine.ingest_repository(target["path"])
    payload = _target_payload(target)
    payload["ingest"] = ingest
    return payload


@app.delete("/api/targets/{target_id}", tags=["Targets"])
def delete_target(
    target_id: str,
    remove_graph: bool = False,
):
    """Hapus target dari registry. `remove_graph=true` ikut menghapus graph.

    Default remove_graph=false supaya user tidak kehilangan hasil pindai
    hanya karena salah Target. Tidak ada kebocoran path di sini: file DB
    dihapus lewat storage.db_path_for_target() yang menyaring id lebih dulu.
    """
    if not projects.is_valid_id(target_id):
        raise HTTPException(status_code=400, detail="Target id tidak valid")
    try:
        removal = projects.delete_target(target_id, remove_graph=remove_graph)
    except KeyError:
        raise HTTPException(status_code=404, detail="Target not found")

    # Kalau target yang dihapus sedang aktif, registry sudah menunjuk ke
    # target lain (atau None). Terapkan supaya storage & engine ikut.
    active = projects.ensure_active_applied()
    engine.invalidate_graph_cache()
    return {
        "ok": True,
        "deleted": target_id,
        "active": (active or {}).get("id"),
        "target": active,
        "targets": projects.list_targets(),
        # Diporto ke depan supaya user tidak mengira graph sudah hilang padahal
        # file-nya masih terkunci. graph_path sengaja tidak ikut: path absolut
        # server tidak ada gunanya di browser.
        "graph_removed": removal.get("graph_removed"),
    }


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
            conn = sqlite3.connect(path)
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
    """🛡️ Daftar semua operasi yang menunggu approval manusia.

    Disaring per target aktif: approval untuk repo lain tidak boleh muncul di
    sini, karena menyetujuinya berarti menyetujui perubahan pada folder yang
    tidak sedang dianalisis.
    """
    return guardian.list_pending_approvals(target_id=_active_target_id())


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

    FILTER PER TARGET: rows disaring ke `operations.target_id` milik target
    aktif. Ini yang membuat halaman Operations, Agents, dan Security (ketiganya
    membaca endpoint ini) tidak lagi menampilkan history repository atau
    folder lain. `?all_targets=true` sengaja TIDAK ada: menampilkan history
    target lain lewat parameter query hanya membuat UI Studien salah target
    bisa terjadi tanpa sengaja.

    Riwayat operasi yang target-nya sudah dihapus dari registry TIDAK ikut
    terhapus - barisnya tetap di DB, cuma tidak terlihat karena tidak ada
    target dengan id itu lagi. Jadi approval lama tidak hilang saat folder
    dihapus dari daftar.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    where = ["COALESCE(target_id, '') = ?"]
    params: list = [_active_target_id()]
    if status:
        where.append("status = ?")
        params.append(status)
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM operations WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT ?",
        params,
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

def _github_oauth_redirect_uri(request: Request) -> str:
    """
    Redirect URI untuk tukar-kode jadi token, diturunkan dari host yang benar-benar
    menghubungi backend.

    Default lama menunjuk ke http://localhost:3000/auth/github/callback - route
    Next.js yang tidak pernah ada. GitHub lalu mengirim `code` ke sana, tidak ada
    yang menukar kode itu, dan user terkunci di halaman 404. Yang lebih buruk,
   menukar kode di dalam browser justru membuka jalan token GitHub lolos ke
   client, padahal kontrak repo ini: token tidak pernah ada di browser.
    """
    return f"{str(request.base_url).rstrip('/')}/api/github/callback"


@app.get("/api/github/auth/url", tags=["GitHub"])
def github_oauth_url(request: Request, redirect_uri: str | None = None):
    """Get GitHub OAuth authorization URL."""
    from urllib.parse import urlencode
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured (GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET)",
        )
    redirect_uri = redirect_uri or _github_oauth_redirect_uri(request)
    scope = "repo read:org read:user"
    # redirect_uri harus persis sama dengan yang dipakai saat tukar kode,
    # jadi keduanya di-encode lewat dict, bukan dirakit dengan f-string.
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": "synapse",
        }
    )
    url = f"https://github.com/login/oauth/authorize?{query}"
    return {"url": url, "state": "synapse", "redirect_uri": redirect_uri}

@app.get("/api/github/callback", tags=["GitHub"])
def github_callback(request: Request, code: str, state: str = "", redirect_uri: str | None = None):
    """Handle GitHub OAuth callback, exchange code for access token."""
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    # Harus identik dengan yang dikirim ke GitHub di /api/github/auth/url,
    # kalau tidak GitHub menolak tukar kode dengan "redirect_uri mismatch".
    redirect_uri = redirect_uri or _github_oauth_redirect_uri(request)

    # Exchange code for token
    import requests
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
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
    )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")
    
    user = user_resp.json()
    
    # Store connection
    from auth import encrypt_token
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO github_connections 
           (id, type, access_token, scope, user_login, user_avatar, updated_at)
           VALUES (?, 'oauth', ?, ?, ?, ?, ?)""",
        (f"oauth:{user['login']}", encrypt_token(access_token), "repo,read:org,read:user", 
         user["login"], user.get("avatar_url", ""), guardian._utcnow_iso())
    )
    conn.commit()
    conn.close()
    
    # Browser mendarat di sini dari GitHub, jadi balas dengan redirect supaya
    # user mendarat di aplikasi. Pesan status lewat query string karena
    # respons JSON di address bar tidak ada tombol balik ke app.
    #
    # PENTING: aplikasi ini single-page shell di "/". Navigasi ke Settings
    # berjalan client-side (activePage di app/page.tsx); tidak ada route
    # /settings, jadi redirect ke sana berakhir di 404 Next. Karena itu
    # page=settings ikut dikirim dan dibaca app/page.tsx untuk halaman awal.
    from urllib.parse import urlencode
    qs = urlencode({
        "page": "settings",
        "tab": "github",
        "github": "connected",
        "login": user["login"],
    })
    return RedirectResponse(url=f"http://localhost:3000/?{qs}", status_code=303)


@app.delete("/api/github/connection", tags=["GitHub"])
def github_disconnect():
    """Disconnect GitHub: hapus semua token yang tersimpan."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM github_connections")
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "removed": max(removed, 0)}

@app.post("/api/github/auth/pat", tags=["GitHub"])
def github_pat(req: GitHubPATRequest):
    """Validate and store GitHub Personal Access Token."""
    import requests
    import sqlite3
    from datetime import datetime
    from auth import encrypt_token
    
    # Validate token
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {req.pat}", "Accept": "application/vnd.github+json"},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid PAT")
    
    user = resp.json()
    scopes = req.scopes
    
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
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
    )
    if resp.status_code != 200:
        return {"ok": False, "connected": False, "error": "Token expired or invalid"}
    return {"ok": True, "connected": True, "user": resp.json(), "type": row["type"]}

def _github_token() -> str:
    """
    Token GitHub yang tersimpan, sudah di-decrypt.

    Disatukan karena pola "buka DB -> SELECT github_connections -> decrypt
    -> HTTPException 401" diulang di lima endpoint; menyalinnya berarti
    satu endpoint bisa lupa decrypt atau lupa cek None.
    """
    import sqlite3
    from auth import decrypt_token

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="No GitHub connection")
    return decrypt_token(row["access_token"])


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


@app.get("/api/github/repos", tags=["GitHub"])
def github_repos(per_page: int = 100, page: int = 1):
    """List repositories accessible by the authenticated user."""
    import requests

    resp = requests.get(
        f"https://api.github.com/user/repos?per_page={per_page}&page={page}&sort=updated",
        headers=_github_headers(_github_token()),
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Failed to fetch repos")
    return {"ok": True, "repos": resp.json()}


@app.get("/api/github/repos/{owner}/{repo}/tree", tags=["GitHub"])
def github_repo_tree(owner: str, repo: str, branch: str = "main", recursive: bool = True):
    """Get repository file tree."""
    import requests

    url = (
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
        f"?recursive={1 if recursive else 0}"
    )
    resp = requests.get(url, headers=_github_headers(_github_token()))
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch tree: {resp.text}")
    return resp.json()

@app.get("/api/github/repos/{owner}/{repo}/contents", tags=["GitHub"])
def github_file_content(owner: str, repo: str, path: str, branch: str = "main"):
    """Get file content from repository."""
    import requests

    from urllib.parse import quote

    token = _github_token()
    # `path` bisa berisi "/" dan karakter khusus; di-encode per segmen
    # supaya "a b/c.py" tidak jadi 404 karena spasi mentah.
    encoded = "/".join(quote(seg, safe="") for seg in path.strip("/").split("/"))
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded}"
        f"?ref={quote(branch, safe='')}"
    )
    resp = requests.get(url, headers=_github_headers(token))
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch file: {resp.text}")
    return resp.json()


class GitHubSyncRequest(BaseModel):
    source: str
    branch: str = "main"
    label: str | None = None
    ingest: bool = True
    make_active: bool = True


@app.post("/api/github/repos/sync", tags=["GitHub"])
def github_sync_target(req: GitHubSyncRequest):
    """
    Unduh repo GitHub ke workspace lalu jadikan target yang dianalisis.

    Ini yang membuat "ganti repository" benar-benar mengganti sumber data,
    bukan cuma melihat file lewat browser. Urutannya penting:

      1. unduh tarball + ekstrak aman  -> github_sync.py
      2. daftarkan foldernya sebagai target (kind="github")
      3. aktifkan target itu  -> storage + engine pindah DB graph
      4. ingest             -> graph terisi dari isi repo SEKARANG

    Sync memakai token yang sudah disimpan. Kalau token tidak ada, endpoint
    menolak 401 - bukan mencoba akses anonim, karena repo private akan
    gagal dengan 404 yang menyesatkan.
    """
    import github_sync

    try:
        github_sync.validate_source(req.source)
        github_sync.validate_branch(req.branch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    token = _github_token()
    source = req.source.strip().strip("/")
    try:
        result = github_sync.sync_repo(source=source, branch=req.branch, token=token)
    except github_sync.SyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    label = req.label or source
    existing = None
    for target in projects.list_targets():
        if target.get("source") == source:
            existing = target
            break

    try:
        if existing:
            target = projects.update_target(
                existing["id"], label=label, branch=req.branch
            )
        else:
            target = projects.create_target(
                kind="github",
                label=label,
                path=result["path"],
                source=source,
                branch=req.branch,
                make_active=False,
            )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    if req.make_active:
        try:
            _switch_target(target["id"])
        except KeyError:
            raise HTTPException(status_code=404, detail="Target not found")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    ingest = None
    if req.ingest:
        # Ingest gagal TIDAK membatalkan sync: file sudah ada di disk dan
        # target sudah terdaftar, jadi user bisa retry tanpa unduh ulang.
        ingest = engine.ingest_repository(result["path"])

    payload = _target_payload(target)
    payload["sync"] = result
    payload["ingest"] = ingest
    return payload


# ---------------------------------------------------------------------------
# LLM Provider Registry
# ---------------------------------------------------------------------------

# Tipe provider yang dikenali. Sisanya tetap diterima: users menjalankan
# LM Studio, vLLM, Together, Groq, atau proxy internal yang tidak ada di
# daftar ini, dan semuanya speak OpenAI-compatible chat/completions.
#
# Kenapa `type` bukan Literal lagi: Literal membuat Pydantic menolak 422
# untuk "groq" atau "lmstudio", padahal keduanya provider yang sah dan
# bisa dikonfigurasi lewat base_url yang sama persis dengan openai-compatible.
# Daftar ini dipakai untuk (a) memberi base_url default saat type dikenali,
# (b) menentukan apakah boleh dihapus, bukan untuk menolak input.
KNOWN_PROVIDER_TYPES = (
    "openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama", "openai-compatible",
)

# Base URL default per tipe yang dikenali. Tipe di luar daftar tidak punya
# default: pemanggil wajib menyebut base_url sendiri, karena mengarang URL
# akan membuat request menembak endpoint yang salah tanpa melaporkan apa pun.
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
    "ibm": "https://us-south.ml.cloud.ibm.com/ml/v1",
}

# Tipe bawaan yang tidak boleh dihapus. openai-compatible TIDAK termasuk:
# itu user-provided, dan memblokir penghapusan hanya akan bikin user
# tidak bisa membersihkan provider yang tidak dipakai lagi.
UNDELETABLE_PROVIDER_TYPES = ("openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama")


def normalize_provider_type(raw: str) -> str:
    """
    Normalisasi nama tipe provider supaya yang sama tidak jadi dua provider.

    Urutan kandidat PENTING. "Open AI" adalah cara orang mengetik nama yang
    setiap hari, dan kalau spasinya diganti tanda hubung hasilnya "open-ai" -
    nama yang tidak ada di daftar bawaan. Akibatnya provider ini kehilangan
    base_url default dan user dipaksa mengetik URL yang sebenarnya sudah kami
    tahu benar. Jadi kandidat yang sudah cocok dengan daftar bawaan dicoba
    lebih dulu:

        "  OpenAI "  -> "openai"   (cocok persis)
        "Open AI"    -> "openai"   (spasi dihapus, cocok)
        "open ai"    -> "openai"   (spasi dihapus, cocok)
        "openai compatible" -> "openai-compatible" (cocok persis, dengan spasi)
        "vllm"       -> "vllm"     (tidak dikenal, dipakai apa adanya)

    Batasnya yang perlu diketahui: "open ai compatible" TIDAK menjadi
    "openai-compatible". squashed-nya "openaicompatible" dan dashed-nya
    "open-ai-compatible", keduanya tidak ada di daftar bawaan, jadi hasilnya
    "open-ai-compatible" dan diperlakukan sebagai tipe custom. Tidak apa-apa
    karena tipe itu memang tidak punya base_url default, tapi jangan menulis
    kode-nya sebaliknya - frontend/lib/llmProviders.ts harus meniru urutan di
    sini persis, bukan yang tertulis di docstring.

    Regex hanya menyaring karakter yang tidak mungkin jadi nama file/URL.
    """
    text = (raw or "").strip().lower()
    if not text:
        return "openai-compatible"
    squashed = re.sub(r"\s+", "", text)
    dashed = "-".join(text.split())
    for candidate in (text, squashed, dashed, dashed.replace("-", "_")):
        if candidate in PROVIDER_BASE_URLS or candidate in KNOWN_PROVIDER_TYPES:
            return candidate
    # Tipe custom: buang karakter yang akan merusak id dan base_url.
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", dashed).strip("-")
    return cleaned or "openai-compatible"


def _as_provider_dict(provider) -> dict:
    """Terjemahkan baris provider apa pun jadi dict biasa.

    BUG-41: pemanggil mengambil provider lewat
    `conn.execute(...).fetchone()` dengan `row_factory = sqlite3.Row`. Row
    mendukung `row["base_url"]` tapi TIDAK punya `.get()`, jadi helper yang
    memanggil `.get()` melempar AttributeError dan /api/llm/chat membalas 500
    untuk semua provider - termasuk yang konfigurasinya benar.

    `dict(row)` berhasil karena Row mengimplementasikan keys() dan __getitem__.
    Ditaruh di sini, bukan di tiap pemanggil, supaya endpoint LLM baru tidak
    harus ingat hal ini.
    """
    return provider if isinstance(provider, dict) else dict(provider)


def _is_local_provider(provider) -> bool:
    """True kalau provider kemungkinan besar jalan di localhost, jadi API key opsional.

    Base URL dengan host loopback (localhost, 127.0.0.1, ::1) atau memakai
    skema file:// dianggap lokal. Ini membiarkan ollama dan LM Studio/vLLM
    lokal dikonfigurasi tanpa key, tanpa membuat daftar yang harus
    ditambahkan setiap kali ada server lokal baru.

    Terima dict atau sqlite3.Row; lihat _as_provider_dict.
    """
    provider = _as_provider_dict(provider)
    base_url = (provider.get("base_url") or "").strip().lower()
    if not base_url:
        return provider.get("type") == "ollama"
    if base_url.startswith("file://"):
        return True
    try:
        host = urlsplit(base_url).hostname or ""
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local")


def resolve_provider_base_url(provider) -> str | None:
    """Base URL final untuk sebuah provider, atau None kalau tidak bisa ditebak.

    Urutannya: base_url eksplisit > default dari tipe yang dikenali > None.
    None berarti pemanggil harus menolak dengan pesan jelas, bukan menembak
    API default OpenAI karena tipe provider-nya "groq".

    Terima dict atau sqlite3.Row; lihat _as_provider_dict.
    """
    provider = _as_provider_dict(provider)
    explicit = (provider.get("base_url") or "").strip()
    if explicit:
        return explicit
    return PROVIDER_BASE_URLS.get(provider.get("type") or "")


class LLMProviderCreate(BaseModel):
    name: str
    type: str = "openai-compatible"
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] = []
    default_model: str = ""
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_vision: bool = False
    enabled: bool = True

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        return normalize_provider_type(v)

    @model_validator(mode="after")
    def _require_base_url_for_unknown_type(self) -> "LLMProviderCreate":
        # Tipe di luar daftar tidak punya base_url default. Tanpa base_url
        # request akan jatuh ke default OpenAI dan gagal dengan 401 yang
        # menyesatkan, atau worse, succeeding di akun yang salah.
        if self.base_url is None and self.type not in PROVIDER_BASE_URLS:
            raise ValueError(
                f"base_url wajib diisi untuk tipe {self.type!r}: tipe ini bukan "
                "provider bawaan, jadi Synapse tidak menebak endpoint-nya"
            )
        return self


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    default_model: str | None = None
    max_tokens: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    enabled: bool | None = None

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str | None) -> str | None:
        return None if v is None else normalize_provider_type(v)

@app.get("/api/llm/providers", tags=["LLM"])
def list_llm_providers():
    """List all configured LLM providers."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
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
    
    conn = sqlite3.connect(DB_PATH)
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
                # `a or b[0] if c else d` di-parse sebagai `(a or b[0]) if c else d`,
                # jadi default_model yang diisi user hilang begitu models kosong.
                json.dumps(req.models),
                req.default_model or (req.models[0] if req.models else ""),
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
    
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Provider not found")
    # Allow deletion of custom providers only
    if existing["type"] in UNDELETABLE_PROVIDER_TYPES:
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
    conn = sqlite3.connect(DB_PATH)
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
    # String kosong berarti "pakai default_model provider". Sengaja tidak
    # required: kalau required, Pydantic membalas 422 "field required" yang
    # tidak menjelaskan bahwa provider-nya memang belum punya model, dan
    # user tidak tahu harus ke tab LLM mana. llm_chat() yang menolak dengan
    # 400 plus pesan yang bisa langsung ditindaklanjuti.
    model: str = ""
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = 4096
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | None = None

@app.post("/api/llm/chat", tags=["LLM"])
async def llm_chat(req: ChatCompletionRequest):
    """Chat completion with LLM provider."""
    import sqlite3
    import json
    import asyncio
    import httpx
    from auth import decrypt_token
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    provider = conn.execute("SELECT * FROM llm_providers WHERE id = ? AND enabled = 1", (req.provider_id,)).fetchone()
    conn.close()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")
    # BUG-41: ini sqlite3.Row, bukan dict. _is_local_provider() dan
    # resolve_provider_base_url() sekarang menerima keduanya (lihat
    # _as_provider_dict), jadi tidak perlu diubah di sini - tapi jangan
    # panggil .get() langsung pada variabel ini.
    provider = _as_provider_dict(provider)

    api_key = decrypt_token(provider["api_key"]) if provider["api_key"] else None
    # Tanpa api key, hanya server lokal yang masuk akal (ollama, atau
    # openai-compatible tanpa auth seperti LM Studio). Provider hosting
    #/public tetap butuh key, dan lebih baik ditolak di sini daripada
    # mendapat 401 yang tidak jelas dari pihak ketiga.
    if not api_key and not _is_local_provider(provider):
        raise HTTPException(status_code=400, detail="Provider not configured with API key")

    model = req.model or provider["default_model"]
    if not model:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provider tidak punya model. Pilih model di tab LLM "
                "(Settings) atau kirim 'model' secara eksplisit."
            ),
        )

    if provider["type"] == "ollama":
        # Ollama local
        base_url = provider["base_url"] or "http://localhost:11434"
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
        # OpenAI-compatible. Ini juga jalur untuk SEMUA tipe di luar daftar
        # (groq, together, lmstudio, vllm, proxy internal): semuanya speak
        # chat/completions yang sama, hanya endpoint-nya yang berbeda.
        base_url = resolve_provider_base_url(provider)
        if not base_url:
            # Provider type ini tidak punya default yang aman. Menebak URL
            # OpenAI di sini akan mengirim prompt user - dan isi repo - ke
            # akun yang tidak diminta, jadi tolak dengan pesan yang bisa
            # ditindaklanjuti.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Provider tipe {provider['type']!r} tidak punya base_url. "
                    "Isi base_url di tab LLM (Settings) supaya Synapse tahu "
                    "endpoint yang benar."
                ),
            )
        base_url = base_url.rstrip("/")

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
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
    context = engine.ask_about(req.topic)
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
    context = engine.review_change(req.path_or_diff)
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
    context = engine.propose_refactor(req.node_name)
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
    conn = sqlite3.connect(DB_PATH)
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
    
    conn = sqlite3.connect(DB_PATH)
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


@app.post("/api/rag/ingest", tags=["RAG"])
async def rag_ingest(req: RAGIngestRequest):
    """Ingest files into RAG vector store."""
    import sqlite3
    import json
    import hashlib
    import httpx
    from auth import decrypt_token

    # Validasi SELURUH entri lebih dulu, sebelum query DB, decrypt_token, atau
    # panggilan jaringan apa pun. Kalau validasi dilakukan setelahnya,
    # request berbahaya bisa lolos, atau pun tertutup 404 "Provider not found"
    # sehingga penolakan aslinya tidak pernah terlihat.
    resolved = [_resolve_ingest_entry(entry) for entry in req.files]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    provider = conn.execute("SELECT * FROM llm_providers WHERE id = ? AND enabled = 1", (req.provider_id,)).fetchone()
    conn.close()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")
    
    api_key = decrypt_token(req.api_key) if req.api_key else None
    model = req.model or "text-embedding-3-small"
    
    # Generate embeddings
    chunks = []
    for content in resolved:
        lines = content.split('\n')
        chunk = []
        for line in lines:
            chunk.append(line)
            if len('\n'.join(chunk)) >= req.chunk_size:
                chunks.append('\n'.join(chunk))
                # overlap
                overlap = chunk[-req.chunk_overlap//50:] if req.chunk_overlap else []
                chunk = overlap
        if chunk:
            chunks.append('\n'.join(chunk))
    
    # Generate embeddings
    embeddings = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"model": model, "input": chunk}
            headers = {"Authorization": f"Bearer {decrypt_token(provider['api_key'])}", "Content-Type": "application/json"}
            base_url = provider["base_url"] or "https://api.openai.com/v1"
            resp = await client.post(f"{base_url}/embeddings", json=payload, headers={"Authorization": f"Bearer {decrypt_token(provider['api_key'])}", "Content-Type": "application/json"}, timeout=30.0)
            if resp.status_code == 200:
                embeddings.append({"chunk": chunk, "embedding": resp.json()["data"][0]["embedding"]})
    
    # Store in DB (simple approach - store in rag_chunks table)
    from datetime import datetime as _dt  # BUG-NEW-5 FIX: datetime tidak diimport di scope ini
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS rag_chunks (
        id TEXT PRIMARY KEY,
        chunk TEXT NOT NULL,
        embedding TEXT NOT NULL,  -- JSON array
        metadata TEXT,  -- JSON
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    for emb in embeddings:
        chunk_id = hashlib.md5(emb["chunk"].encode()).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks (id, chunk, embedding, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, emb["chunk"], json.dumps(emb["embedding"]), json.dumps({"provider": req.provider_id, "model": model}), guardian._utcnow_iso())
        )
    conn.commit()
    conn.close()
    
    return {"ok": True, "chunks": len(embeddings)}

@app.post("/api/rag/search", tags=["RAG"])
async def rag_search(req: RAGSearchRequest):
    """Search RAG vector store for relevant chunks."""
    import sqlite3
    import json
    import numpy as np
    import httpx
    from auth import decrypt_token
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    provider = conn.execute("SELECT * FROM llm_providers WHERE id = ? AND enabled = 1", (req.provider_id,)).fetchone()
    conn.close()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")
    
    # Generate query embedding
    model = req.model or "text-embedding-3-small"
    api_key = decrypt_token(provider["api_key"])
    base_url = provider["base_url"] or "https://api.openai.com/v1"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{provider['base_url'] or 'https://api.openai.com/v1'}/embeddings",
            json={"model": model, "input": req.query},
            headers={"Authorization": f"Bearer {decrypt_token(provider['api_key'])}", "Content-Type": "application/json"},
            timeout=30.0
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        query_embedding = np.array(resp.json()["data"][0]["embedding"])
    
    # Search in DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, chunk, embedding, metadata FROM rag_chunks").fetchall()
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
    return {"ok": True, "results": results[:req.top_k]}


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "synapse-backend", "version": "0.2.0"}
