// lib/llmProviders.test.ts
// node --test "lib/*.test.ts"
//
// Helper registry LLM provider murni. Yang diuji di sini adalah invariant yang
// kalau bocor baru ketahuan saat user sudah menyimpan konfigurasi salah:
//  1. default_model harus selalu menunjuk model yang ada di daftar.
//  2. normalizeProviderType() client harus sama dengan backend, karena id
//     provider dihitung client-side (makeProviderId) dan id itu jadi PRIMARY KEY
//     di server. Beda satu karakter = provider tidak pernah ditemukan.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  addModel,
  dedupe,
  hasDefaultBaseUrl,
  isDeletable,
  KNOWN_PROVIDER_TYPES,
  makeProviderId,
  modelSuggestions,
  MODEL_SUGGESTIONS,
  normalizeProviderType,
  PROVIDER_BASE_URLS,
  PROVIDER_TYPES,
  reconcileDefault,
  removeModel,
  UNDELETABLE_TYPES,
  validateDraft,
  type ProviderType,
} from "./llmProviders.ts";

test("PROVIDER_TYPES masih memuat semua tipe bawaan backend", () => {
  // Alias lama. Backend menambah tipe baru, daftar ini harus menyusul supaya
  // datalist isi form punya opsi itu - meskipun mengetik bebas tetap sah.
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
  assert.deepEqual([...PROVIDER_TYPES], [...KNOWN_PROVIDER_TYPES]);
});

test("daftar tipe BUKAN daftar tertutup - tipe bebas harus bisa lolos", () => {
  // Ini inti fitur "endpoint umum": backend menerima tipe apa pun. Kalau
  // suatu saat daftar ini dipakai sebagai validator, "vllm" akan ditolak.
  for (const bebas of ["vllm", "groq", "lmstudio", "internal-proxy"]) {
    assert.equal(normalizeProviderType(bebas), bebas);
  }
});

test("isDeletable mencerminkan blokir 403 di delete_llm_provider", () => {
  // backend/main.py delete_llm_provider menolak 403 untuk type bawaan.
  for (const type of ["openai", "anthropic", "ibm", "nvidia", "deepseek", "ollama"] as const) {
    assert.equal(isDeletable(type), false, `${type} diblokir backend, jangan minta DELETE`);
  }
  assert.equal(isDeletable("openai-compatible"), true);
  // Tipe custom harus bisa dihapus, kalau tidak registry hanya bisa bertambah.
  for (const custom of ["vllm", "groq", "lmstudio"]) {
    assert.equal(isDeletable(custom), true, `${custom} tidak ada di backend, harus bisa dihapus`);
  }
  assert.equal(UNDELETABLE_TYPES.has("openai-compatible"), false);
});

test("tiap tipe punya saran model", () => {
  for (const type of KNOWN_PROVIDER_TYPES) {
    assert.ok(
      MODEL_SUGGESTIONS[type].length > 0,
      `${type} tidak punya saran model, dropdown autocomplete jadi kosong`,
    );
  }
});

test("modelSuggestions selalu array walau tipe tidak dikenal", () => {
  // Versi lama memakai MODEL_SUGGESTIONS[type].length, yang meledak jadi
  // TypeError saat user mengetik tipe custom. Input form tidak boleh crash
  // karena teks yang diketik user.
  assert.deepEqual(modelSuggestions("vllm"), []);
  assert.deepEqual(modelSuggestions(""), []);
  assert.ok(modelSuggestions("ollama").length > 0);
  // Saran model tidak boleh mencuri atau mengubah nama tipe.
  assert.deepEqual([...modelSuggestions("ollama")], [...MODEL_SUGGESTIONS.ollama]);
});

test("hasDefaultBaseUrl hanya true untuk tipe ber-URL-bawaan", () => {
  assert.equal(hasDefaultBaseUrl("openai"), true);
  assert.equal(hasDefaultBaseUrl("ollama"), true);
  // openai-compatible sengaja TIDAK punya default: menebak URL OpenAI akan
  // mengirim isi repo ke akun yang tidak diminta.
  assert.equal(hasDefaultBaseUrl("openai-compatible"), false);
  assert.equal(hasDefaultBaseUrl("vllm"), false);
  // Nama bawaan warisan prototipe (constructor, toString) tidak boleh dianggap
  // tipe yang punya default.
  assert.equal(hasDefaultBaseUrl("constructor"), false);
  assert.equal(hasDefaultBaseUrl("toString"), false);
  assert.equal(hasDefaultBaseUrl("__proto__"), false);
});

test("normalisasi replicate persis normalize_provider_type di backend", () => {
  // Tabel ini disalin dari docstring backend. Kalau backend berubah, tabel ini
  // yang harus ikut - dan ituquetteExactly kenapa test-nya ada.
  const cases: [string, string][] = [
    ["openai", "openai"],
    ["  OpenAI ", "openai"],
    ["OpenAI", "openai"],
    ["Open AI", "openai"],
    ["open ai", "openai"],
    ["Anthropic", "anthropic"],
    // "openai compatible" (tanpa spasi di tengah) yang menghasilkan
    // "openai-compatible". "open ai compatible" TIDAK bisa sampai ke sana:
    // squashed-nya "openaicompatible" dan dashed-nya "open-ai-compatible",
    // keduanya tidak ada di daftar bawaan, jadi jatuh ke pembersihan.
    ["openai compatible", "openai-compatible"],
    ["open ai compatible", "open-ai-compatible"],
    ["OpenAI Compatible", "openai-compatible"],
    ["Ollama", "ollama"],
    ["vllm", "vllm"],
    ["LM Studio", "lm-studio"],
    ["internal-proxy", "internal-proxy"],
  ];
  for (const [raw, expected] of cases) {
    assert.equal(normalizeProviderType(raw), expected, `"${raw}" harus jadi "${expected}"`);
  }
});

test('"Open AI" jadi "openai", bukan "open-ai" yang kehilangan base_url', () => {
  // Bug yang diperbaiki: versi lama hanya mengganti spasi dengan tanda hubung,
  // jadi "Open AI" -> "open-ai". Tipe itu tidak ada di PROVIDER_BASE_URLS,
  // jadi form menuntut base_url padahal URL-nya sudah kami tahu, DAN id yang
  // dibuat client ("open-ai:team") beda dari id server ("openai:team").
  const t = normalizeProviderType(" Open AI ");
  assert.equal(t, "openai");
  assert.equal(hasDefaultBaseUrl(t), true, "tipe ini harus punya base_url default");
  assert.equal(makeProviderId(t, "team"), "openai:team");
});

test("kandidat yang cocok lebih dulu menang, bukan bentuk paling kasar", () => {
  // "deep seek" squashed-nya "deepseek" (cocok), dashed-nya "deep-seek" (tidak).
  assert.equal(hasDefaultBaseUrl("deep-seek"), false);
  assert.equal(normalizeProviderType("deep seek"), "deepseek");
  // "nvidia nim" tidak cocok di bentuk mana pun, jadi dipakai apa adanya
  // setelah dibersihkan - tidak diam-diam jadi tipe bawaan yang salah.
  assert.equal(normalizeProviderType("nvidia nim"), "nvidia-nim");
});

test("tipe custom dibersihkan supaya id dan base_url tidak rusak", () => {
  // Karakter yang tidak boleh di path/URL/id. Kalau lolos, backend balas 422
  // dengan pesan Pydantic yang tidak jelas.
  assert.equal(normalizeProviderType("My Provider!"), "my-provider");
  assert.equal(normalizeProviderType("  vllm  "), "vllm");
  assert.equal(normalizeProviderType("a//b"), "a-b");
  assert.equal(normalizeProviderType("qwen.coder"), "qwen.coder", "titik sah untuk nama model");
  // Garis hubung di ujung dibuang supaya id tidak jadi "-foo:-bar".
  assert.equal(normalizeProviderType("---"), "openai-compatible");
  assert.equal(normalizeProviderType("   "), "openai-compatible");
  assert.equal(normalizeProviderType(""), "openai-compatible");
});

test("normalisasi idempoten: jalankan dua kali hasilnya sama", () => {
  // Dipanggil ulang di validateDraft lalu di makeProviderId. Kalau tidak
  // idempoten, id yang sampai ke server beda dari yang divalidasi.
  for (const raw of ["Open AI", "open ai compatible", "vllm", "My Provider!"]) {
    const once = normalizeProviderType(raw);
    assert.equal(normalizeProviderType(once), once, `"${raw}" tidak idempoten`);
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
  // backend: provider_id = f"{normalize(req.type)}:{req.name.strip()}"
  assert.equal(makeProviderId("openai", "team"), "openai:team");
  assert.equal(makeProviderId("ollama", "  lokal  "), "ollama:lokal");
  // Nama boleh berisi spasi dan tanda baca; yang di-normalkan hanya tipe.
  assert.equal(makeProviderId("vllm", "Qwen Team (internal)"), "vllm:Qwen Team (internal)");
});

test("validateDraft meloloskan draft tipe bawaan tanpa base_url", () => {
  const problems = validateDraft({
    name: "Team",
    type: "openai",
    models: ["gpt-4o"],
    default_model: "gpt-4o",
  });
  assert.deepEqual(problems, [], `harusnya sah, tapi: ${problems.join(" | ")}`);
});

test("validateDraft menuntut base_url untuk tipe custom", () => {
  // Kalau base_url kosong, backend balas 400 karena tidak mau menebak endpoint
  // tipe di luar daftar. Jadi ini bukan sekadar mezmur strictness.
  const problems = validateDraft({
    name: "Internal",
    type: "vllm",
    models: ["qwen2.5-coder"],
    default_model: "qwen2.5-coder",
  });
  assert.equal(problems.length, 1);
  assert.match(problems[0], /base_url wajib diisi/);
  assert.match(problems[0], /vllm/, "pesan harus menyebut tipenya, user bisa-action");
});

test("validateDraft meloloskan tipe custom yang base_url-nya diisi", () => {
  const problems = validateDraft({
    name: "Internal",
    type: "vllm",
    base_url: "http://10.0.0.5:8000/v1",
    models: ["qwen2.5-coder"],
    default_model: "qwen2.5-coder",
  });
  assert.deepEqual(problems, []);
});

test("validateDraft menolak draft kosong dan menumpuk semua masalah", () => {
  const problems = validateDraft({ name: "  ", type: "", models: [] });
  assert.equal(problems.length, 3, `harusnya 3 masalah, dapat: ${problems.join(" | ")}`);
  assert.ok(problems.some((p) => /Nama provider/.test(p)));
  assert.ok(problems.some((p) => /base_url wajib/.test(p)));
  assert.ok(problems.some((p) => /minimal satu model/.test(p)));
});

test("validateDraft memakai tipe ternormalkan, bukan input mentah", () => {
  // validateDraft("Open AI") harus TIDAK menuntut base_url, karena
  // hasDefaultBaseUrl("Open AI") false sedangkan hasDefaultBaseUrl("openai")
  // true. Kalau yang dipakai input mentah, form akan salah validasi.
  const problems = validateDraft({
    name: "Team",
    type: " Open AI ",
    models: ["gpt-4o"],
    default_model: "gpt-4o",
  });
  assert.deepEqual(problems, [], `harusnya sah, tapi: ${problems.join(" | ")}`);
});

test("validateDraft menerima model di default_model saja", () => {
  // Model bisa diisi lewat field default tanpa masuk daftar; LLMProviderManager
  // menyusun ulang daftar dari situ. Menolaknya akan memblokir draft yang sah.
  const problems = validateDraft({
    name: "Team",
    type: "openai",
    models: [],
    default_model: "gpt-4o",
  });
  assert.deepEqual(problems, []);
});

test("PROVIDER_BASE_URLS tidak punya slot prototipe yang bisa dikira tipe", () => {
  for (const key of Object.keys(PROVIDER_BASE_URLS)) {
    assert.match(key, /^[a-z0-9._-]+$/, `key "${key}" akan dipakai sebagai id provider`);
  }
});
