// lib/llmProviders.ts
// Client typed untuk registry LLM provider (backend/main.py, tag "LLM").
//
// Token API tidak pernah ada di browser: route handler app/backend/[...path]
// menyuntikkan SYNAPSE_API_TOKEN dari sisi server, jadi setiap fetch di sini
// cukup same-origin tanpa header auth apa pun. Jangan tambahin
// localStorage token atau X-Synapse-Token di file ini - lib/backendUrl.test.ts
// dan-review sekalian kontrak itu.

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

// Harus sama persis dengan Literal di LLMProviderCreate / LLMProviderUpdate
// (backend/main.py). Kirim nilai di luar daftar ini dan FastAPI 422.
export const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "ibm",
  "nvidia",
  "deepseek",
  "ollama",
  "openai-compatible",
] as const;

export type ProviderType = (typeof PROVIDER_TYPES)[number];

// Backend menolak DELETE untuk type di bawah dengan 403 (delete_llm_provider,
// "Cannot delete built-in provider"). UI harus menonaktifkan tombol hapus
// berdasarkan daftar yang sama supaya user tidak menunggu error yang sudah
// bisa diprediksi di client.
export const UNDELETABLE_TYPES: ReadonlySet<ProviderType> = new Set<ProviderType>([
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

// Saran model per tipe. Backend tidak menolak nama model di luar daftar ini -
// namespaced model lokal (mis. "llama3.1:8b", "qwen2.5-coder:14b") sah untuk
// Ollama, dan vendor barurels cepat. Daftar ini hanya untuk autocomplete, jadi
// input tetap harus bisa menerima teks bebas.
export const MODEL_SUGGESTIONS: Record<ProviderType, readonly string[]> = {
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3-mini"],
  anthropic: ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-3-5-haiku-latest"],
  ibm: ["ibm/granite-3-8b-instruct", "meta-llama/llama-3-3-70b-instruct"],
  nvidia: ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
  ollama: ["llama3.1", "qwen2.5-coder", "deepseek-r1", "gemma3"],
  "openai-compatible": ["gpt-4o-mini", "llama3.1", "qwen2.5-coder"],
};

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
