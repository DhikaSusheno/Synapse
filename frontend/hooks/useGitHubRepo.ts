// hooks/useGitHubRepo.ts
// Pembungkus state untuk daftar repo + isi file GitHub.
//
// Logika HTTP-nya ada di lib/githubApi.ts supaya ada satu tempat yang tahu
// bentuk path endpoint. Hook ini cuma menyimpan state loading/error.

"use client";

import { useCallback, useState } from "react";
import {
  fetchFileContent,
  fetchRepoTree,
  fetchRepos,
  isNotConnected,
  type GitHubRepo,
  type GitHubTreeItem,
} from "@/lib/githubApi";

export type { GitHubRepo, GitHubTreeItem };

export function useGitHubRepo() {
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "Belum ada GitHub connection" adalah status normal, bukan kegagalan.
  // Dikenali dari status HTTP (lihat isNotConnected), bukan dari teks pesan,
  // karena proxy Next mengubah 401 menjadi 502.
  const [notConnected, setNotConnected] = useState(false);

  const fetchReposList = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotConnected(false);
    try {
      setRepos(await fetchRepos());
    } catch (err) {
      if (isNotConnected(err)) {
        setRepos([]);
        setNotConnected(true);
        setError(null);
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const getFileTree = useCallback(
    (owner: string, repo: string, branch = "main") =>
      fetchRepoTree(owner, repo, branch),
    [],
  );

  const getFileContent = useCallback(
    (owner: string, repo: string, path: string, branch = "main") =>
      fetchFileContent(owner, repo, path, branch),
    [],
  );

  return {
    repos,
    loading,
    error,
    notConnected,
    fetchRepos: fetchReposList,
    getFileTree,
    getFileContent,
  };
}
