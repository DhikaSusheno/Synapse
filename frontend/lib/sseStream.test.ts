// lib/sseStream.test.ts
// Regresi BUG-38: 4 halaman = 1 koneksi /stream. Cek fanout, refcount, dan backoff.

import { test } from "node:test";
import assert from "node:assert/strict";
import { subscribeStream, openStreamCount } from "./sseStream.ts";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  close() { this.closed = true; }
  emit(data: string) { this.onmessage?.({ data }); }
  fail() { this.onerror?.(); }
  static get latest() { return FakeEventSource.instances[FakeEventSource.instances.length - 1]; }
}

// Node tidak punya global EventSource → pasang stub
(globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;

test("satu koneksi /stream di-share, fanout ke semua subscriber, backoff saat putus", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });

  const a: string[] = [];
  const b: string[] = [];
  const unA = subscribeStream((e) => a.push(e.event));
  const unB = subscribeStream((e) => b.push(e.event));

  // Dua subscriber (mis. SynapseGraph + CodeGraphPage) → tetap 1 koneksi
  assert.equal(FakeEventSource.instances.length, 1, "hanya boleh 1 EventSource dibuat");
  assert.equal(openStreamCount(), 1);

  FakeEventSource.latest.emit('{"event":"operation_proposed","data":{}}');
  assert.deepEqual(a, ["operation_proposed"]);
  assert.deepEqual(b, ["operation_proposed"], "kedua subscriber dapat event yang sama");

  // Event rusak tidak boleh melempar
  FakeEventSource.latest.emit("bukan json");
  assert.deepEqual(a, ["operation_proposed"]);

  // Putus → reconnect dijadwalkan dengan backoff, tanpa bikin koneksi paralel
  const first = FakeEventSource.latest;
  first.fail();
  assert.equal(first.closed, true, "koneksi yang error harus ditutup");
  assert.equal(FakeEventSource.instances.length, 1, "reconnect belum jalan sebelum timer");
  t.mock.timers.tick(1000);
  assert.equal(FakeEventSource.instances.length, 2, "reconnect setelah 1s");
  assert.equal(openStreamCount(), 1, "tetap satu koneksi");

  // Subscriber terakhir unsubscribe → koneksi ditutup
  unA();
  assert.equal(openStreamCount(), 1, "masih ada subscriber");
  unB();
  assert.equal(openStreamCount(), 0, "tanpa subscriber koneksi harus ditutup");
  assert.equal(FakeEventSource.latest.closed, true);
});
