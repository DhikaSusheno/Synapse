# Synapse — Reversible, Conflict-Aware Understanding Layer for Agentic Development

> **Status**: Berdiri sendiri. **Tidak bergantung ke ATRest** — semua arsitektur di bawah dirancang dibangun dari nol, solo, dalam 48 jam, tanpa Redis/Neo4j/Qdrant/Ollama. Kalau nanti ATRest ternyata jalan mulus, bisa jadi upgrade path opsional — tapi bukan prasyarat.

---

## 0. Ringkasan Eksekutif

**Satu kalimat (awam)**: Synapse kasih AI coding agent dua hal — peta hidup yang nunjukin gimana kode saling terhubung, dan refleks otomatis yang membalikkan kesalahan sebelum jadi bencana, bahkan kalau ada beberapa agent bekerja bersamaan.

**Satu kalimat (teknis)**: Sebuah MCP-native layer yang (1) membangun knowledge graph hybrid AST+LLM dari sebuah repo untuk onboarding & review, dan (2) mencegat operasi berisiko yang dijalankan agent (migration, restart, deploy), menjamin reversibilitas lewat snapshot otomatis + verifikasi + rollback, dengan kesadaran konflik antar-agent yang bekerja bersamaan.

**Nama kerja**: **Synapse**
**Event**: IBM Bob 2.0 Hackathon, lablab.ai — 25-27 September 2026
**Eksekusi**: Solo, ~10-16 jam/hari

---

## 1. MASTER PROMPT

> Blok ini dirancang untuk dipakai langsung sebagai brief awal ke IBM Bob 2.0 (atau ke diri sendiri sebagai peta kerja). Copy-paste apa adanya kalau perlu.

```
You are building "Synapse" — a reversible, conflict-aware understanding layer
for AI coding agents, built for the IBM Bob 2.0 Hackathon.

ROLE: You (Bob 2.0 agent mode) are the ONLY orchestrator. There is no message
bus, no separate planner daemon. You decompose the user's natural-language
goal and call the tool endpoints below directly and in parallel where
independent.

GOAL: Given a target repository, provide two capabilities:
  1. UNDERSTAND — build and visualize a knowledge graph of the repo (files,
     symbols, dependencies, docs) so a human can onboard, and so a reviewer
     can score changes for correctness/clarity.
  2. PROTECT — before executing any risky, hard-to-reverse operation
     (schema migration, service restart, config write, deploy), generate a
     reversibility plan, gate it by risk, execute, verify post-conditions,
     and auto-rollback on failure. Before acting, check whether any other
     in-flight or recent operation touches an overlapping resource
     (conflict-aware gating) — do not act blindly in isolation.

TOOLS YOU CAN CALL (exposed via MCP by our FastAPI server):
  - understand_repo(repo_path) -> ingests repo: tree-sitter AST pass builds
    the structural skeleton (files/functions/classes/imports), then you
    (Bob) read README/docs/PRDs and propose DOCUMENTS/EXPLAINS/REFERENCES
    edges between docs and code entities. Returns graph diff for the live
    visualization.
  - explain_topic(topic) -> "mentor" capability. Search the graph + relevant
    file contents, return a plain-language explanation with 1 concrete
    example, structured: definition -> mental model -> example.
  - review_artifact(path_or_diff) -> "reviewer" capability. Score on 4
    dimensions (completeness, clarity, correctness-vs-spec, risk) using the
    graph as context. Return verdict: pass | needs_work | block.
  - propose_operation(tool_name, params, target) -> "guardian" capability,
    step 1. Classify blast_radius via the static rule table (see PRD
    section 4.4). Check for CONFLICTS_WITH: any operation touching an
    overlapping target created/executed within the last N minutes and not
    yet verified-complete. If found, force human approval regardless of
    blast_radius. Generate a reversibility plan (snapshot strategy per
    operation type). Return: {operation_id, blast_radius, conflicts,
    plan, requires_approval}.
  - execute_operation(operation_id) -> only after approval (auto or human).
    Runs the real operation, then runs the verification checks from
    `synapse.invariants.yaml`. On failure, automatically executes the
    stored rollback plan and marks the operation `rolled_back`. Emits SSE
    events at every state transition.
  - list_pending_approvals() / approve_operation(operation_id, decision)

CONSTRAINTS:
  - No Redis, no Neo4j, no Qdrant, no Ollama. Storage = SQLite (nodes/edges
    tables), in-memory networkx for traversal. This must run with
    `pip install -r requirements.txt && uvicorn main:app` and nothing else.
  - Ship the DB migration operation type FULLY end-to-end before touching
    any other operation type (service restart, config write, file delete
    are config-only stubs for the demo, not deeply implemented).
  - Every risky action MUST have a rollback plan or MUST require human
    approval — never silently proceed on an unknown operation type
    (fail-closed default).
  - Build a scripted, reproducible failure scenario for the demo (a
    migration that breaks something on purpose) — this is the single most
    important scene to get reliable before polishing anything else.

PRIORITY ORDER (stop at any point and you still have a demoable product):
  1. propose_operation + execute_operation for DB migration, single agent,
     no conflict-check yet — this alone is demoable.
  2. Add conflict-check (the two-operations-same-target scenario).
  3. Add understand_repo + explain_topic (Cortex/onboarding half).
  4. Add review_artifact.
  5. Polish the live graph visualization (SSE-driven, force-directed).

OUTPUT OF EVERY STEP: keep the SQLite graph and the SSE event log as the
single source of truth — the frontend renders straight from these, no
duplicate state.
```

---

## 2. PRD (Product Requirements Document)

### 2.1 Problem Statement

Tiga masalah yang saling terkait di era AI-assisted development (2026):

1. **Verification debt** — developer tidak percaya penuh pada kode/keputusan yang dihasilkan AI agent, dan review-nya makan waktu lebih lama dari sebelumnya.
2. **Risiko tindakan tak-terbalikkan** — makin banyak agent dikasih akses tulis ke infra nyata (migration, deploy, restart), tapi tidak ada jaminan otomatis bahwa tindakan itu bisa dibatalkan kalau salah.
3. **Konflik antar-agent** — begitu lebih dari satu agent (atau agent + manusia) bekerja bersamaan di resource yang sama, tidak ada mekanisme standar untuk mendeteksi dan mengarbitrase konflik sebelum terjadi kerusakan.

### 2.2 Bukti (riset & data, dengan sitasi)

| Klaim | Sumber |
|---|---|
| 96% developer tidak sepenuhnya percaya output AI; hanya 48% selalu verifikasi sebelum commit | 2026 State of Code Developer Survey (Sonar) |
| 45% bilang debugging kode hasil AI lebih lama dari perkiraan ("verification debt") | Stack Overflow / VentureBeat coverage 2026 |
| 63% developer sebut technical debt sebagai frustrasi kerja #1 | Technical Debt Statistics 2026 |
| **79% enterprise pernah harus reverse tindakan agent-nya; 42% mengalami revenue loss** dari kegagalan agent | Survei enterprise 2026, dikutip di *"Safe to Resume?"* (arXiv 2608.29381) |
| Sistem multi-agent produksi gagal 41-86.7%; **79% dari kegagalan itu soal koordinasi, bukan kapabilitas model** ("stale read hazard") | *Semantic Consensus* (arXiv 2604.16339) |
| Belum ada karakterisasi formal kapan rencana antar-agent kompatibel — riset eksplisit menyerukan concurrency control jadi prioritas | *Position: Multi-Agent Systems Should Prioritize Concurrency Control* (arXiv 2608.18092) |
| Rollback yang "sukses" teknis bisa menghasilkan state yang secara historis mustahil (efek eksternal tak terbalikkan) | *Safe to Resume?* (arXiv 2608.29381) |
| Knowledge graph murni LLM-extracted kurang reliable dibanding hybrid dengan AST | *Reliable Graph-RAG for Codebases: AST-Derived vs LLM-Extracted* (arXiv 2601.08773) |

### 2.3 Target User & Persona

- **Backend/infra engineer** yang mulai kasih AI agent akses tulis ke sistem produksi — butuh jaminan reversibilitas.
- **Tech lead / reviewer** yang kebanjiran PR hasil AI — butuh scoring cepat + konteks graph.
- **Developer baru** onboarding ke codebase asing — butuh penjelasan kontekstual, bukan baca kode mentah.

### 2.4 Goals

1. Setiap operasi berisiko yang dijalankan agent punya jalur rollback otomatis yang terverifikasi.
2. Konflik antar-operasi/antar-agent terdeteksi **sebelum** eksekusi, bukan setelah rusak.
3. Siapa pun (termasuk non-teknis) bisa melihat satu graph hidup dan paham: apa yang sedang dipahami sistem, dan apa yang sedang dilindungi.

### 2.5 Non-Goals (scope eksplisit, biar gak melar)

- **Tidak** membangun policy engine generik multi-protokol (bukan OPA clone) — MCP-only untuk hackathon ini.
- **Tidak** membangun ML risk-scoring — rule-based/heuristik saja.
- **Tidak** menjamin reversibilitas untuk efek eksternal non-idempotent (webhook, email terkirim) — cukup **dideteksi dan dipaksa approval manusia**, bukan dibatalkan otomatis (ini batasan yang jujur, sesuai temuan riset di 2.2).
- **Tidak** bergantung ke ATRest atau infrastruktur pribadi lain yang belum diverifikasi.

### 2.6 Fitur

**Wajib (MVP demo):**
1. `propose_operation` + `execute_operation` — jalur DB migration, snapshot → approve → eksekusi → verifikasi → auto-rollback kalau gagal.
2. Conflict check — dua operasi menyentuh target sama dalam window waktu tertentu → operasi kedua otomatis butuh approval, bahkan kalau blast radius-nya kecil sendirian.
3. `understand_repo` + `explain_topic` — ingest repo (AST + Bob baca dokumen), graph terbentuk, bisa ditanya "jelasin modul X".
4. Dashboard web — graph hidup, event real-time lewat SSE.

**Nice-to-have (dipotong pertama kalau waktu kurang):**
5. `review_artifact` — scoring PR/dokumen 4 dimensi.
6. Snapshot strategy untuk tipe operasi selain migration (restart servis, config write).
7. Export audit log (CSV).

### 2.7 Metrik Sukses (buat pitch, bukan buat production)

- Waktu dari "operasi berisiko diminta" sampai "rollback selesai" saat skenario gagal disuntikkan: **< 10 detik** di demo.
- 100% operasi tak dikenal (tidak match rule apa pun) **wajib** minta approval manusia — nol pengecualian (fail-closed, dibuktikan lewat 1 skenario demo eksplisit).
- Graph terbentuk dari repo sample dalam < 30 detik saat live ingest di depan juri.

---

## 3. Workflow

### 3.1 Development Workflow (solo, 48 jam efektif)

Ikuti PRIORITY ORDER di Master Prompt (section 1) secara ketat — tiap tahap harus menghasilkan sesuatu yang demoable sebelum lanjut ke tahap berikutnya.

| Fase | Jam (kumulatif) | Output yang harus ada di akhir fase | Checkpoint gagal → tindakan |
|---|---|---|---|
| **0. Setup** | 0–2 | FastAPI + SQLite kosong jalan, `uvicorn main:app` sukses, schema nodes/edges dibuat | — |
| **1. Guardian inti** | 2–10 | `propose_operation`+`execute_operation` buat 1 tipe (migration) end-to-end, tanpa conflict-check, tanpa UI — dites lewat curl/Postman | Kalau jam 10 belum jalan, potong ke jalur paling minimal: 1 hardcoded migration, gak usah generic |
| **2. Conflict-aware** | 10–16 | Tambah pengecekan overlap target antar-operasi dalam window waktu | Kalau susah, downgrade jadi: 2 operasi manual ke resource sama → yang kedua otomatis blocked (hardcode window, jangan generalisir dulu) |
| **3. Cortex ingest** | 16–24 | `understand_repo` jalan: tree-sitter parse struktur + Bob baca README → graph terisi | Kalau tree-sitter ribet, fallback: parse manual pakai `ast` module Python (repo demo sengaja pilih yang Python) |
| **4. Mentor Q&A** | 24–28 | `explain_topic` jalan, jawab dari graph + isi file | — |
| **5. Dashboard** | 28–38 | Web graph + SSE live update — **jangan kejar animasi mulus, kejar "kelihatan hidup"** | Kalau waktu abis, tabel event log biasa juga cukup asal live-update |
| **6. Reviewer (opsional)** | 38–42 | `review_artifact` kalau masih ada waktu — **potong duluan kalau mepet** | — |
| **7. Rehearsal & rekam fallback** | 42–46 | Ulang skenario gagal→rollback berkali-kali sampai reliable, **rekam video sebagai fallback demo** | Ini bukan opsional — ini asuransi kalau live demo ngadat di depan juri |
| **8. Submission** | 46–48 | Slide, screenshot sesi task Bob, deskripsi submission, kirim lebih awal | — |

**Aturan keras**: begitu masuk fase 7, **stop nulis fitur baru**. Resiko break sesuatu yang udah jalan lebih mahal dari fitur tambahan apa pun.

### 3.2 User/Demo Workflow (alur pemakaian, 3 menit)

```
[Judge/Bob] "pahami repo ini"
      │
      ▼
understand_repo() ──► graph mulai terbentuk live di layar (AST dulu, lalu edge semantik dari Bob)
      │
      ▼
[Judge/Bob] "jelasin modul X ke developer baru"
      │
      ▼
explain_topic() ──► node menyala, penjelasan muncul di sidebar
      │
      ▼
[Judge/Bob] "tambahin kolom wajib lewat migration"
      │
      ▼
propose_operation() ──► node operasi muncul kuning (pending), snapshot dibuat otomatis
      │
      ▼
[approve] ──► execute_operation() ──► verifikasi lolos ──► hijau
      │
      ▼
[Judge/Bob] "migration KEDUA yang sengaja rusak, target sama"
      │
      ▼
propose_operation() ──► terdeteksi CONFLICTS_WITH operasi sebelumnya ──► auto-approval diblokir
      │  (kalau tetap dipaksa jalan untuk demo)
      ▼
execute_operation() ──► verifikasi GAGAL ──► auto-rollback ──► merah berkedip → pulih hijau
```

### 3.3 Workflow Integrasi Bob 2.0 (MCP)

```
Bob 2.0 (agent mode, orchestrator)
   │  MCP tools/call (paralel jika independen)
   ▼
Synapse MCP Server (FastAPI + MCP adapter)
   ├── understand_repo      → tree-sitter + doc read
   ├── explain_topic        → graph query + file read
   ├── review_artifact      → graph context + scoring
   ├── propose_operation    → rule engine + conflict check + plan generator
   ├── execute_operation    → jalankan + verifikasi + rollback
   └── SSE /stream          → event tiap state transition, dikonsumsi dashboard
```

---

## 4. Arsitektur Teknis (Standalone — Tanpa ATRest)

### 4.1 Stack

| Layer | Pilihan | Alasan |
|---|---|---|
| Backend | Python + FastAPI | Cepat dibangun solo, ekosistem MCP Python matang |
| Storage graph | **SQLite** (`nodes`, `edges` table) + `networkx` in-memory buat traversal | Nol setup server, jalan di laptop tanpa docker sama sekali |
| Parsing struktur | **tree-sitter** (via `tree-sitter-languages`) | AST deterministik, jawab langsung gap reliabilitas di paper 2601.08773 |
| Enrichment semantik | Bob 2.0 sendiri (baca README/docs via document understanding) | Gak butuh model embedding terpisah |
| Real-time | **SSE bawaan FastAPI** (`StreamingResponse`) | Gak butuh Redis buat pub/sub |
| Frontend | Next.js + `react-force-graph-2d` | Satu dependency ringan, bukan D3 penuh |
| Snapshot demo migration | Copy file SQLite demo DB (`.backup`) sebelum eksekusi | Jauh lebih ringan dari `pg_dump`, cukup buat demo |

**Total dependency eksternal buat jalan: nol server tambahan.** `pip install -r requirements.txt && npm install && npm run dev` — itu saja.

### 4.2 Skema Data (SQLite)

```sql
nodes (id, type, name, meta_json, created_at)
  -- type: file | symbol | dependency | doc | operation

edges (id, source_id, target_id, relationship, confidence, created_at)
  -- relationship: DOCUMENTS | EXPLAINS | REFERENCES | IMPLEMENTED_BY
  --               | TARGETS | CONFLICTS_WITH | ROLLED_BACK_BY

operations (id, tool_name, params_json, target_node_id, blast_radius,
            reversibility_class, status, snapshot_ref, rollback_command,
            requires_approval, created_at, executed_at, verified_at)

approvals (operation_id, decision, decided_at, note)
```

### 4.3 Reversibility Plan per Tipe Operasi (MVP: migration saja yang dalam)

| Tipe | Snapshot | Rollback |
|---|---|---|
| DB migration (SQLite demo) | Copy file `.db` → `.db.bak.<timestamp>` | Restore dari `.bak` |
| Service restart (stub, config only) | Catat status terakhir | Redeploy versi tercatat |
| Config write (stub) | Copy file lama | Restore file lama |
| Tak dikenal | — | **Wajib approval manusia, tidak ada eksekusi otomatis** |

### 4.4 Rule Table (blast radius, statis — bukan ML)

```yaml
rules:
  - match: { tool: "db.run_migration" }
    blast_radius: high
    reversibility: needs_snapshot
    require_approval: true

  - match: { tool: "service.restart" }
    blast_radius: medium
    reversibility: needs_snapshot
    require_approval: false

  - match: "*"
    blast_radius: unknown
    reversibility: irreversible_suspected
    require_approval: true   # fail-closed default
```

### 4.5 Conflict Detection (inti keunggulan riset)

```
Sebelum propose_operation() disetujui otomatis:
  query edges WHERE relationship = 'TARGETS'
    AND target_node_id = <target operasi baru>
    AND source operation.status IN ('pending', 'executing', 'executed_unverified')
    AND created_at > now() - WINDOW_MINUTES

  Kalau ada hasil → buat edge CONFLICTS_WITH, paksa require_approval = true,
  terlepas dari blast_radius individunya.
```

Ini bagian yang **belum ada di sistem rollback manapun yang ditemukan di riset 2026** (DeltaBox/AgentRewind/Shepherd/ACRFence semuanya single-agent-aware, bukan conflict-aware).

---

## 5. Diferensiasi & Kenapa Ini Bukan Klaim Kosong

| Sudah ada di riset/pemenang lalu | Jangan diklaim sebagai baru | Yang Synapse tambahkan |
|---|---|---|
| Rollback/checkpoint agent (DeltaBox, AgentRewind, Shepherd, ACRFence) | "Rollback pertama untuk AI agent" | **Rollback yang conflict-aware** — belum ada sistem bernama yang menangani ini |
| Knowledge graph via MCP (CodebaseMemory, GraphCodeAgent) | "Graph pertama untuk repo via MCP" | Hybrid AST+LLM (jawab gap reliabilitas arXiv 2601.08773), disatukan dengan proteksi di graph yang sama |
| Audit trail (Pedigree, juara 1 lalu) | "Audit pertama" | Audit yang **bertindak** (rollback), bukan cuma mencatat |
| Peta visual onboarding (Atlas, juara 2 lalu) | "Visual pertama" | Peta yang **hidup** dan menunjukkan konflik + proteksi real-time, bukan proxy ukuran file statis |

**Posisi jujur buat pitch**: *"Kami tidak mengklaim menemukan rollback atau knowledge graph — riset 2026 sudah membuktikan keduanya penting (kutip DeltaBox, Semantic Consensus, dst). Yang belum ada siapa pun bangun adalah irisan keduanya: rollback yang sadar bahwa agent lain mungkin sudah bekerja di atas state yang baru dibatalkan."*

---

## 6. Pemetaan ke Kriteria Juri

- **Application of Technology**: Bob 2.0 sebagai orchestrator tunggal (bukan tempelan), MCP tools sebagai subagents, parallel dispatch native, document understanding buat enrichment graph.
- **Business Value**: 79% enterprise pernah reverse aksi agent, 42% rugi revenue — Synapse langsung menjawab ini dengan mekanisme otomatis, bukan proses manual.
- **Originality**: irisan riset conflict-aware rollback yang belum ada implementasinya (lihat section 5).
- **Presentation**: satu metafora (paham + refleks), satu layar visual, satu momen dramatis (rusak → pulih sendiri di depan juri).

---

## 7. Submission Checklist

- [ ] Judul, deskripsi singkat, deskripsi panjang
- [ ] Cover image + video presentasi + slide
- [ ] Link demo aplikasi (hosting/localhost+tunnel) + repo kode
- [ ] Screenshot sesi task Bob 2.0 (wajib)
- [ ] File/kode yang eksplisit menunjukkan bantuan Bob 2.0
- [ ] Video fallback (rekaman skenario rusak→rollback) siap kalau live demo gagal
- [ ] Lisensi MIT dicantumkan di repo

---

## 8. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Solo + waktu terbatas | Priority order ketat (section 1 & 3.1), berhenti kapan pun tetap demoable |
| Live demo gagal pas dinilai juri | Video fallback wajib direkam di fase 7 |
| tree-sitter setup ribet di waktu mepet | Fallback ke modul `ast` bawaan Python (repo demo pilih Python) |
| Scope conflict-detection kebablasan generik | Hardcode window waktu & 1 kasus overlap dulu, generalisir cuma kalau ada sisa waktu |
| Juri anggap ide "sudah ada" (rollback/graph) | Section 5 dipakai eksplisit di pitch — akui dasar riset, tunjukkan irisan yang baru |
