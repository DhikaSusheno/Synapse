export type PlatformSettings = {
  platform_name: string;
  environment: string;
  log_level: string;
  dev_mode: boolean;
  workspace_path: string;
  default_branch: string;
  auto_migrate: boolean;
  conflict_detect: boolean;
  sse_enabled: boolean;
  approval_mode: string;
  conflict_auto_deny: boolean;
};

export type StorageOverview = {
  files: { label: string; file: string; size_bytes: number }[];
  tables: Record<string, string[]>;
};

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";
const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

let cache: PlatformSettings | null = null;
let storage: StorageOverview | null = null;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getSettings() {
  return cache;
}

export function getStorage() {
  return storage;
}

export async function refreshSettings(): Promise<void> {
  if (!USE_LIVE) {
    emit();
    return;
  }
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/settings`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      cache = data.settings as PlatformSettings;
      storage = data.storage as StorageOverview;
    } catch {
      cache = null;
      storage = null;
    } finally {
      inflight = null;
      emit();
    }
  })();
  return inflight;
}

async function post(path: string): Promise<PlatformSettings | null> {
  const res = await fetch(`${BACKEND_URL}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  cache = data.settings as PlatformSettings;
  storage = data.storage as StorageOverview;
  emit();
  return cache;
}

export function saveSettings(patch: Partial<PlatformSettings>) {
  return postWithBody("/settings", patch);
}

export function resetSettings() {
  return post("/settings/reset");
}

async function postWithBody(path: string, body: Partial<PlatformSettings>) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  cache = data.settings as PlatformSettings;
  storage = data.storage as StorageOverview;
  emit();
  return cache;
}

export type BrowseEntry = { name: string; type: "dir" | "file"; size: number | null };
export type BrowseResult = {
  path: string;
  absolute_path: string;
  parent: string | null;
  entries: BrowseEntry[];
};

export async function browsePath(path: string): Promise<BrowseResult> {
  const url = `${BACKEND_URL}/browse?path=${encodeURIComponent(path)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BrowseResult;
}

/**
 * Subfolder di `path` untuk dipilih sebagai target analisis.
 *
 * BEDA dengan browsePath() di atas: browsePath dipakai Cortex untuk membaca
 * ISI file dan terkurung di dalam repo/workspace. Yang ini untuk memilih
 * folder target, yang belum tentu berada di zona itu - memakai browsePath()
 * membuat "Telusuri folder..." hanya bisa membuka root repo, itu bug yang
 * dilaporkan user.
 *
 * Path kosong = folder home. Balikannya hanya berisi direktori, jadi
 * `entries.filter(e => e.type === "dir")` di frontend tetap benar (dan aman
 * kalau nanti backend menambah file).
 */
export async function browseTargetDirs(path = ""): Promise<BrowseResult> {
  const url = `${BACKEND_URL}/api/targets/browse?path=${encodeURIComponent(path)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BrowseResult;
}

/**
 * Path absolut anak dari `base` + `name`.
 *
 * compose browse yang sebelumnya menyambung `result.path` (path RELATIF ke
 * REPO_ROOT untuk /browse) dengan nama anak. Untuk /api/targets/browse,
 * `result.path` sudah absolut, dan menyambungnya relatif menghasilkan
 * "C:/Users/dhika/synapse-repoC:/Users/dhika/proyek" - path yang tidak pernah
 * ada. Karena kedua endpoint mengembalikan `absolute_path`, men composing dari
 * situ benar untuk keduanya.
 *
 * Separator memakai backslash di Windows dan slash di mana saja, jadi path
 * yang diketik user tetap bisa di-browse ulang.
 */
export function joinBrowsePath(base: string, name: string): string {
  const trimmed = base.replace(/[\\/]+$/, "");
  if (!trimmed) return name;
  return /^[A-Za-z]:[\\/]/.test(trimmed) ? `${trimmed}\\${name}` : `${trimmed}/${name}`;
}

export { BACKEND_URL, USE_LIVE };
