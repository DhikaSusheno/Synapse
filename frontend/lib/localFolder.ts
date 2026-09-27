// lib/localFolder.ts
// Integrasi folder lokal lewat File System Access API.
//
// Semua file dibaca di browser, di mesin user sendiri. Tidak ada request ke
// backend, jadi tidak ada token yang berpindah tangan - dan isi folder pun
// tidak terkirim ke mana pun sampai user sendiri yang menekan tombol kirim.
//
// Batasan yang tidak dihindari: handle hanya hidup selama tab terbuka. Reload
// menghapus handle, jadi user harus memilih folder ulang. Menyimpan handle ke
// IndexedDB dan meminta izin ulang tiap_load adalah pekerjaan sendiri; sampai
// itu ada, pilih ulang adalah perilaku yang jujur.

import { buildTreeFromPaths, type FileTreeNode } from "./fileTree.ts";

export interface LocalFile {
  /** Path relatif terhadap folder yang dipilih, pemisah "/". */
  path: string;
  handle: FileSystemFileHandle;
  size: number;
}

export interface LocalTree {
  nodes: FileTreeNode[];
  /** Peta path -> handle, supaya klik file bisa langsung dibaca. */
  byPath: Map<string, LocalFile>;
}

// Folder yang tidak pernah berguna ditampilkan dan hanya mengikis ribuan file
// tanpa akhir. Default ini yang membuat picker bisa dipakai pada project nyata
// (yang selalu punya node_modules) tanpa membekukan tab.
export const DEFAULT_IGNORED_DIRS: ReadonlySet<string> = new Set([
  "node_modules",
  ".git",
  ".next",
  ".nuxt",
  "dist",
  "build",
  "out",
  "coverage",
  "__pycache__",
  ".venv",
  "venv",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".tox",
  "target",
  ".gradle",
  ".idea",
  ".vscode",
  ".cache",
]);

export const DEFAULT_MAX_FILES = 5000;
export const DEFAULT_MAX_DEPTH = 8;

/** showDirectoryPicker belum masuk lib.dom dan hanya ada di Chromium. */
export function isFolderAccessSupported(): boolean {
  return typeof window !== "undefined" && "showDirectoryPicker" in window;
}

interface PickerWindow {
  showDirectoryPicker?: (options?: {
    mode?: "read" | "readwrite";
    id?: string;
    startIn?: string;
  }) => Promise<FileSystemDirectoryHandle>;
}

/**
 * Buka dialog pilih folder. Return null kalau user membatalkan (AbortError)
 * jadi pemanggil tidak salah mengira gagal.
 */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle | null> {
  if (!isFolderAccessSupported()) {
    throw new Error(
      "Browser ini belum mendukung File System Access API. Pakai Chrome, Edge, atau Opera.",
    );
  }
  const picker = (window as unknown as PickerWindow).showDirectoryPicker;
  if (!picker) throw new Error("showDirectoryPicker tidak tersedia di window ini.");
  try {
    return await picker({ mode: "read", id: "synapse-workspace" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return null;
    throw err;
  }
}

export interface WalkOptions {
  ignoredDirs?: ReadonlySet<string>;
  maxFiles?: number;
  maxDepth?: number;
  signal?: { aborted: boolean };
}

/**
 * Jalan seluruh subtree, kembalikan daftar file datar.
 *
 * Berhenti di maxFiles dan melapor lewat `truncated` supaya UI bisa
 * truthfully menampilkan "menampilkan 5000 file pertama", bukan membuat user
// mengira foldernya cuma berisi segitu.
 */
export async function walkDirectory(
  root: FileSystemDirectoryHandle,
  options: WalkOptions = {},
): Promise<{ files: LocalFile[]; truncated: boolean }> {
  const ignored = options.ignoredDirs ?? DEFAULT_IGNORED_DIRS;
  const maxFiles = options.maxFiles ?? DEFAULT_MAX_FILES;
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH;

  const files: LocalFile[] = [];
  let truncated = false;

  async function visit(dir: FileSystemDirectoryHandle, prefix: string, depth: number) {
    if (truncated) return;
    if (depth > maxDepth) {
      truncated = true;
      return;
    }
    // values() butuh dom.asynciterable, sudah masuk tsconfig.
    for await (const entry of dir.values()) {
      if (truncated) return;
      if (options.signal?.aborted) {
        truncated = true;
        return;
      }
      const path = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.kind === "directory") {
        if (ignored.has(entry.name)) continue;
        await visit(entry as FileSystemDirectoryHandle, path, depth + 1);
      } else {
        if (files.length >= maxFiles) {
          truncated = true;
          return;
        }
        const handle = entry as FileSystemFileHandle;
        // size dibaca best-effort: beberapa browser tidak memberi size sebelum
        // file benar-benar dibuka, dan itu bukan alasan gagal listing.
        let size = 0;
        try {
          size = (await handle.getFile()).size;
        } catch {
          size = 0;
        }
        files.push({ path, handle, size });
      }
    }
  }

  await visit(root, "", 1);
  files.sort((a, b) => a.path.localeCompare(b.path));
  return { files, truncated };
}

export function buildLocalTree(files: readonly LocalFile[]): LocalTree {
  const byPath = new Map<string, LocalFile>();
  for (const file of files) byPath.set(file.path, file);
  return { nodes: buildTreeFromPaths(byPath.keys()), byPath };
}

export async function readLocalFile(file: LocalFile): Promise<string> {
  const handle = file.handle;
  const blob = await handle.getFile();
  return blob.text();
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
