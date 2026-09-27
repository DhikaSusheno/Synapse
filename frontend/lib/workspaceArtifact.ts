// lib/workspaceArtifact.ts
// Artefak kerja yang dipilih di tab GitHub / Folder Lokal, lalu dipakai Cortex
// untuk review.
//
// Kenapa store module-level dan bukan props: pengambilnya ada di halaman
// berbeda (Settings choosing, CortexPage memakai). Pola yang sama sudah dipakai
// lib/platformSettings.ts - cache modul + subscribe - supaya tidak perlu provider
// Context untuk satu nilai.
//
// Isinya TIDAK dikirim ke mana pun sampai user menekan tombol review di Cortex.
// Untuk folder lokal ini penting: isi file dibaca di browser dan tidak pernah
// lewat backend kecuali user eksplisit mengirimkannya.

export type ArtifactSource = "github" | "local";

export interface WorkspaceArtifact {
  /** Penanda yang dibaca user, mis. "owner/repo@main/frontend/app/page.tsx". */
  label: string;
  content: string;
  source: ArtifactSource;
  /** Unix ms, supaya panel bisa menampilkan "dari X" dan membedakan overwrite. */
  at: number;
}

let current: WorkspaceArtifact | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

export function getArtifact(): WorkspaceArtifact | null {
  return current;
}

export function setArtifact(artifact: WorkspaceArtifact | null) {
  current = artifact;
  emit();
}

export function clearArtifact() {
  setArtifact(null);
}

export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * Batas aman untuk textarea dan untuk payload review.
 * File besar membuat /review_artifact lambat atau mentok, jadi potong di awal
 * dengan penanda yang jelas - bukan diam-diam, supaya user tahu isinya tidak
 * lengkap.
 */
export const ARTIFACT_MAX_CHARS = 200_000;

export function clampArtifact(content: string): { text: string; truncated: boolean } {
  if (content.length <= ARTIFACT_MAX_CHARS) {
    return { text: content, truncated: false };
  }
  return {
    text: `${content.slice(0, ARTIFACT_MAX_CHARS)}\n\n... [dipotong di ${ARTIFACT_MAX_CHARS} karakter]`,
    truncated: true,
  };
}
