// lib/derive.test.ts — run: node --test lib/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bucketActivity, buildFileTree, conflictCandidates, isOpen, mapPending,
  opSummary, parseTs, pct, relativeTime, rollbackStats, securityOverview,
  withConflicts, type LiveOp,
} from "./derive.ts";

const op = (over: Partial<LiveOp> = {}): LiveOp => ({
  id: "op::1", tool_name: "db.run_migration", params_json: "{}", target_node_id: "t::a",
  blast_radius: "high", status: "pending", requires_approval: 1,
  created_at: new Date().toISOString(), executed_at: null, verified_at: null,
  ...over,
});

test("isOpen hanya status aktif", () => {
  assert.equal(isOpen("pending"), true);
  assert.equal(isOpen("executing"), true);
  assert.equal(isOpen("verified"), false);
  assert.equal(isOpen("rolled_back"), false);
});

test("pct aman saat total nol", () => {
  assert.equal(pct(0, 0), 0);
  assert.equal(pct(1, 4), 25);
});

test("securityOverview menghitung status", () => {
  const o = securityOverview([
    op({ status: "verified" }), op({ status: "failed" }),
    op({ status: "rolled_back" }), op({ status: "denied" }),
    op({ status: "pending" }),
  ]);
  assert.equal(o.total_checks, 5);
  assert.equal(o.violations, 2);
  assert.equal(o.blocked_ops, 1);
  assert.equal(o.verified_ops, 1);
  assert.equal(o.is_healthy, true);
});

test("is_healthy false saat ada operasi executing", () => {
  assert.equal(securityOverview([op({ status: "executing" })]).is_healthy, false);
});

test("rollbackStats hanya menghitung yang terEksekusi", () => {
  const r = rollbackStats([
    op({ id: "op::v", status: "verified" }),
    op({ id: "op::r", status: "rolled_back" }),
    op({ id: "op::p", status: "pending" }),
  ]);
  assert.equal(r.total, 2);
  assert.equal(r.successful, 1);
  // recent mengikuti urutan /operations (created_at DESC dari backend)
  assert.deepEqual(r.recent.map((x) => x.opId), ["op::v", "op::r"]);
});

test("conflictCandidates hanya target dengan >1 op", () => {
  const c = conflictCandidates([
    op({ id: "op::1", target_node_id: "t::db" }),
    op({ id: "op::2", target_node_id: "t::db" }),
    op({ id: "op::3", target_node_id: "t::other" }),
    op({ id: "op::4", target_node_id: null }),
  ]);
  assert.equal(c.length, 1);
  assert.equal(c[0].target, "t::db");
  assert.deepEqual(c[0].conflictsWith, ["op::2"]);
});

test("buildFileTree memecah path dan dedup prefix", () => {
  const t = buildFileTree([
    { id: "1", name: "backend/main.py", type: "file" },
    { id: "2", name: "backend/cortex.py", type: "file" },
    { id: "3", name: "README.md", type: "doc" },
  ]);
  assert.deepEqual(t.map((n) => `${"  ".repeat(n.depth)}${n.type}:${n.name}`), [
    "dir:backend",
    "  file:cortex.py",
    "  file:main.py",
    "doc:README.md",
  ]);
});

test("buildFileTree strip prefix node id dari backend", () => {
  const t = buildFileTree([{ id: "file::app/models.py", name: "file::app/models.py", type: "file" }]);
  assert.deepEqual(t.map((n) => n.name), ["app", "models.py"]);
});

test("bucketActivity mengabaikan timestamp rusak", () => {
  const b = bucketActivity([op({ created_at: "bukan-tanggal" })], 4, 40_000);
  assert.equal(b.length, 4);
  assert.equal(b.reduce((s, x) => s + x.count, 0), 0);
});

test("bucketActivity menghitung op di dalam window", () => {
  const b = bucketActivity([op()], 10, 5 * 60 * 60 * 1000);
  assert.equal(b[b.length - 1].count, 1);
});

test("opSummary ambil sql, fallback target", () => {
  assert.equal(opSummary(op({ params_json: '{"sql":"ALTER TABLE x"}' })), "ALTER TABLE x");
  assert.equal(opSummary(op({ target_node_id: "t::z" })), "t::z");
  assert.equal(opSummary(op({ params_json: "bukan-json", target_node_id: null })), "db.run_migration");
});

test("relativeTime menangani input rusak", () => {
  assert.equal(relativeTime("bukan-tanggal"), "-");
  assert.match(relativeTime(new Date().toISOString()), /just now/);
});

// BUG-2: backend tulis UTC naive (tanpa "Z"), new Date() baca sebagai waktu lokal.
test("parseTs baca timestamp UTC naive sebagai UTC", () => {
  const naive = new Date().toISOString().slice(0, 19);           // "2026-09-26T15:50:00"
  assert.equal(parseTs(naive), parseTs(`${naive}Z`));
  assert.equal(parseTs("2026-09-26T15:50:00Z"), Date.parse("2026-09-26T15:50:00Z"));
  assert.equal(parseTs("2026-09-26T15:50:00+07:00"), Date.parse("2026-09-26T15:50:00+07:00"));
  assert.ok(Number.isNaN(parseTs("bukan-tanggal")));
  assert.ok(Number.isNaN(parseTs(null)));
});

test("bucketActivity menghitung op dengan timestamp UTC naive", () => {
  // Sebelum fix: op ini jatuh 7 jam di luar window 5 jam -> semua bucket 0.
  const naive = new Date(Date.now() - 60_000).toISOString().slice(0, 19);
  const b = bucketActivity([op({ created_at: naive })], 10, 5 * 60 * 60 * 1000);
  assert.equal(b[b.length - 1].count, 1);
});

test("relativeTime tidak geser untuk timestamp UTC naive", () => {
  const naive = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString().slice(0, 19);
  assert.equal(relativeTime(naive), "3 h ago");
});

// BUG-1: backend di Windows menyimpan path dengan backslash.
test("buildFileTree memecah path Windows (backslash)", () => {
  const t = buildFileTree([
    { id: "1", name: "backend\\main.py", type: "file" },
    { id: "2", name: "security\\tests\\conftest.py", type: "file" },
  ]);
  assert.deepEqual(t.map((n) => `${"  ".repeat(n.depth)}${n.type}:${n.name}`), [
    "dir:backend",
    "  file:main.py",
    "dir:security",
    "  dir:tests",
    "    file:conftest.py",
  ]);
});

// FE-2: pending kosong harus jadi list kosong, bukan data lama/mock yang nyangkut.
test("mapPending mengembalikan [] saat backend tidak punya pending", () => {
  assert.deepEqual(mapPending([]), []);
  assert.deepEqual(mapPending(undefined), []);
  assert.deepEqual(mapPending("bukan array"), []);
});

test("mapPending memetakan field backend dan fallback aman", () => {
  const [first] = mapPending([{ id: "op::1", tool_name: "db.run_migration", blast_radius: "high" }]);
  assert.equal(first.id, "op::1");
  assert.equal(first.params_json, "{}");
  assert.equal(first.target_node_id, null);
  assert.equal(first.status, "pending");
  assert.equal(first.requires_approval, 1);
  assert.equal(first.conflicts, undefined);
  assert.ok(first.created_at);
});

test("mapPending mempertahankan status denied (bukan jadi failed)", () => {
  const [op] = mapPending([{ id: "op::2", tool_name: "fs.write", status: "denied", conflicts: ["op::1"] }]);
  assert.equal(op.status, "denied");
  assert.deepEqual(op.conflicts, ["op::1"]);
});

// Backend tidak kirim kolom conflicts, jadi FE harus hitung dengan aturan yang sama
// dengan guardian._check_conflict: status aktif + window 10 menit.
test("withConflicts menandai operasi aktif yang berbagi target", () => {
  const ops = mapPending([
    { id: "op::1", target_node_id: "t::nodes" },
    { id: "op::2", target_node_id: "t::nodes" },
    { id: "op::3", target_node_id: "t::edges" },
    { id: "op::4", target_node_id: null },
  ]);
  const byId = Object.fromEntries(withConflicts(ops).map((o) => [o.id, o.conflicts]));
  assert.deepEqual(byId["op::1"], ["op::2"]);
  assert.deepEqual(byId["op::2"], ["op::1"]);
  assert.equal(byId["op::3"], undefined);
  assert.equal(byId["op::4"], undefined);
});

test("withConflicts mengabaikanPartner yang sudah selesai (verified)", () => {
  const ops = mapPending([
    { id: "op::verified", target_node_id: "t::nodes", status: "verified" },
    { id: "op::pending", target_node_id: "t::nodes", status: "pending" },
  ]);
  const byId = Object.fromEntries(withConflicts(ops).map((o) => [o.id, o.conflicts]));
  assert.equal(byId["op::pending"], undefined, "verified bukan konflik aktif");
});

test("withConflicts mengabaikan operasi di luar window 10 menit", () => {
  const old = new Date(Date.now() - 11 * 60 * 1000).toISOString();
  const ops = mapPending([
    { id: "op::lama", target_node_id: "t::nodes", created_at: old },
    { id: "op::baru", target_node_id: "t::nodes" },
  ]);
  const byId = Object.fromEntries(withConflicts(ops).map((o) => [o.id, o.conflicts]));
  assert.equal(byId["op::baru"], undefined);
  assert.equal(byId["op::lama"], undefined);
});

test("withConflicts tidak menimpa conflicts dari backend", () => {
  const [op] = withConflicts(mapPending([{ id: "op::1", target_node_id: "t::n", conflicts: ["op::be"] }]));
  assert.deepEqual(op.conflicts, ["op::be"]);
});
