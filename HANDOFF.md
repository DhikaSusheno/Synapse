# HANDOFF — Synapse Frontend (konteks lanjutan)

Brief asli proyek ada di [`SYNAPSE.md`](SYNAPSE.md) dan
[`frontend/MASTER_PROMPT.md`](frontend/MASTER_PROMPT.md). Dokumen ini bukan brief —
ini catatan state pekerjaan untuk sesi berikutnya.

## Peran
Kamu senior dev yang lazy dan teliti. Bahasa: Indonesia gaya caveman (fragment ok,
tanpa filler, istilah teknis persis). Kode, commit, PR, dan komentar issue ditulis
normal. Gate dulu: apakah ini perlu ada sama sekali.

## Tugas
Lanjutkan job FE-1 `@nabilfauzandafa` dan FE-2 `@ShannWasHere` di folder `frontend/`.
Sumber: issue GitHub #37, #38, #39, #40 (repo DhikaSusheno/Synapse).

## Repo
- Path lokal: `C:\Users\Nabil Fauzan Daffa\synapse-repo-clone`
- Branch: `frontend/live-data` (push sudah sinkron dengan `origin/frontend/live-data`)

Struktur: `backend/` (FastAPI, `guardian.py`, `cortex.py`, `engine.py`),
`security/tests/` (pytest, 6 file), `frontend/` (Next.js app router).

Sebelum kerja: `git fetch --all --prune`, baca `main`, cek PR + issue terbuka,
baca kontrak API backend, lalu jalankan ulang test.

## Commit yang sudah push (jangan di-rework tanpa alasan)
- `8c75932` bug FE-2: `res.json()` lalu `res.clone()` (fix #37), deny `failed`→`denied`,
  false success, stale/mock list, mojibake, fake Cortex insight.
- `8003b68` ignore sqlite `*.db-wal` / `*.db-shm`.
- `0b0f8f6` hapus `OperationsSidebar.tsx` dead code, History approvals dari `/operations`.
- `603ed7a` merge `origin/main` (PR #42 engine-knowledge-graph) + resolve konflik.
- `4d0335b` satu request `/operations?limit=100`, conflict dari backend, hapus `withConflicts()`.
- `bc0d2f9` #38 SSE singleton, #39 `decideOperation`, #40 animasi SynapseGraph tanpa re-render.

## Keputusan arsitektur (sudah dipakai, jangan diubah tanpa alasan)
- **Satu sumber data**: pending + history + conflict banner dari satu
  `GET /operations?limit=100` (`hooks/useOperations.ts`, filter `requires_approval === 1`).
- `/list_pending_approvals` **tidak dipakai**: endpoint itu tidak mengirim `conflicts`.
- **Kontrak**: `/approve_operation` → `{ ok, status, new_status }`.
  Execute hanya boleh setelah approve `ok`. Implementasinya di `lib/operations.ts`
  (`decideOperation`), dipakai GuardianPage, GuardianPanel, ApprovalCard. Jangan tulis
  approve/execute inline lagi.
- **Satu koneksi SSE**: `lib/sseStream.ts` (transport tunggal: fanout, refcount, exponential
  backoff BUG-08) + `hooks/useSSEStream.ts` (wrapper React). Agents, CodeGraph, Security,
  SynapseGraph semua lewat hook itu. Jangan `new EventSource` di komponen.
- Animasi SynapseGraph pakai ref (`animTimeRef`), bukan `setState` per frame.

## Status issue
- #37 double `res.json()` → **fixed** di `8c75932`, belum ditutup.
- #38 4 koneksi `/stream` → **fixed** di `bc0d2f9` + `lib/sseStream.test.ts`, belum ditutup.
- #39 approve/execute inline 3 tempat → **fixed** di `bc0d2f9` + 6 test, belum ditutup.
- #40 re-render 60fps → **fixed** di `bc0d2f9`, belum ditutup.
- README `frontend/README.md` sudah diperbarui (endpoint, struktur file, tabel mitigasi).

## Verifikasi terakhir (semua hijau)
- `cd frontend; npm test` → 27/27
- `npm run typecheck` (tsc --noEmit) → clean
- `npm run lint` (next lint) → No ESLint warnings or errors
- FE `http://localhost:3000` → 200, backend `http://localhost:8000` → 200
- `python -m pytest security/tests -q` → 86 passed (JALAN dari repo root, bukan `backend/`)

## Sisa pekerjaan
1. Buka PR `frontend/live-data` → `main` dengan ringkasan fix #37–#40 + hasil test.
2. Comment + tutup issue #37, #38, #39, #40 dengan bukti (commit hash, 27/27 test).
3. Visual check manual di browser biasa (headless Chrome gagal: GCM/updater access denied).
4. Audit integrasi endpoint baru `backend/engine.py` (PR #42) — belum dicek sisi FE.

## Aturan keamanan (penting)
- GitHub CLI `gh` 2.101.0 terpasang, **belum login**.
- JANGAN pernah memakai token yang di-paste user di chat. Dua PAT sudah terekspos →
  wajib di-revoke oleh user di Settings → Developer settings → Personal access tokens.
- Login harus lewat `gh auth login --hostname github.com --git-protocol https --web`
  yang dijalankan user sendiri di terminalnya. Credensial masuk Windows Credential Manager.
- Kalau `gh` belum login, jangan minta token di chat. Minta user login sendiri.
- `gh` ada di: `%LOCALAPPDATA%\Microsoft\WinGet\Packages\GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\gh.exe`
  (terminal baru sudah ada alias `gh`).

## Jebakan tooling yang sudah ketahuan
- `node --test` di Node 24 pakai strip-only TS: **dilarang** TypeScript parameter
  property (`constructor(public x: string)`) dan top-level `await`. Tulis eksplisit.
- `EventSource` bukan global di Node → test SSE perlu stub global manual.
- PowerShell 5.1 `Set-Content`/`Out-File` bisa merusak encoding UTF-8. Untuk edit file
  pakai tool edit, bukan Set-Content.
- `git grep`/scan secret pakai pola `ghp_[A-Za-z0-9]{20,}`, jangan pernah echo token penuh.
