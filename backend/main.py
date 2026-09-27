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
import ipaddress
import json
import os
import re
import socket
import sys
from urllib.parse import urlsplit
import sqlite3

# Issue #74 fix: Pastikan stdout/stderr pakai UTF-8 agar emoji/unicode
# pada endpoint seperti /repo_health tidak menyebabkan UnicodeEncodeError
# pada terminal Windows (default encoding cp1252).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
#
# allow_methods harus memuat SEMUA method yang benar-benar dipakai route.
# Daftar lama ("GET","POST","OPTIONS") membuang PUT/PATCH/DELETE, padahal
# ketiganya punya route nyata: PUT /api/projects/{id}/llm-config (:1255),
# PATCH /api/llm/providers/{id} (:943), DELETE /api/llm/providers/{id}
# (:1001). Akibatnya preflight membalas tanpa method itu dan browser
# memblokir request silang-originnya — endpoint terlihat ada tapi tidak
# pernah bisa dipakai dari frontend lintas origin.
# OPTIONS ikut dicantumkan supaya daftar ini tetap dibaca apa adanya.
app.add_middleware(
    CORSMiddleware,
    allow_origins=auth.allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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


# M6 FIX: batas ukuran body request.
#
# FastAPI/Pydantic membatasi isinya, tapi TIDAK membatasi berapa banyak byte
# yang dibaca dari koneksi: body dibaca dulu, baru diparse. Tanpa batas sini,
# satu request `POST` berukuran beberapa GB cukup untuk menghabiskan memori
# proses — endpoint mana pun bisa dipakai sebagai pemantik OOM tanpa token
# pun pernah diperiksa (middleware ini berjalan paling luar, sebelum auth).
#
# Content-Length diperiksa lebih dulu supaya request yang jelas-jelas
# terlalu besar ditolak sebelum satu byte pun dibaca.
#
# CATATAN JUJUR: ini menangani klien yang menyatakan ukurannya. Klien yang
# berbohong (CL kecil lalu tetap men-stream) tetap perlu ditahan di lapis
# edge — nginx `client_max_body_size` atau `uvicorn --limit-max-requests`.
# Membungkus `receive` di middleware untuk menghitung byte sungguhan berarti
# menyentuh API privat Starlette, dan nilainya tidak sebanding dengan
# risikonya selama edge juga menegakkan batas yang sama.
MAX_REQUEST_BODY_BYTES = int(
    os.environ.get("SYNAPSE_MAX_BODY_BYTES", str(32 * 1024 * 1024))
)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    declared = request.headers.get("content-length")
    if declared is None:
        # Tanpa CL (chunked) tidak bisa dinilai di awal; biarkan route yang
        # memutuskan. Edge-lah yang menangani kasus ini.
        return await call_next(request)

    try:
        size = int(declared)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Header Content-Length tidak valid"},
        )

    if size < 0:
        return JSONResponse(
            status_code=400,
            content={"detail": "Header Content-Length tidak valid"},
        )

    if size > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "detail": (
                    f"Body terlalu besar ({size} byte, maksimal "
                    f"{MAX_REQUEST_BODY_BYTES} byte)"
                )
            },
        )

    return await call_next(request)


# Handler startup sudah dipindah ke lifespan() di atas.



# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class UnderstandRepoRequest(BaseModel):
    # M6: seluruh field string di blok ini dulu tanpa batas. Repo path,
    # topik, nama node, dan id operasi adalah identifier — nilainya memang
    # pendek, jadi membiarkannya tanpa batas hanya membuka satu jalan untuk
    # memasukkan payload raksasa ke database dan ke respons SSE.
    repo_path: str = Field(max_length=4096)

class ExplainTopicRequest(BaseModel):
    topic: str = Field(max_length=512)

class ReviewArtifactRequest(BaseModel):
    # path_or_diff memuat diff yang bisa besar, jadi batasnya longgar —
    # dan tetap dibatasi MAX_REQUEST_BODY_BYTES di middleware.
    path_or_diff: str = Field(max_length=10_000_000)

class FindPathRequest(BaseModel):
    from_node: str = Field(max_length=512)
    to_node: str = Field(max_length=512)

class SuggestRefactorRequest(BaseModel):
    node_name: str = Field(max_length=512)

class ProposeOperationRequest(BaseModel):
    # H4 FIX: dulu ketiganya tanpa batas sama sekali.
    #
    # `target` dipakai MENTAH oleh guardian sebagai id sekaligus nama node
    # graph (`f"operation_target::{target}"`), jadi string sepanjang apa pun
    # yang dikirim klien ikut tersimpan di database dan muncul di seluruh
    # endpoint /graph/*. Batas 512 karakter jauh di atas target yang wajar
    # (nama file, simbol, id repo) tapi cukup untuk mencegah pembesaran graph
    # dari satu request.
    #
    # `tool_name` dibatasi panjangnya saja, bukan pola karakternya: guardian
    # memang HARUS menerima tool_name yang aneh dan menjadikannya fail-closed
    # (lihat security/tests/test_adversarial.py A5b yang menguji persis itu).
    # Membuangnya di lapis HTTP akan menghapus pengujian jalur fail-closed.
    tool_name: str = Field(min_length=1, max_length=128)
    params: dict = {}
    target: str = Field(min_length=1, max_length=512)

class ExecuteOperationRequest(BaseModel):
    operation_id: str = Field(max_length=64)  # UUID = 36 karakter

class ApproveOperationRequest(BaseModel):
    operation_id: str = Field(max_length=64)
    decision: str  # diverifikasi ulang di guardian.approve_operation()
    note: str = Field(default="", max_length=4096)


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
def browse(path: str = Query("", max_length=4096, description="Path relatif terhadap repo root")):
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
    redirect_uri: str = Field(
        default="http://localhost:3000/auth/github/callback", max_length=2048
    )

class GitHubPATRequest(BaseModel):
    pat: str = Field(max_length=512)
    scopes: list[str] = ["repo", "read:org", "read:user"]


# M7 FIX: redirect_uri dulu diterima apa adanya lalu di-interpolasi langsung
# ke URL authorize GitHub tanpa encoding dan tanpa validasi.
#
# Dua akibatnya:
#   1. Injeksi parameter. Nilai berisi "&" memotong redirect_uri sendiri dan
#      menambahkan query param lain ke URL authorize (mis. mengubah scope
#      atau allow_signup). URL harus di-encode.
#   2. Open redirect. redirect_uri bisa diarahkan ke domain mana pun; meski
#      GitHub sendiri menolak URI yang tidak terdaftar, mengandalkan penolakan
#      pihak ketiga berarti kebijakan kita tidak punya arti.
#
# Default hanya localhost (itulah nilai defaultnya), dan domain lain harus
# diizinkan eksplisit lewat SYNAPSE_OAUTH_REDIRECT_ALLOW, dipisah koma.
_OAUTH_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _oauth_redirect_allowed(raw: str) -> bool:
    if not raw or len(raw) > 2048:
        return False
    try:
        parts = urlsplit(raw)
    except ValueError:
        return False
    # fragment tidak pernah dikirim balik ke server dan hanya membingungkan
    # perbandingan; userinfo (user:pass@) tidak ada gunanya di redirect URI.
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.netloc or parts.fragment or parts.username:
        return False
    if parts.hostname in _OAUTH_LOCAL_HOSTS:
        return True
    allow = {
        item.strip().rstrip("/")
        for item in os.environ.get("SYNAPSE_OAUTH_REDIRECT_ALLOW", "").split(",")
        if item.strip()
    }
    return raw.rstrip("/") in allow


def _require_valid_redirect(raw: str) -> str:
    if not _oauth_redirect_allowed(raw):
        raise HTTPException(
            status_code=400,
            detail=(
                "redirect_uri tidak diizinkan. Hanya http(s) ke localhost "
                "yang diterima; domain lain harus didaftarkan di "
                "SYNAPSE_OAUTH_REDIRECT_ALLOW (comma-separated)."
            ),
        )
    return raw


def _github_oauth_redirect_uri(request: Request) -> str:
    """
    Redirect URI untuk tukar-kode jadi token, diturunkan dari host yang
    benar-benar menghubungi backend.

    Default lama menunjuk ke http://localhost:3000/auth/github/callback - route
    Next.js yang tidak pernah ada. GitHub lalu mengirim `code` ke sana, tidak
    ada yang menukar kode itu, dan user terkunci di halaman 404. Yang lebih
    buruk, menukar kode di dalam browser justru membuka jalan token GitHub
    lolos ke client, padahal kontrak repo ini: token tidak pernah ada di
    browser.

    Nilai turunan ini tetap harus lolos _require_valid_redirect: base_url ikut
    Host header, jadi tanpa gerbang whitelist ia open redirect yang disamarkan
    sebagai "derived from request".
    """
    return f"{str(request.base_url).rstrip('/')}/api/github/callback"


def _resolve_oauth_redirect(request: Request, redirect_uri: str | None) -> str:
    """Ambil redirect_uri dari query bila ada, else turunkan dari host request."""
    return _require_valid_redirect(redirect_uri or _github_oauth_redirect_uri(request))


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
    # M7: nilai dari query tetap harus lolos whitelist yang sama seperti di
    # langkah authorize - user boleh mengarahkan callback ke host lain.
    redirect_uri = _resolve_oauth_redirect(request, redirect_uri)

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
    from auth import decrypt_stored_token
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM github_connections ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "connected": False}
    token = decrypt_stored_token(row["access_token"])
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
    from auth import decrypt_stored_token

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
    return decrypt_stored_token(row["access_token"])


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


@app.get("/api/github/repos", tags=["GitHub"])
def github_repos(
    # M6: kedua nilai dulu bebas. per_page raksasa / page negatif dikirim apa
    # adanya ke api.github.com - GitHub membatasi per_page ke 100, jadi angka
    # besar hanya membuang-buang waktu dan membingungkan log sisi mereka tanpa
    # memberi apa pun kepada pemanggil.
    per_page: int = Query(100, ge=1, le=100),
    page: int = Query(1, ge=1, le=10000),
):
    """List repositories accessible by the authenticated user."""
    import requests

    resp = requests.get(
        f"https://api.github.com/user/repos?per_page={per_page}&page={page}&sort=updated",
        headers=_github_headers(_github_token()),
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Failed to fetch repos")
    return {"ok": True, "repos": resp.json()}

def _github_repo_segment(value: str, field: str, allow_slash: bool = False) -> str:
    """
    Segmen URL GitHub (owner, repo, branch).

    M8 FIX: nilai ini dulu dipasang mentah ke
    `https://api.github.com/repos/{owner}/{repo}/...`. FastAPI memang tidak
    memuat "/" literal dalam path param, tapi nilai yang dikirim ter-encode
    (%2F, %3F, %23) di-DECODE ulang sebelum masuk ke handler, sehingga
    pemanggil tetap bisa memasukkan "/", "?" atau "#" ke dalam URL tujuan —
    termasuk `..` yang mengubah struktur path. Permintaan tetap berakhir di
    api.github.com, tapi strukturnya bukan lagi endpoint yang dimaksud.

    Dibatasi ke charset nama repo/branch di GitHub, lalu di-encode ulang.
    `allow_slash` hanya untuk branch (`feature/x`) — owner dan repo selalu
    satu segmen tunggal.
    """
    if not value or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{field} tidak valid")
    if value in (".", "..") or ".." in value.split("/"):
        raise HTTPException(status_code=400, detail=f"{field} tidak valid")
    pattern = r"[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-]+)*" if allow_slash else r"[A-Za-z0-9._\-]+"
    if not re.fullmatch(pattern, value):
        raise HTTPException(status_code=400, detail=f"{field} tidak valid")
    return quote(value, safe="")


def _github_repo_path(value: str) -> str:
    """
    Path file di dalam repo (`src/main.go`). Boleh memuat "/" karena memang
    struktur direktori, tapi tidak boleh memuat "..", "?" atau "#" yang bisa
    mengubah URL tujuan, dan tetap di-encode ulang.
    """
    if not value or len(value) > 1024:
        raise HTTPException(status_code=400, detail="path tidak valid")
    if ".." in value.split("/") or value.startswith("/"):
        raise HTTPException(status_code=400, detail="path tidak valid")
    if not re.fullmatch(r"[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-]+)*", value):
        raise HTTPException(status_code=400, detail="path tidak valid")
    return quote(value, safe="/")

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

    # M8: sama seperti /tree - semua segmen dibatasi charset GitHub dulu,
    # baru di-encode. `path` boleh memuat "/" karena itu struktur direktori.
    owner = _github_repo_segment(owner, "owner")
    repo = _github_repo_segment(repo, "repo")
    branch = _github_repo_segment(branch, "branch", allow_slash=True)
    encoded = _github_repo_path(path)

    token = _github_token()
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded}"
        f"?ref={branch}"
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

# M9 FIX: base_url provider adalah TUJUAN REQUEST KELUAR yang dikendalikan
# pengguna - server lah yang menghubunginya, bukan browser. Nilai itu dulu
# diterima apa adanya, sehingga `base_url = "http://169.254.169.254/latest/meta-data/"`
# membuat Synapse ikut menembak metadata cloud (IAM credential) atau layanan
# internal yang tidak terekspos ke internet.
#
# Kebijakannya bertingkap karena kebutuhan nyata bertabrakan dengan SSRF:
#   - struktur URL SELALU divalidasi (scheme http/https saja, ada host,
#     tanpa userinfo/fragment) -> `file://`, `ftp://` dan URL aneh tertutup;
#   - alamat privat ditolak untuk provider SaaS publik (openai/anthropic/...),
#     di mana tujuan loopback atau RFC1918 tidak pernah sah;
#   - untuk `ollama` dan `openai-compatible`, localhost JUSTRU tujuan yang
#     normal (Ollama default di 11434), jadi ditolak hanya kalau operator
#     menyetel SYNAPSE_BLOCK_PRIVATE_UPSTREAM=1.
#   - SYNAPSE_ALLOW_PRIVATE_UPSTREAM=1 mematikan penolakan privat sepenuhnya
#     untuk operator yang sadar risikonya.
#
# CATATAN JUJUR: pemeriksaan ini berjalan SEBELUM request, sementara
# resolusi DNS bisa berubah di antara keduanya (DNS rebinding). Menutupnya
# penuh berarti membungkus transport HTTP dengan pinning IP, yang tidak
# sebanding di sini karena tetap butuh token API untuk mencapai endpoint ini.
_PUBLIC_SAE_TYPES = frozenset({"openai", "anthropic", "ibm", "nvidia", "deepseek"})


def _is_private_host(hostname: str) -> bool | None:
    """True = privat/loopback/link-local, False = publik, None = tak bisa dinilai."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return None  # gagal resolve: biarkan; request-nya sendiri akan gagal
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
        return False
    return None


def _validate_upstream_base_url(raw: str | None, provider_type: str) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None

    if len(value) > 2048:
        raise HTTPException(status_code=400, detail="base_url terlalu panjang")

    try:
        parts = urlsplit(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="base_url tidak valid")

    if parts.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="base_url harus memakai skema http atau https",
        )
    if not parts.hostname:
        raise HTTPException(status_code=400, detail="base_url tidak punya host")
    if parts.username or parts.password:
        raise HTTPException(
            status_code=400,
            detail="base_url tidak boleh memuat kredensial; pakai field api_key",
        )
    if parts.fragment:
        raise HTTPException(status_code=400, detail="base_url tidak boleh memuat fragment")

    allow_private = os.environ.get("SYNAPSE_ALLOW_PRIVATE_UPSTREAM", "") == "1"
    force_block = os.environ.get("SYNAPSE_BLOCK_PRIVATE_UPSTREAM", "") == "1"
    check_private = force_block or (
        provider_type in _PUBLIC_SAE_TYPES and not allow_private
    )
    if check_private and not allow_private:
        if _is_private_host(parts.hostname) is True:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"base_url menunjuk alamat privat/loopback untuk provider "
                    f"'{provider_type}'. Set SYNAPSE_ALLOW_PRIVATE_UPSTREAM=1 "
                    f"kalau ini memang disengaja."
                ),
            )
    return value


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
    name: str | None = Field(default=None, max_length=256)
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

    # M9: tujuan request keluar divalidasi SEBELUM disimpan, supaya baris yang
    # sudah ada di database juga tidak pernah lolos begitu saja nanti.
    req.base_url = _validate_upstream_base_url(req.base_url, req.type)

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
        # M9: validasi memakai type BARU kalau request ikut mengubah type,
        # kalau tidak type yang sudah tersimpan — kebijakan SSRF-nya harus
        # mengikuti provider yang benar-benar akan dipakai.
        effective_type = req.type if req.type is not None else (existing["type"] or "")
        req.base_url = _validate_upstream_base_url(req.base_url, effective_type)
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


# BUG-45: streaming chat mati dengan "NetworkError when attempting to fetch
# resource" di browser.
#
# Bentuk yang salah (dan yang dipakai sebelum fix ini):
#
#     async with httpx.AsyncClient() as client:
#         async def stream_response():
#             async with client.stream(...) as resp:
#                 yield ...
#         return StreamingResponse(stream_response(), ...)
#
# `stream_response()` dipanggil untuk membuat OBJECK generator, bukan
# dijalankan. Prosecutnya selesai - `async with` menutup client - baru
# FastAPI mulai meng-iterate generator. Generator-nya lalu memakai client
# yang sudah ditutup: request ke provider mati di tengah jalan, koneksi
# HTTP terputus sebelum response selesai, dan fetch() di browser DITOLAK
# (bukan 500, bukan 502 - fetch-nya sendiri yang gagal). Gejalanya persis
# "Error: NetworkError when attempting to fetch resource." sementara
# /api/llm/explain - yang stream=False - tetap jalan. Provider di Settings
# juga tetap jalan karena tidak lewat jalur ini sama sekali.
#
# Dua perbaikan sekaligus:
#   1. Client dibuat DI DALAM generator, jadi umurnya mengikuti stream.
#   2. Status response provider Dicek SEBELUM StreamingResponse dikembalikan.
#      401/429/500 dari provider jadi HTTP error yang bisa ditampilkan
#      ("Provider menolak: ..."), bukan koneksi yang diputus diam-diam.
#
# `open_stream` menerima client yang sudah hidup dan mengembalikan context
# manager response streaming-nya; pemanggil deciding URL dan payload-nya.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Nginx/proxy mana pun yang menahan response sampai penuh akan membatalkan
    # seluruh tujuan SSE.
    "X-Accel-Buffering": "no",
}

# Body error dari provider dipotong; message-nya bisa jadi halaman HTML
# panjang atau echoed payload user, dan ini masuk ke response ke browser.
_MAX_PROVIDER_ERROR_BYTES = 600


def _provider_error_detail(status: int, body: bytes, provider_type: str) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        text = "(body kosong)"
    return f"Provider {provider_type!r} membalas HTTP {status}: {text[:_MAX_PROVIDER_ERROR_BYTES]}"


async def _sse_proxy(open_stream, provider_type: str = "provider"):
    """Bungkus satu request streaming provider jadi StreamingResponse SSE.

    open_stream: callable(client) -> async context manager yang mengembalikan
    response streaming dari provider.

    async, bukan sync, karena status response provider harus diperiksa SEBELUM
    StreamingResponse dikembalikan. Kalau pemeriksaannya duduk di dalam
    generator, response sudah "terkirim" begitu generator pertama kali
    dijalankan dan HTTPException di dalamnya tidak lagi bisa jadi status -
    hasilnya koneksi mati di tengah, yaitu NetworkError yang asli.
    """
    import httpx

    client = httpx.AsyncClient(timeout=60.0)
    try:
        resp_cm = open_stream(client)
        resp = await resp_cm.__aenter__()
    except Exception as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Gagal menghubungi provider {provider_type!r}: {exc}",
        )

    if resp.status_code >= 400:
        try:
            body = await resp.aread()
        except Exception:
            body = b""
        try:
            await resp_cm.__aexit__(None, None, None)
        finally:
            await client.aclose()
        raise HTTPException(
            status_code=502 if resp.status_code != 400 else 400,
            detail=_provider_error_detail(resp.status_code, body, provider_type),
        )

    async def body():
        try:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                line_str = line.strip() if isinstance(line, str) else line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                if line_str.startswith("data: ") or line_str.startswith("event: ") or line_str.startswith("id: ") or line_str.startswith("retry: "):
                    yield f"{line_str}\n\n"
                else:
                    yield f"data: {line_str}\n\n"
        finally:
            # Generator bisa ditutup di tengah (user tekan Clear, atau browser
            # menutup tab). Tanpa finally, socket ke provider menggantung
            # sampai timeout.
            try:
                await resp_cm.__aexit__(None, None, None)
            finally:
                await client.aclose()

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)

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
    from auth import decrypt_stored_token
    
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

    api_key = decrypt_stored_token(provider["api_key"]) if provider["api_key"] else None
    # Tanpa api key, hanya server lokal yang masuk akal (ollama, atau
    # openai-compatible tanpa auth seperti LM Studio). Provider hosting
    # /public tetap butuh key, dan lebih baik ditolak di sini daripada
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
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": req.stream,
            "options": {"temperature": req.temperature, "num_predict": req.max_tokens},
        }
        if req.stream:
            return await _sse_proxy(
                lambda client: client.stream(
                    "POST", f"{base_url}/api/chat", json=payload, timeout=60.0
                ),
                provider["type"],
            )
        async with httpx.AsyncClient(timeout=60.0) as client:
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

        if req.stream:
            return await _sse_proxy(
                lambda client: client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60.0,
                ),
                provider["type"],
            )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60.0
            )
            return resp.json()


class ExplainRequest(BaseModel):
    provider_id: str = Field(max_length=64)
    model: str | None = Field(default=None, max_length=128)
    topic: str = Field(max_length=512)
    context_limit: int = 5

class ReviewRequest(BaseModel):
    provider_id: str = Field(max_length=64)
    model: str | None = Field(default=None, max_length=128)
    path_or_diff: str = Field(max_length=10_000_000)
    context: str | None = Field(default=None, max_length=1_000_000)

class RefactorRequest(BaseModel):
    provider_id: str = Field(max_length=64)
    model: str | None = Field(default=None, max_length=128)
    node_name: str = Field(max_length=512)

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
    # chunk_size/chunk_overlap dulu bebas nilainya. Akibatnya:
    #   chunk_size <= 0  -> syarat `len(...) >= chunk_size` selalu benar, jadi
    #                       SEMUA baris terkirim sebagai chunk terpisah. Satu
    #                       file 100rb baris berarti 100rb panggilan API pihak
    #                       ketiga dari satu request, dan itu DoS mandiri yang
    #                       dibayar pemilik API key.
    #   chunk_size raksasa -> 1 chunk meledak melewati context window provider.
    # Batas di atas (8000 karakter) masih jauh di bawah context window mana pun
    # (8k token ~ 32k karakter) dan membatasi biaya per request.
    chunk_size: int = Field(default=1000, ge=1, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=4000)

class RAGSearchRequest(BaseModel):
    provider_id: str = Field(max_length=64)
    model: str | None = Field(default=None, max_length=128)
    query: str = Field(max_length=8192)
    # top_k tanpa batas berarti satu request bisa meminta jutaan baris
    # embedding dari SQLite dan meledakkan memori respons.
    top_k: int = Field(default=5, ge=1, le=50)

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
    from auth import decrypt_stored_token, decrypt_client_token

    # Validasi SELURUH entri lebih dulu, sebelum query DB, decrypt, atau
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
    
    # api_key berasal dari BODY request, bukan dari database — klien tidak
    # pernah menerima nilai terenkripsi dari endpoint mana pun (lihat
    # list_llm_providers yang hanya memilih kolom tanpa api_key). Kegagalan
    # decrypt di sini karena itu salah klien -> 400, bukan 500.
    api_key = decrypt_client_token(req.api_key) if req.api_key else None
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
    #
    # Dibuka sekali di luar loop karena decrypt_stored_token() tidak murah dan
    # nilainya sama untuk semua chunk. Variabel `headers` di versi lama dihitung
    # di dalam loop tapi TIDAK PERNAH dipakai — post() memakai dict inline
    # sendiri, sehingga decrypt dijalankan dua kali per chunk hanya untuk
    # dibuang.
    embed_api_key = decrypt_stored_token(provider['api_key'])
    embed_headers = {
        "Authorization": f"Bearer {embed_api_key}",
        "Content-Type": "application/json",
    }
    base_url = provider["base_url"] or "https://api.openai.com/v1"
    embeddings = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"model": model, "input": chunk}
            resp = await client.post(
                f"{base_url}/embeddings",
                json=payload,
                headers=embed_headers,
                timeout=30.0,
            )
            # Diam-diam melewatkan chunk yang gagal (versi lama) membuat
            # sebagian dokumen tidak pernah masuk index tanpa satu pun
            # error yang terlihat — retrieval lalu mengembalikan hasil
            # parsial yang tampak sah. Gagal keras dengan kode provider
            # supaya ingest gagal penuh dan bisa diulang.
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Provider menolak chunk embedding (HTTP "
                        f"{resp.status_code}). Ingest dibatalkan agar index "
                        f"tidak tersimpan parsial."
                    ),
                )
            embeddings.append(
                {"chunk": chunk, "embedding": resp.json()["data"][0]["embedding"]}
            )
    
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
    from auth import decrypt_stored_token
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    provider = conn.execute("SELECT * FROM llm_providers WHERE id = ? AND enabled = 1", (req.provider_id,)).fetchone()
    conn.close()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found or disabled")
    
    # Generate query embedding
    model = req.model or "text-embedding-3-small"
    api_key = decrypt_stored_token(provider["api_key"])
    base_url = provider["base_url"] or "https://api.openai.com/v1"
    
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
