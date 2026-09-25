# Security & QC PRD — Rule Engine + Demo Reliability

Scope untuk: [@pidpid35](https://github.com/pidpid35) (QC-1 · Rule engine), [@zuyss](https://github.com/zuyss) (QC-2 · Demo/Integrasi).
Konteks penuh: [`../SYNAPSE.md`](../SYNAPSE.md) section 2.

## Goal (dari SYNAPSE.md 2.7, metrik yang QC yang buktikan)

- 100% operasi tak dikenal (tidak match rule apa pun) **wajib** minta approval manusia — nol pengecualian (fail-closed), dibuktikan lewat skenario tes eksplisit.
- Waktu dari "operasi berisiko diminta" sampai "rollback selesai" saat skenario gagal disuntikkan: **< 10 detik**.
- Graph terbentuk dari repo sample dalam **< 30 detik** saat live ingest.

## Deliverable wajib

| # | Deliverable | Owner | Target rule/kode di SYNAPSE.md |
|---|---|---|---|
| 1 | Daftar skenario uji (termasuk operasi tak dikenal) | QC-1 | section 4.4 rule table |
| 2 | Test case untuk rule table & blast radius (unknown tool → `require_approval: true`) | QC-1 | section 4.4 |
| 3 | Adversarial test: coba bobol jalur approval | QC-1 | section 4.5 conflict detection |
| 4 | Pastikan default fail-closed konsisten di semua jalur | QC-1 | section 2.5 non-goals |
| 5 | Repo demo + seed data + skenario migrasi yang sengaja rusak | QC-2 | section 3.2 demo workflow |
| 6 | Tes integrasi end-to-end backend↔frontend↔Bob | QC-2 | — |
| 7 | Uji ulang skenario rusak→rollback sampai reliable, rekam video fallback | QC-2 | section 3.1 fase 7 (wajib, bukan opsional) |
| 8 | Sahkan rollback benar-benar memulihkan state (bukan cuma "sukses teknis") | QC-1 | section 2.2 — rollback sukses bisa hasilkan state historis mustahil |

## Non-Goals

- Bukan tim yang menulis fitur baru — tugas kalian adalah menemukan yang rusak dan memverifikasi yang benar.
- Tidak menyimpan credential/secret asli di repo demo — pakai `.gitignore` di root.

## Definition of done per fase

- **Jam 2**: daftar skenario uji + repo demo/seed data disusun.
- **Jam 16**: mulai tulis test case rule engine begitu API pertama dari backend ada.
- **Jam 30**: semua temuan bug sudah dilaporkan balik ke backend/frontend (lihat panah feedback loop di `../synapse-build-flow.html`) — jangan menumpuk temuan.
- **Jam 40**: fase pengerasan selesai — mulai rehearsal penuh & rekam video fallback (asuransi kalau live demo gagal di depan juri).
- **Jam 46**: submission checklist bagian teknis & aset terisi.
