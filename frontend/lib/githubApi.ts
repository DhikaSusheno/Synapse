// lib/githubApi.ts
// Client typed untuk endpoint GitHub (backend/main.py, tag "GitHub").
//
// Token API DAN token GitHub tidak pernah ada di browser. Route handler
// app/backend/[...path] menyuntikkan SYNAPSE_API_TOKEN dari sisi server, dan
// PAT GitHub hanya pernah dikirim ke backend, dienkripsi di sqlite. Jadi
// semua fetch di sini same-origin tanpa header auth.

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

import { buildTreeFromPaths, type FileTreeNode } from "./fileTree.ts";

export type { FileTreeNode };

export interface GitHubUser {
  login: string;
  avatar_url?: string;
  name?: string | null;
}

export interface GitHubConnection {
  connected: boolean;
  type?: "oauth" | "pat";
  user?: GitHubUser;
  error?: string;
}

export interface GitHubRepo {
  id: number;
  name: string;
  full_name: string;
  private: boolean;
  html_url: string;
  description: string | null;
  default_branch: string;
  updated_at: string;
  stargazers_count: number;
  language: string | null;
}

export interface GitHubTreeItem {
  path: string;
  mode: string;
  type: "blob" | "tree";
  sha: string;
  size: number;
  url: string;
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
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      // Backend FastAPI menulis {"detail": ...}; route handler proxy Next
      // menulis {"error": ..., "hint": ...}. Hanya membaca "detail" membuat
      // semua error dari proxy jadi "HTTP 502" tanpa penjelasan.
      if (typeof body?.detail === "string") detail = body.detail;
      else if (typeof body?.error === "string") detail = body.error;
    } catch {
      // body bukan JSON
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Pesan yang dipakai app/backend/[...path] saat backend membalas 401. */
const PROXY_TOKEN_REJECTED = "Token API backend ditolak";

/**
 * True kalau error berarti "belum ada koneksi GitHub", bukan kegagalan yang
 * perlu ditampilkan sebagai bug.
 *
 * Backend membalas 401 "No GitHub connection" untuk semua /api/github/repos*.
 * Tapi proxy Next menerjemahkan 401 menjadi 502 supaya token API yang salah
 * tidak bisa disamarkan sebagai masalah GitHub. Jadi lewat proxy angka
 * status-nya 502, bukan 401 - yang harus tetap diartikan "belum terhubung".
 */
export function isNotConnected(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.status === 401) return true;
  return err.status === 502 && err.message.includes(PROXY_TOKEN_REJECTED);
}

// owner/repo di-encode per-segmen supaya karakter aneh tidak memecah path.
// PR #67 sudah pasang ini di sisi proxy; di sini tetap perlu karena request
// bisa juga Buyers bypass proxy saat backend di-set jadi NEXT_PUBLIC_BACKEND_URL.
const seg = (v: string) => encodeURIComponent(v);

export async function fetchConnection(): Promise<GitHubConnection> {
  return api<GitHubConnection>("/api/github/user");
}

export async function fetchOAuthUrl(): Promise<{ url: string; redirect_uri: string }> {
  return api<{ url: string; redirect_uri: string }>("/api/github/auth/url");
}

export async function connectWithPat(
  pat: string,
  scopes: string[] = ["repo", "read:org", "read:user"],
): Promise<GitHubUser> {
  const data = await api<{ ok: boolean; user: GitHubUser }>("/api/github/auth/pat", {
    method: "POST",
    body: JSON.stringify({ pat, scopes }),
  });
  return data.user;
}

export async function disconnect(): Promise<number> {
  const data = await api<{ ok: boolean; removed: number }>("/api/github/connection", {
    method: "DELETE",
  });
  return data.removed ?? 0;
}

export async function fetchRepos(perPage = 100): Promise<GitHubRepo[]> {
  const data = await api<{ ok: boolean; repos: GitHubRepo[] }>(
    `/api/github/repos?per_page=${perPage}`,
  );
  return data.repos ?? [];
}

export async function fetchRepoTree(
  owner: string,
  repo: string,
  branch = "main",
  recursive = true,
): Promise<GitHubTreeItem[]> {
  const data = await api<{ tree?: GitHubTreeItem[]; truncated?: boolean }>(
    `/api/github/repos/${seg(owner)}/${seg(repo)}/tree` +
      `?branch=${encodeURIComponent(branch)}&recursive=${recursive ? "true" : "false"}`,
  );
  return data.tree ?? [];
}

/**
 * Ambil isi satu file.
 *
 * PENTING: path dikirim sebagai QUERY parameter, bukan segmen path. Rutenya
 * `GET /api/github/repos/{owner}/{repo}/contents` dengan `path: str` sebagai
 * query param (backend/main.py). Versi lama menaruh path sebagai segmen
 * (`/contents/frontend%2Fapp`) sehingga FastAPI tidak pernah match dan
 * selalu 404.
 */
export async function fetchFileContent(
  owner: string,
  repo: string,
  path: string,
  branch = "main",
): Promise<string> {
  const data = await api<{ content?: string; encoding?: string; type?: string }>(
    `/api/github/repos/${seg(owner)}/${seg(repo)}/contents` +
      `?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch)}`,
  );
  if (typeof data.content !== "string") {
    throw new Error(`${path} bukan file (tipe: ${data.type ?? "?"})`);
  }
  return data.encoding === "base64" ? decodeBase64Utf8(data.content) : data.content;
}

/**
 * Base64 GitHub berisi byte mentah file, jadi harus lewat UTF-8 decoder.
 * atob() langsung menghasilkan string latin1: setiap karakter non-ASCII jadi
 * mojibake. Komentar dengan huruf Indonesia dan emoji di source code akan rusak.
 */
export function decodeBase64Utf8(b64: string): string {
  const binary = atob(b64.replace(/\s/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// --- tree flattening, murni supaya bisa diuji tanpa network ------------------

/**
 * Ubah hasil `git/trees?recursive=true` yang datar jadi pohon bersarang
 * untuk FileTreeBrowser.
 *
 * Hanya `blob` yang jadi file. GitHub tidak mengirim entri untuk direktori,
 * jadi direktori disimpulkan dari segmen path (lihat lib/fileTree.ts). Item
 * bertipe "tree" (submodule, atau symlink ke direktori) sengaja diabaikan:
 * kalau dirender sebagai file, user klik dan dapat "bukan file".
 */
export function buildFileTree(items: readonly GitHubTreeItem[]): FileTreeNode[] {
  return buildTreeFromPaths(
    items.filter((item) => item.type === "blob").map((item) => item.path),
  );
}
