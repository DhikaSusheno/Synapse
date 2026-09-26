// lib/operations.test.ts — BUG-39: approve error tidak boleh disamarkan jadi sukses
import { test } from "node:test";
import assert from "node:assert/strict";
import { decideOperation } from "./operations.ts";

type Reply = { status: number; body: unknown };

function stubFetch(replies: Record<string, Reply>) {
  const calls: string[] = [];
  const real = globalThis.fetch;
  globalThis.fetch = (async (url: string) => {
    const key = String(url).split("/").pop()!;
    calls.push(key);
    const reply = replies[key];
    if (!reply) throw new Error(`stub tidak punya ${key}`);
    return {
      ok: reply.status >= 200 && reply.status < 300,
      json: async () => reply.body,
    } as Response;
  }) as typeof fetch;
  return {
    calls,
    restore: () => { globalThis.fetch = real; },
  };
}

const URL_BASE = "http://be";

test("BUG-39: approve ditolak -> status null, error tampil, execute TIDAK dipanggil", async () => {
  const s = stubFetch({
    approve_operation: { status: 400, body: { detail: "Operation tidak ditemukan" } },
  });
  try {
    const r = await decideOperation("op::x", "approved", URL_BASE);
    assert.equal(r.ok, false);
    assert.equal(r.status, null, "UI tidak boleh menampilkan status kalau approve gagal");
    assert.equal(r.error, "Operation tidak ditemukan");
    assert.deepEqual(s.calls, ["approve_operation"], "execute tidak boleh jalan");
  } finally { s.restore(); }
});

test("BUG-39: backend offline saat approve -> error, bukan approved palsu", async () => {
  const s = stubFetch({});
  try {
    const r = await decideOperation("op::x", "approved", URL_BASE);
    assert.equal(r.ok, false);
    assert.equal(r.status, null);
    assert.ok(r.error);
    assert.deepEqual(s.calls, ["approve_operation"], "hanya approve yang dicoba");
  } finally { s.restore(); }
});

test("deny sukses -> status denied dari backend, tanpa execute", async () => {
  const s = stubFetch({
    approve_operation: { status: 200, body: { ok: true, status: "denied", new_status: "denied" } },
  });
  try {
    const r = await decideOperation("op::x", "denied", URL_BASE);
    assert.equal(r.ok, true);
    assert.equal(r.status, "denied");
    assert.equal(r.error, null);
    assert.deepEqual(s.calls, ["approve_operation"]);
  } finally { s.restore(); }
});

test("approve ok -> execute jalan -> verified", async () => {
  const s = stubFetch({
    approve_operation: { status: 200, body: { ok: true, status: "approved" } },
    execute_operation: { status: 200, body: { ok: true, status: "verified" } },
  });
  try {
    const r = await decideOperation("op::x", "approved", URL_BASE);
    assert.equal(r.ok, true);
    assert.equal(r.status, "verified");
    assert.equal(r.error, null);
    assert.deepEqual(s.calls, ["approve_operation", "execute_operation"]);
  } finally { s.restore(); }
});

test("approve ok tapi execute ok:false -> status failed + error (tidakClaim sukses)", async () => {
  const s = stubFetch({
    approve_operation: { status: 200, body: { ok: true, status: "approved" } },
    execute_operation: { status: 200, body: { ok: false, error: "Butuh approval manusia" } },
  });
  try {
    const r = await decideOperation("op::x", "approved", URL_BASE);
    assert.equal(r.ok, false);
    assert.equal(r.status, "failed");
    assert.equal(r.error, "Butuh approval manusia");
  } finally { s.restore(); }
});

test("execute HTTP error -> status failed, bukan verified", async () => {
  const s = stubFetch({
    approve_operation: { status: 200, body: { ok: true, status: "approved" } },
    execute_operation: { status: 500, body: { detail: "boom" } },
  });
  try {
    const r = await decideOperation("op::x", "approved", URL_BASE);
    assert.equal(r.ok, false);
    assert.equal(r.status, "failed");
    assert.equal(r.error, "boom");
  } finally { s.restore(); }
});
