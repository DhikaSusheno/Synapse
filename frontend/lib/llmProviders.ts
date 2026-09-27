// lib/llmProviders.ts
// Client typed untuk registry LLM provider (backend/main.py, tag "LLM").
//
// Token API tidak pernah ada di browser: route handler app/backend/[...path]
// menyuntikkan SYNAPSE_API_TOKEN dari sisi server, jadi setiap fetch di sini
// cukup same-origin tanpa header auth apa pun. Jangan tambahin
// localStorage token atau X-Synapse-Token di file ini - lib/backendUrl.test.ts
// dan-review sekalian kontrak itu.

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

// Tipe yang dikenali Synapse. BUKAN daftar tertutup: backend menerima tipe
// apa pun (lihat normalize_provider_type di main.py), jadi "groq",
// "lmstudio", "vllm", atau "internal-proxy" semuanya sah. Daftar ini hanya
// untuk (a) memberi base_url default di backend dan (b) mengisi dropdown.
//
// Konsekuensi: form harus bisa menerima teks bebas, bukan cuma <select>.
export const KNOWN_PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "ibm",
  "nvidia",
  "deepseek",
  "ollama",
  "openai-compatible",
] as const;

/** Nama tipe provider. Bebas, bukan salah satu dari KNOWN_PROVIDER_TYPES. */
export type ProviderType = string;

// Alias lama. Dipakai LLMProviderManager untuk iterasi dropdown; nama baru
// lebih jujur karena daftar ini tidak lagi lengkap.
export const PROVIDER_TYPES = KNOWN_PROVIDER_TYPES;

// Backend menolak DELETE untuk type di bawah dengan 403 (delete_llm_provider,
// "Cannot delete built-in provider"). UI harus menonaktifkan tombol hapus
// berdasarkan daftar yang sama supaya user tidak menunggu error yang sudah
// bisa diprediksi di client. Tipe custom SELALU boleh dihapus.
export const UNDELETABLE_TYPES: ReadonlySet<string> = new Set<string>([
  "openai",
  "anthropic",
  "ibm",
  "nvidia",
  "deepseek",
  "ollama",
]);

export function isDeletable(type: ProviderType): boolean {
  return !UNDELETABLE_TYPES.has(type);
}

// Base URL default per tipe yang dikenali. Harus sama dengan
// PROVIDER_BASE_URLS di backend/main.py. Tipe di luar daftar TIDAK punya
// default: backend akan menolak dengan 400 kalau base_url kosong, karena
// menebak URL OpenAI akan mengirim isi repo ke akun yang tidak diminta.
export const PROVIDER_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  nvidia: "https://integrate.api.nvidia.com/v1",
  deepseek: "https://api.deepseek.com/v1",
  ollama: "http://localhost:11434/v1",
  ibm: "https://us-south.ml.cloud.ibm.com/ml/v1",
};

/** True kalau tipe punya base_url default, jadi field boleh dikosongkan. */
export function hasDefaultBaseUrl(type: ProviderType): boolean {
  return Object.prototype.hasOwnProperty.call(PROVIDER_BASE_URLS, type);
}

// Saran model per tipe. Backend tidak menolak nama model di luar daftar ini -
// namespaced model lokal (mis. "llama3.1:8b", "qwen2.5-coder:14b") sah untuk
// Ollama, dan vendor baru sering punya nama sendiri. Daftar ini hanya untuk
// autocomplete, jadi input tetap harus bisa menerima teks bebas.
export const MODEL_SUGGESTIONS: Record<string, readonly string[]> = {
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3-mini"],
  anthropic: ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-3-5-haiku-latest"],
  ibm: ["ibm/granite-3-8b-instruct", "meta-llama/llama-3-3-70b-instruct"],
  nvidia: ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
  ollama: ["llama3.1", "qwen2.5-coder", "deepseek-r1", "gemma3"],
  "openai-compatible": ["gpt-4o-mini", "llama3.1", "qwen2.5-coder"],
};

/** Saran model untuk satu tipe. Selalu array, walau tipenya tidak dikenal. */
export function modelSuggestions(type: ProviderType): readonly string[] {
  return MODEL_SUGGESTIONS[type] ?? [];
}

export interface LLMProvider {
  id: string;
  name: string;
  type: ProviderType;
  base_url: string | null;
  models: string[];
  default_model: string;
  max_tokens: number;
  supports_tools: boolean;
  supports_vision: boolean;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ProviderDraft {
  name: string;
  type: ProviderType;
  base_url?: string | null;
  api_key?: string | null;
  models: string[];
  default_model?: string;
  max_tokens?: number;
  supports_tools?: boolean;
  supports_vision?: boolean;
  enabled?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    // FastAPI balas {"detail": "..."} atau {"detail": [{loc, msg}]} untuk 422.
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        detail = `${body.detail[0].loc?.join(".") ?? "body"}: ${body.detail[0].msg}`;
      }
    } catch {
      // body bukan JSON, pakai status saja
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// owner dan repo tetap di-encode per-segmen: nama repo GitHub boleh berisi
// karakter yang harus di-escape, dan segment "/" akan memecah path.
const seg = (v: string) => encodeURIComponent(v);

export async function listProviders(): Promise<LLMProvider[]> {
  const data = await api<{ ok: boolean; providers: LLMProvider[] }>("/api/llm/providers");
  return data.providers ?? [];
}

export async function createProvider(draft: ProviderDraft): Promise<string> {
  const data = await api<{ ok: boolean; id: string }>("/api/llm/providers", {
    method: "POST",
    body: JSON.stringify(draft),
  });
  return data.id;
}

export async function updateProvider(
  id: string,
  patch: Partial<ProviderDraft>,
): Promise<void> {
  await api<{ ok: boolean }>(`/api/llm/providers/${seg(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteProvider(id: string): Promise<void> {
  await api<{ ok: boolean }>(`/api/llm/providers/${seg(id)}`, { method: "DELETE" });
}

export async function listModels(
  id: string,
): Promise<{ models: string[]; defaultModel: string }> {
  const data = await api<{ ok: boolean; models: string[]; default: string }>(
    `/api/llm/providers/${seg(id)}/models`,
  );
  return { models: data.models ?? [], defaultModel: data.default ?? "" };
}

// --- helper model list, murni supaya bisa diuji tanpa network ---------------

/**
 * Tambah model ke daftar, buang duplikat dan entry kosong, dan jaga
 * default_model tetap menunjuk ke model yang benar-benar ada.
 *
 * Tanpa ini, menghapus model default lewat UI meninggalkan default_model
 * menggantung ke nama yang sudah dihapus, dan /api/llm/chat gagal dengan
 * "Provider not found or disabled"-looking error dari sisi provider.
 */
export function addModel(
  models: readonly string[],
  name: string,
): string[] {
  const trimmed = name.trim();
  if (!trimmed) return dedupe(models);
  return dedupe([...models, trimmed]);
}

export function removeModel(
  models: readonly string[],
  name: string,
): string[] {
  return dedupe(models.filter((m) => m !== name));
}

export function dedupe(models: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of models) {
    const trimmed = m.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out;
}

/**
 * Bersihkan default_model terhadap daftar model terbaru.
 * Kalau default hilang, jatuh ke model pertama; kalau daftar kosong, kosong.
 */
export function reconcileDefault(
  models: readonly string[],
  currentDefault: string,
): string {
  const list = dedupe(models);
  if (!list.length) return "";
  return list.includes(currentDefault) ? currentDefault : list[0];
}

/**
 * Backend membuat id dari "{type}:{name}", jadi dua provider beda tipe tapi
 * nama sama tetap bentrok di kolom PRIMARY KEY dan jawab 409. Lebih baik
 * dicegat sebelum request.
 */
export function makeProviderId(type: ProviderType, name: string): string {
  return `${type}:${name.trim()}`;
}

/** Tipe fallback kalau user mengosongkan field tipe. Satu-satunya tipe
 *  yang boleh tanpa base_url dan tanpa model bawaan, jadi form tetap bisa
 *  disimpan. */ 
const DEFAULT_PROVIDER_TYPE = "openai-compatible";

/**
 * Normalisasi tipe: lowercase, lalu coba beberapa bentuk sampai satu cocok
 * dengan daftar bawaan. WAJIB sama dengan normalize_provider_type() di
 * backend/main.py, karena makeProviderType di bawah menghitung id client-side
 * dan id itu harus sama persis dengan "{type}:{name}" yang dibuat server.
 *
 * Urutan kandidat penting. "Open AI" adalah cara orang mengetik nama itu
 * setiap hari, dan kalau spasinya diganti tanda hubung hasilnya "open-ai",
 * nama yang tidak ada di daftar bawaan. Akibatnya provider kehilangan
 * base_url default dan user dipaksa mengetik URL yang sebenarnya sudah kami
 * tahu benar, DAN id yang dibuat client beda dengan id dari server.
 *
 *     "  OpenAI "            -> "openai"           (cocok persis)
 *     "Open AI" / "open ai"  -> "openai"           (spasi dihapus, cocok)
 *     "open ai compatible"   -> "openai-compatible" (spasi -> dash)
 *     "vllm"                 -> "vllm"             (tidak dikenal, dipakai apa adanya)
 */
export function normalizeProviderType(raw: string): string {
  const text = (raw ?? "").trim().toLowerCase();
  if (!text) return DEFAULT_PROVIDER_TYPE;
  const squashed = text.replace(/\s+/g, "");
  const dashed = text.split(/\s+/).join("-");
  for (const candidate of [text, squashed, dashed, dashed.replace(/-/g, "_")]) {
    if (hasDefaultBaseUrl(candidate) || KNOWN_PROVIDER_TYPES.includes(candidate as never)) {
      return candidate;
    }
  }
  // Tipe custom: buang karakter yang akan merusak id dan base_url.
  const cleaned = dashed.replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || DEFAULT_PROVIDER_TYPE;
}

/**
 * Validasi draft sebelum dikirim. Backend sudah menolak tipe tanpa base_url
 * dengan 422, tapi errornya berupa jargon Pydantic; di sini pesannya
 * langsung dan bisa ditindaklanjuti user.
 *
 * Mengembalikan string[] yang kosong kalau draftnya sah.
 */
export function validateDraft(draft: ProviderDraft): string[] {
  const problems: string[] = [];
  if (!draft.name.trim()) {
    problems.push("Nama provider wajib diisi.");
  }
  const type = normalizeProviderType(draft.type);
  if (!type) {
    problems.push("Tipe provider wajib diisi.");
  } else if (!hasDefaultBaseUrl(type) && !(draft.base_url ?? "").trim()) {
    problems.push(
      `Tipe "${type}" bukan provider bawaan, jadi base_url wajib diisi. ` +
        `Synapse tidak menebak endpoint untuk tipe di luar daftar.`,
    );
  }
  if (draft.models.length === 0 && !(draft.default_model ?? "").trim()) {
    problems.push("Isi minimal satu model, atau set default model.");
  }
  return problems;
}
