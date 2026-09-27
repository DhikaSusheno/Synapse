// lib/coerce.test.ts
// node --test "lib/*.test.ts"

import { test } from "node:test";
import assert from "node:assert/strict";
import { num, arr, str } from "./coerce.ts";

test("num: number finite diteruskan apa adanya", () => {
  assert.equal(num(0), 0);
  assert.equal(num(42), 42);
  assert.equal(num(-3.5), -3.5);
});

test("num: string numerik diterima (JSON dari backend kadang string)", () => {
  assert.equal(num("7"), 7);
  assert.equal(num("0.5"), 0.5);
});

test("num: undefined / null / NaN -> 0, tidak melempar", () => {
  assert.equal(num(undefined), 0);
  assert.equal(num(null), 0);
  assert.equal(num(NaN), 0);
  assert.doesNotThrow(() => num(undefined).toFixed(1));
});

test("num: Infinity -> 0, bukan string 'Infinity' di UI", () => {
  assert.equal(num(Infinity), 0);
  assert.equal(num(-Infinity), 0);
});

test("num: string non-numerik -> 0", () => {
  assert.equal(num("abc"), 0);
  assert.equal(num(""), 0);
  assert.equal(num("   "), 0);
});

test("num: boolean dan object -> 0, bukan 1/NaN", () => {
  assert.equal(num(true), 0);
  assert.equal(num({}), 0);
  assert.equal(num([]), 0);
});

test("num: fallback dipakai untuk nilai tidak valid", () => {
  assert.equal(num(undefined, -1), -1);
  assert.equal(num("abc", 99), 99);
});

test("arr: array diteruskan, non-array -> kosong", () => {
  assert.deepEqual(arr([1, 2]), [1, 2]);
  assert.deepEqual(arr([]), []);
  assert.deepEqual(arr(undefined), []);
  assert.deepEqual(arr(null), []);
  assert.deepEqual(arr("bukan array"), []);
  assert.deepEqual(arr({ length: 2 }), []);
});

test("arr: hasilnya selalu iterable, .map tidak melempar", () => {
  const r = arr<string>(undefined);
  assert.doesNotThrow(() => r.map((x) => x.toUpperCase()));
  assert.equal(r.length, 0);
});

test("str: string diteruskan, non-string -> fallback", () => {
  assert.equal(str("pass"), "pass");
  assert.equal(str(undefined), "");
  assert.equal(str(null), "");
  assert.equal(str(42), "");
  assert.equal(str(undefined, "unknown"), "unknown");
});

test("str: hasil selalu punya .toUpperCase", () => {
  assert.doesNotThrow(() => str(undefined).toUpperCase());
  assert.equal(str(undefined).toUpperCase(), "");
});
