# Daftar Skenario Uji — Security & QC (QC-1 · pidpid35)

Dokumen ini adalah **deliverable #1** sesuai [PRD](./PRD.md).  
Semua skenario di sini diimplementasi sebagai test case di `security/tests/`.  
Sumber kebenaran: [`SYNAPSE.md`](../SYNAPSE.md) section 2.5, 4.4, 4.5.

---

## Grup R — Rule Engine (SYNAPSE.md 4.4)

| ID | Tool | Ekspektasi | File |
|---|---|---|---|
| R1a | `db.run_migration` | `blast_radius=high`, `require_approval=True` | `test_rule_engine.py::TestDbRunMigration` |
| R1b | `db.run_migration` | `requires_approval=1` tersimpan di DB | `test_rule_engine.py::TestDbRunMigration` |
| R2a | `service.restart` | `blast_radius=medium`, `require_approval=False` | `test_rule_engine.py::TestServiceRestart` |
| R2b | `service.restart` | propose tidak set `requires_approval` | `test_rule_engine.py::TestServiceRestart` |
| R3 | `config.write` | `blast_radius=medium`, `require_approval=False` | `test_rule_engine.py::TestConfigWrite` |
| R4 | `file.delete` | `blast_radius=high`, `require_approval=True` | `test_rule_engine.py::TestFileDelete` |
| R5a | `unknown_tool` | fail-closed: `require_approval=True`, `blast_radius=unknown` | `test_rule_engine.py::TestFailClosed` |
| R5b | `totally.random.operation` | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R5c | `hack.db` | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R5d | `admin.override` | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R5e | `   ` (whitespace) | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R5f | `` (empty string) | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R9a | `DB.RUN_MIGRATION` (uppercase) | fail-closed — case-sensitive match | `test_rule_engine.py::TestFailClosed` |
| R9b | `Service.Restart` (mixed) | fail-closed | `test_rule_engine.py::TestFailClosed` |
| R10 | Unknown tool tanpa approval | `execute_operation` → `ok=False` | `test_rule_engine.py::TestFailClosed::test_unknown_tool_cannot_execute_without_approval` |
| R6a | `db.run_migration.v2` (prefix) | match rule `db.run_migration` | `test_rule_engine.py::TestPrefixMatch` |
| R6b | `service.restart.graceful` | match rule `service.restart` | `test_rule_engine.py::TestPrefixMatch` |

---

## Grup C — Conflict Detection (SYNAPSE.md 4.5)

| ID | Skenario | Ekspektasi | File |
|---|---|---|---|
| C1a | 2 op ke target sama (A pending, B baru) | B: `requires_approval=True` dipaksa | `test_conflict_detection.py::TestConflictForcesApproval` |
| C1b | 3 op ke target sama | jumlah konflik ≥ 2 | `test_conflict_detection.py::TestConflictForcesApproval` |
| C2 | Op ke target berbeda | tidak ada konflik | `test_conflict_detection.py::TestNoConflictDifferentTarget` |
| C3a | Op lama > CONFLICT_WINDOW menit | tidak dihitung konflik | `test_conflict_detection.py::TestConflictWindowExpiry` |
| C3b | Op dalam window − 1 menit | HARUS terdeteksi | `test_conflict_detection.py::TestConflictWindowExpiry` |
| C4 | `service.restart` (no-approval) + konflik | `requires_approval=True` paksa | `test_conflict_detection.py::TestConflictOverridesBlastRadius` |
| C5a | Op status `verified` dalam window | **tidak** trigger konflik | `test_conflict_detection.py::TestConflictStatusFilter` |
| C5b | Op status `failed` dalam window | tidak trigger konflik | `test_conflict_detection.py::TestConflictStatusFilter` |
| C5c | Op status `rolled_back` dalam window | tidak trigger konflik | `test_conflict_detection.py::TestConflictStatusFilter` |
| C5d | Status `pending/approved/executing/executed_unverified` | SEMUA trigger konflik | `test_conflict_detection.py::TestConflictStatusFilter` |
| C6 | 3 agent simultan ke target sama | semua setelah pertama harus conflict | `test_conflict_detection.py::TestMultiAgentConflict` |

---

## Grup RB — Rollback Verification (SYNAPSE.md 2.2)

| ID | Skenario | Ekspektasi | File |
|---|---|---|---|
| RB1 | Migration SQL invalid | status akhir `rolled_back` atau `failed` | `test_rollback_verification.py::TestDbMigrationRollback` |
| RB2 | Setelah rollback | tabel kontrak (nodes/edges/ops/approvals) masih ada | `test_rollback_verification.py::TestDbMigrationRollback` |
| RB3 | Execute tanpa approval | `ok=False`, status tetap `pending` | `test_rollback_verification.py::TestNoApprovalBlocked` |
| RB4 | Execute op yang di-deny | `ok=False`, status tetap `denied` | `test_rollback_verification.py::TestDeniedOperationBlocked` |
| RB5a | Execute selesai sukses | status ≠ `executing` | `test_rollback_verification.py::TestNoStuckExecuting` |
| RB5b | Execute selesai gagal | status ≠ `executing` | `test_rollback_verification.py::TestNoStuckExecuting` |
| RB6 | Rollback op kedua | op pertama yang `verified` tetap ada (bukan impossible state) | `test_rollback_verification.py::TestRollbackStateValidity` |
| RB7 | End-to-end propose→rollback | < 10 detik (SYNAPSE.md 2.7) | `test_rollback_verification.py::TestRollbackPerformance` |
| RB8 | Execute dua kali (replay) | panggilan kedua `ok=False` | `test_rollback_verification.py::TestDoubleExecuteGuard` |

---

## Grup A — Adversarial (SYNAPSE.md 4.5, PRD #3)

| ID | Serangan | Ekspektasi | File |
|---|---|---|---|
| A1 | Inject `requires_approval=0` langsung di DB | Jika bypass berhasil → **SECURITY FINDING** dilaporkan | `test_adversarial.py::TestDirectDbManipulation` |
| A2 | Approve `operation_id` palsu | `ok=False` | `test_adversarial.py::TestCrossOperationApproval` |
| A3 | Decision `APPROVED` (uppercase) | `ok=False` | `test_adversarial.py::TestInvalidDecision` |
| A4 | Decision string kosong / arbitrary | `ok=False` | `test_adversarial.py::TestInvalidDecision` |
| A5a | `tool_name="*"` | fail-closed | `test_adversarial.py::TestWildcardToolName` |
| A5b | SQL injection dalam `tool_name` | tidak crash, fail-closed | `test_adversarial.py::TestWildcardToolName` |
| A6 | `target=""` (kosong) | tidak crash | `test_adversarial.py::TestEmptyTarget` |
| A7 | Execute UUID palsu | `ok=False`, pesan error informatif | `test_adversarial.py::TestNonexistentOperation` |
| A8 | Approve dua kali (approved→denied) | decision terupdate, tidak duplikat | `test_adversarial.py::TestDoubleApprove` |

---

## Bug Findings Log

> Checkpoint jam 30 — semua temuan sudah dilaporkan ke backend team via GitHub Issues.

| Waktu | ID Bug | Skenario QC | Deskripsi | Issue | Severity | Status |
|---|---|---|---|---|---|---|
| Jam 30 | BUG-01 | A1 | `execute_operation` bypass approval via direct DB column manipulation — `requires_approval=0` di-inject langsung ke DB memungkinkan eksekusi tanpa approval | [#4](../issues/4) | 🔴 CRITICAL | Open |
| Jam 30 | BUG-02 | RB2 | `_do_rollback` selalu restore ke `DB_PATH` hardcoded, bukan ke target DB asli dari params — rollback ke DB yang salah | [#5](../issues/5) | 🔴 HIGH | Open |
| Jam 30 | BUG-03 | RB6 | Rollback `db.run_migration` restore seluruh file DB → operasi `verified` lain yang dibuat setelah snapshot ikut terhapus (historically impossible state, SYNAPSE.md 2.2) | [#6](../issues/6) | 🔴 HIGH | Open |
| Jam 30 | BUG-04 | RB1 | `_make_snapshot` dipanggil saat `propose` (terlalu awal, bukan saat execute) — jika file DB belum ada, snapshot gagal diam-diam dan rollback protection hilang tanpa warning | [#7](../issues/7) | 🟡 MEDIUM | Open |
| Jam 30 | BUG-05 | — | `main.py` duplicate class `ProposeOperationRequest` & `ApproveOperationRequest` — definisi kedua override pertama dengan skema berbeda, endpoint `/approve_operation` contract tidak konsisten | [#8](../issues/8) | 🟡 MEDIUM | Open |

---

## Cara Jalankan

```bash
# Dari root repo
pip install pytest
pytest security/tests/ -v

# Hanya rule engine
pytest security/tests/test_rule_engine.py -v

# Hanya adversarial
pytest security/tests/test_adversarial.py -v

# Dengan laporan durasi (untuk cek RB7)
pytest security/tests/test_rollback_verification.py -v --tb=short
```

## Metrics Target (SYNAPSE.md 2.7)

| Metric | Target | Test |
|---|---|---|
| Unknown tool → require_approval | 100% (zero exceptions) | R5a–R5f, R9a–R9b |
| Rollback time (injected failure) | < 10 detik | RB7 |
| Graph ingest < 30 detik | < 30 detik | *covered by QC-2/zuyss* |
