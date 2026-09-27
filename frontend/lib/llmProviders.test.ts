// lib/llmProviders.test.ts
// node --test "lib/*.test.ts"
//
// Helper registry LLM provider murni. Yang diuji di sini adalah invariant yang
// kalau bocor baru ketahuan saat user sudah menyimpan konfigurasi salah:
// default_model harus selalu menunjuk model yang ada di daftar.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  addModel,
  dedupe,
  isDeletable,
  makeProviderId,
  MODEL_SUGGESTIONS,
  PROVIDER_TYPES,
  reconcileDefault,
  removeModel,
  type ProviderType,
} from "./llmProviders.ts";

test("PROVIDER_TYPES sama dengan Literal backend", () => {
  // Kalau backend menambah tipe baru, daftar ini harus menyusul, kalau tidak
  // user tidak bisa memilih tipe itu di UI.
  const expected: ProviderType[] = [
    "openai",
    "anthropic",
    "ibm",
    "nvidia",
    "deepseek",
    "ollama",
    "openai-compatible",
  ];
  assert.deepEqual([...PROVIDER_TYPES], expected);
});

test("isDeletable mencerminkan blokir 403 di delete_llm_provider", () => {
  // backend/main.py delete_llm_provider menolak 403 untuk type bawaan.
  for (const type of ["openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama"] as const) {
    assert.equal(isDeletable(type), false, `${type} diblokir backend, jangan minta DELETE`);
  }
  assert.equal(isDeletable("openai-compatible"), true);
});

test("tiap tipe punya saran model", () => {
  for (const type of PROVIDER_TYPES) {
    assert.ok(
      MODEL_SUGGESTIONS[type].length > 0,
      `${type} tidak punya saran model, dropdown autocomplete jadi kosong`,
    );
  }
});

test("addModel menormalkan input dan buang duplikat", () => {
  assert.deepEqual(addModel(["gpt-4o"], "gpt-4o-mini"), ["gpt-4o", "gpt-4o-mini"]);
  assert.deepEqual(addModel(["gpt-4o"], "  gpt-4o  "), ["gpt-4o"]);
  assert.deepEqual(addModel(["a", "a"], "A"), ["a", "A"], "beda kapital = model beda");
  assert.deepEqual(addModel(["a"], "   "), ["a"], "spasi doang bukan model");
});

test("removeModel membuang semua kemunculan", () => {
  assert.deepEqual(removeModel(["a", "b", "a"], "a"), ["b"]);
  assert.deepEqual(removeModel(["a"], "zzz"), ["a"], "hapus yang tidak ada = no-op");
});

test("dedupe mempertahankan urutan pertama", () => {
  assert.deepEqual(dedupe(["b", "a", "b", "  c  ", ""]), ["b", "a", "c"]);
});

test("reconcileDefault menjaga default yang masih ada", () => {
  assert.equal(reconcileDefault(["a", "b"], "b"), "b");
  assert.equal(reconcileDefault(["a", "b"], "a"), "a");
});

test("reconcileDefault overhaul default yang sudah dihapus", () => {
  // Ini inti dari test: user hapus model yang jadi default, lalu buka panel
  // LLMChat. Kalau default menggantung, chat gagal dengan error provider.
  assert.equal(reconcileDefault(["b", "c"], "a"), "b");
  assert.equal(reconcileDefault([], "a"), "");
  assert.equal(reconcileDefault(["  ", ""], "a"), "");
});

test("makeProviderId mencerminkan id yang dibuat backend", () => {
  // backend: provider_id = f"{req.type}:{req.name}"
  assert.equal(makeProviderId("openai", "team"), "openai:team");
  assert.equal(makeProviderId("ollama", "  lokal  "), "ollama:lokal");
});
