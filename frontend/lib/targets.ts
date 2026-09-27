// lib/targets.ts
// Client typed untuk target analisis: repository atau folder lokal yang
// menjadi sumber data Synapse (backend/main.py, tag "Targets").
//
// Kontrak yang dijaga file ini:
//  - Token API tidak pernah ada di browser. Semua fetch lewat route handler
//    app/backend/[...path] yang menyuntikkan SYNAPSE_API_TOKEN dari server.
//    Jangan tambahin localStorage atau X-Synapse-Token di sini.
//  - Ganti target berarti pindah file DB graph di server, jadi setelah
//    activate() caller WAJIB reload data graph (Overview, Cortex, CodeGraph)
//    - bukan cuma update daftar target.

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

export type TargetKind = "local" | "github";

export interface Target {
  id: string;
  kind: TargetKind;
  label: string;
  /** Folder lokal yang dianalisis. Untuk kind="github" ini hasil sync tarball. */
  path: string;
  /** "owner/repo" untuk kind="github", null untuk folder lokal. */
  source: string | null;
  branch: string | null;
  /**
   * False kalau folder-nya sudah hilang atau berada di luar area yang
   * diizinkan. Target seperti ini TIDAK bisa diaktifkan, tapi tetap
   * ditampilkan supaya user tahu itu targetnya, bukan sekadar(data hilang).
   */
  available: boolean;
  created_at?: string;
}

/** Ringkasan hasil ingest. Field-nya mengikuti stats dari engine.ingest_repository. */
export interface IngestSummary {
  ok: boolean;
  repo?: string;
  files?: number;
  symbols?: number;
  edges?: number;
  docs?: number;
  stale_removed?: number;
  error?: string;
  [key: string]: unknown;
}

export interface TargetListResponse {
  ok: boolean;
  /** Id target aktif, atau null kalau belum ada target. */
  active: string | null;
  target: Target | null;
  targets: Target[];
}

export interface TargetMutationResponse extends TargetListResponse {
  ingest?: IngestSummary | null;
}

export interface SyncResult {
  ok: boolean;
  source: string;
  branch: string;
  path: string;
  files: number;
  dirs: number;
  skipped: number;
}

export interface TargetSyncResponse extends TargetMutationResponse {
  sync?: SyncResult | null;
}

export class TargetApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "TargetApiError";
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
    // Proxy Next menuliskan pesan di key `error`, backend FastAPI di `detail`.
    // Baca keduanya, kalau tidak user melihat "HTTP 502" tanpa penjelasan.
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        detail = `${body.detail[0].loc?.join(".") ?? "body"}: ${body.detail[0].msg}`;
      } else if (typeof body?.error === "string") detail = body.error;
    } catch {
      // body bukan JSON; status saja yang bisa ditampilkan
    }
    throw new TargetApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// id target masuk ke path URL dan juga jadi nama file DB di server, jadi
// di-encode. Backend juga menolak id yang tidak cocok ^[a-z0-9][a-z0-9_-]*$.
const seg = (v: string) => encodeURIComponent(v);

export async function listTargets(): Promise<TargetListResponse> {
  const data = await api<TargetListResponse>("/api/targets");
  return { ...data, targets: data.targets ?? [], active: data.active ?? null };
}

export interface LocalTargetDraft {
  kind: "local";
  label: string;
  path: string;
  make_active?: boolean;
  ingest?: boolean;
}

export interface GitHubTargetDraft {
  kind: "github";
  /** "owner/repo". */
  source: string;
  branch?: string;
  label?: string;
  make_active?: boolean;
  ingest?: boolean;
}

export async function createLocalTarget(
  draft: LocalTargetDraft,
): Promise<TargetMutationResponse> {
  return api<TargetMutationResponse>("/api/targets", {
    method: "POST",
    body: JSON.stringify({
      kind: "local",
      label: draft.label,
      path: draft.path,
      make_active: draft.make_active ?? true,
      ingest: draft.ingest ?? true,
    }),
  });
}

/**
 * Unduh repo GitHub lalu jadikan target aktif. Backend yang melakukan sync,
 * ekstrak, dan ingest - browser tidak pernah menyentuh file system server
 * dan tidak pernah menerima token GitHub.
 */
export async function syncGitHubTarget(
  draft: GitHubTargetDraft,
): Promise<TargetSyncResponse> {
  return api<TargetSyncResponse>("/api/github/repos/sync", {
    method: "POST",
    body: JSON.stringify({
      source: draft.source,
      branch: draft.branch || "main",
      label: draft.label,
      make_active: draft.make_active ?? true,
      ingest: draft.ingest ?? true,
    }),
  });
}

export async function activateTarget(
  id: string,
  opts: { ingest?: boolean } = {},
): Promise<TargetMutationResponse> {
  return api<TargetMutationResponse>(`/api/targets/${seg(id)}/activate`, {
    method: "POST",
    body: JSON.stringify({ ingest: opts.ingest ?? true }),
  });
}

export async function renameTarget(
  id: string,
  patch: { label?: string; branch?: string },
): Promise<TargetMutationResponse> {
  return api<TargetMutationResponse>(`/api/targets/${seg(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function removeTarget(
  id: string,
  opts: { removeGraph?: boolean } = {},
): Promise<TargetListResponse> {
  const qs = opts.removeGraph ? "?remove_graph=true" : "";
  return api<TargetListResponse>(`/api/targets/${seg(id)}${qs}`, {
    method: "DELETE",
  });
}

// --- store: snapshot target + penanda "graph berganti" -------------------
//
// Berpindah target di backend MEMINDAHKAN file DB yang dibaca, jadi seluruh
// data graph di browser jadi basi: node, edge, ringkasan, health report.
// Halaman-halaman itu tidak tahu ada konsep target, jadi dua hal di sini
// yang mereka dengarkan lewat useSyncExternalStore:
//
//   1. snapshot target (label + path aktif) untuk ditampilkan
//   2. penanda perubahan, supaya useEffect pemanggil data graph jalan ulang
//
// Ini satu-satunya sumber target di browser. useTargets menulis ke sini, dan
// komponen mana pun membaca dari sini - bukan fetch sendiri, supaya Overview
// dan Cortex tidak bisa menampilkan target yang berbeda.

export interface TargetSnapshot {
  active: Target | null;
  targets: Target[];
}

const EMPTY_SNAPSHOT: TargetSnapshot = { active: null, targets: [] };

let snapshot: TargetSnapshot = EMPTY_SNAPSHOT;
let graphGeneration = 0;
const listeners = new Set<() => void>();

function emit() {
  graphGeneration += 1;
  listeners.forEach((fn) => {
    fn();
  });
}

/**
 * Selalu kembalikan objek yang sama antara pemanggilan, karena
 * useSyncExternalStore membandingkan dengan referensi (Object.is). Kalau
 * setiap call membuat objek baru, React menganggap store selalu berubah
 * dan masuk render loop.
 */
export function getTargetSnapshot(): TargetSnapshot {
  return snapshot;
}

export function getActiveTarget(): Target | null {
  return snapshot.active;
}

export function getGraphGeneration(): number {
  return graphGeneration;
}

export function subscribeTargets(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

// Alias yang lebih sempit, supaya kode yang cuma butuh target aktif tidak
// mengambil seluruh snapshot.
export const subscribeActiveTarget = subscribeTargets;

/**
 * Tulis snapshot baru dan beritahukan pendengar.
 *
 * Dipanggil setelah SETIAP baca atau mutasi target. Objek baru selalu dibuat
 * supaya useSyncExternalStore melihat perubahan lewat referensi.
 */
export function publishTargets(list: { active: string | null; targets: Target[] }): void {
  snapshot = {
    active: findActive(list),
    targets: list.targets ?? [],
  };
  emit();
}

// --- helper murni, supaya bisa diuji tanpa network -------------------------

/**
 * Slug untuk label, sama aturan dengan projects.slugify() di backend.
 * Dipakai untuk memberi id Ramah saat membuat target baru, supaya label
 * "My Repo" tidak jadi "my-repo" di server tapi "My Repo" di UI.
 */
export function slugify(text: string): string {
  return (
    text
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "target"
  );
}

/**
 * Validasi draft folder lokal sebelum request.
 *
 * Backend yang jadi penjaga terakhir (projects._registerable_dir), tapi
 * tiga aturan di sini bisa dicek lebih cepat dan pesannya lebih jelas:
 * path kosong, path root drive, dan label kosong.
 */
export function validateLocalDraft(draft: LocalTargetDraft): string[] {
  const problems: string[] = [];
  const path = draft.path.trim();
  if (!path) {
    problems.push("Path folder wajib diisi.");
  } else {
    const segments = path.split(/[\\/]+/).filter(Boolean);
    if (segments.length === 0) {
      problems.push("Path folder tidak valid.");
    }
  }
  if (!draft.label.trim()) {
    problems.push("Label target wajib diisi.");
  }
  return problems;
}

/**
 * Validasi draft repo GitHub. Format harus "owner/repo"; backend menolak
 * karakter lain karena nilainya jadi bagian dari path filesystem server.
 */
export function validateGitHubDraft(draft: GitHubTargetDraft): string[] {
  const problems: string[] = [];
  const source = draft.source.trim().replace(/^\/+|\/+$/g, "");
  const parts = source.split("/");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    problems.push("Format harus owner/repo, contoh: DhikaSusheno/Synapse");
  } else {
    const bad = /[^A-Za-z0-9._-]/;
    if (bad.test(parts[0]) || bad.test(parts[1])) {
      problems.push("Owner dan repo hanya boleh huruf, angka, titik, underscore, dan tanda hubung.");
    }
  }
  return problems;
}

/** Target aktif, atau null kalau belum ada / tidak ditemukan di daftar. */
export function findActive(
  list: Pick<TargetListResponse, "active" | "targets">,
): Target | null {
  if (!list.active) return null;
  for (const t of list.targets) {
    if (t.id === list.active) return t;
  }
  return null;
}

/**
 * Target yang bisa dipilih user: yang tersedia saja.
 * Target `available: false` akan gagal 409 saat diaktifkan, jadi offering
 * di sini berarti "tidak akan gagal dengan error yang tak terduga".
 */
export function selectableTargets(targets: readonly Target[]): Target[] {
  return targets.filter((t) => t.available);
}

/** Ringkasan singkat untuk ditampilkan, mis. "12 file, 87 simbol". */
export function summarizeIngest(ingest: IngestSummary | null | undefined): string {
  if (!ingest) return "";
  if (ingest.ok === false) return ingest.error || "Ingest gagal";
  const parts: string[] = [];
  if (typeof ingest.files === "number") parts.push(`${ingest.files} file`);
  if (typeof ingest.symbols === "number") parts.push(`${ingest.symbols} simbol`);
  if (typeof ingest.edges === "number") parts.push(`${ingest.edges} relasi`);
  return parts.join(", ");
}
