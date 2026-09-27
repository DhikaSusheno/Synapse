// hooks/useGitHubRepo.ts
// Hook untuk GitHub repository integration

import { useState, useCallback, useEffect } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";

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

export interface GitHubFile {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
  sha: string;
  url: string;
}

export interface GitHubTreeItem {
  path: string;
  mode: string;
  type: "blob" | "tree";
  sha: string;
  size: number;
  url: string;
}

export interface GitHubTreeResponse {
  sha: string;
  tree: GitHubTreeItem[];
  truncated: boolean;
}

interface GitHubApiResponse<T> {
  ok: boolean;
  repos?: GitHubRepo[];
  tree?: GitHubTreeItem[];
  file?: {
    content: string;
    encoding: string;
    size: number;
    name: string;
    path: string;
  };
  error?: string;
}

// Token API tidak pernah ada di browser: route handler app/backend/[...path]
// menyuntikkan SYNAPSE_API_TOKEN dari sisi server. Jadi request cukup
// same-origin tanpa header auth apa pun.

export function useGitHubRepo() {
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRepos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/github/repos?per_page=100`);
      
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      
      const data = await res.json();
      if (data.ok && Array.isArray(data.repos)) {
        setRepos(data.repos);
      } else {
        throw new Error(data.error || "Failed to fetch repos");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch repositories");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRepos();
  }, [fetchRepos]);

  const getFileTree = useCallback(async (owner: string, repo: string, branch: string = "main"): Promise<GitHubTreeItem[]> => {
    const res = await fetch(`${BACKEND_URL}/api/github/repos/${owner}/${repo}/tree?branch=${branch}&recursive=true`);
    
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    
    const data = await res.json();
    return data.tree || [];
  }, []);

  const getFileContent = useCallback(async (owner: string, repo: string, path: string, branch: string = "main"): Promise<string> => {
    const res = await fetch(`${BACKEND_URL}/api/github/repos/${owner}/${repo}/contents/${encodeURIComponent(path)}?branch=${branch}`);
    
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    
    const data = await res.json();
    if (data.content && data.encoding === "base64") {
      return atob(data.content);
    }
    return "";
  }, []);

  return {
    repos,
    loading,
    error,
    fetchRepos,
    getFileTree,
    getFileContent,
  };
}

// Hook untuk local folder access (File System Access API)
export function useLocalFolder() {
  const [folderHandle, setFolderHandle] = useState<FileSystemDirectoryHandle | null>(null);
  const [files, setFiles] = useState<FileSystemFileHandle[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickFolder = useCallback(async () => {
    if (!("showDirectoryPicker" in window)) {
      setError("File System Access API tidak didukung di browser ini");
      return null;
    }

    try {
      const handle = await (window as any).showDirectoryPicker({
        mode: "read",
      });
      setFolderHandle(handle);
      await loadFiles(handle);
      return handle;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memilih folder");
      return null;
    }
  }, []);

  const loadFiles = useCallback(async (handle: FileSystemDirectoryHandle) => {
    setLoading(true);
    try {
      const entries: FileSystemFileHandle[] = [];
      for await (const entry of handle.values()) {
        if (entry.kind === "file") entries.push(entry as FileSystemFileHandle);
      }
      setFiles(entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memuat file");
    } finally {
      setLoading(false);
    }
  }, []);

  const readFile = useCallback(async (fileHandle: FileSystemFileHandle): Promise<string> => {
    const file = await fileHandle.getFile();
    return await file.text();
  }, []);

  return {
    folderHandle,
    files,
    loading,
    error,
    pickFolder,
    readFile,
  };
}