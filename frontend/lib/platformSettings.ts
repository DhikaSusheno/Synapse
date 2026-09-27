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

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
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

export { BACKEND_URL, USE_LIVE };
