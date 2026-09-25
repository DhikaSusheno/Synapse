# Frontend PRD — Graph + Dashboard

Scope untuk: [@nabilfauzandafa](https://github.com/nabilfauzandafa) (FE-1 · Graph), [@ShannWasHere](https://github.com/ShannWasHere) (FE-2 · Dashboard).
Konteks penuh: [`../SYNAPSE.md`](../SYNAPSE.md) section 2.

## Goal (dari SYNAPSE.md 2.4, bagian yang frontend tanggung jawab)

Siapa pun (termasuk non-teknis, yaitu juri) bisa melihat satu graph hidup dan paham: apa yang sedang dipahami sistem, dan apa yang sedang dilindungi.

## Deliverable wajib

| # | Deliverable | Owner | Bergantung pada |
|---|---|---|---|
| 1 | Force-directed graph (`react-force-graph-2d`) pakai data mock dulu | FE-1 | — (bisa mulai sebelum backend siap) |
| 2 | Sidebar penjelasan + tombol approve/deny (mock) | FE-2 | — |
| 3 | Sambungkan graph ke SSE asli dari BE-2 | FE-1 | Backend deliverable #5 (SSE stream) |
| 4 | Sambungkan dashboard ke API asli (`operations`, `approvals`) | FE-2 | Backend deliverable #1–2 |
| 5 | Poles animasi pulse/warna node (pending=kuning, approved=hijau, rolled_back=merah berkedik→hijau) | FE-1 | — |
| 6 | Poles UI, tangani state kosong/error | FE-2 | — |

**Jangan kejar animasi mulus duluan** — kejar "kelihatan hidup" dulu. Kalau waktu habis, tabel event log biasa yang live-update sudah cukup.

## Kontrak (jangan asumsikan sendiri — sepakati dengan backend di jam 0–2)

- Bentuk event SSE per state transition (lihat `../backend/MASTER_PROMPT.md`).
- Skema `operations`/`approvals` di [`../SYNAPSE.md`](../SYNAPSE.md) section 4.2 — field yang dipakai UI: `blast_radius`, `status`, `requires_approval`, `conflicts`.

## Non-Goals

- Bukan tempat implementasi rule engine atau rollback logic — itu murni tanggung jawab backend, frontend hanya render state.
- Tidak perlu D3 penuh — cukup 1 dependency ringan (`react-force-graph-2d`).

## Definition of done per fase

- **Jam 2**: bentuk event SSE disepakati dengan backend.
- **Jam 16**: demo internal pertama — graph & dashboard harus render sesuatu yang nyambung ke backend, walau kasar.
- **Jam 30**: semua bug dari QC masuk daftar perbaikan.
- **Jam 40**: stop nambah fitur baru, mulai rehearsal.
