// hooks/useGitHubAuth.ts
// State koneksi GitHub: apakah tersambung, siapa, lewat OAuth atau PAT.
//
// PAT tidak pernah disimpan di frontend. Nilainya dikirim sekali ke backend
// yang memvalidasinya ke api.github.com, lalu meng-enkripsi-nya (auth.encrypt_token)
// ke tabel github_connections. State di hook ini hanya menyimpan login dan
// avatar - bukan rahasianya.

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  connectWithPat,
  disconnect,
  fetchConnection,
  fetchOAuthUrl,
  type GitHubConnection,
} from "@/lib/githubApi";

export type GitHubAuthMode = "unknown" | "connected" | "disconnected";

export function useGitHubAuth() {
  const [connection, setConnection] = useState<GitHubConnection | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** true kalau backend mengembalikan 500 karena env OAuth belum di-set. */
  const [oauthUnavailable, setOauthUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setConnection(await fetchConnection());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const connectPat = useCallback(async (pat: string) => {
    setBusy(true);
    setError(null);
    try {
      await connectWithPat(pat);
      await refresh();
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err);
      setError(text);
      throw err;
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const disconnectGitHub = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const removed = await disconnect();
      // Optimal di sini memang benar: state "tidak tersambung" persis
      // hasil server, dan tidak ada data turunan yang bisa basi.
      setConnection({ connected: false });
      return removed;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setBusy(false);
    }
  }, []);

  /**
   * URL authorize GitHub. Kalau backend bilang "not configured", tandai
   * oauthUnavailable supaya UI menyembunyikan tombol OAuth dan menjelaskan
   * cara mengaktifkannya, daripada gagal berulang.
   */
  const getOAuthUrl = useCallback(async (): Promise<string | null> => {
    setError(null);
    try {
      const { url } = await fetchOAuthUrl();
      setOauthUnavailable(false);
      return url;
    } catch (err) {
      setOauthUnavailable(true);
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  const mode: GitHubAuthMode = loading
    ? "unknown"
    : connection?.connected
      ? "connected"
      : "disconnected";

  return {
    connection,
    user: connection?.user ?? null,
    mode,
    loading,
    busy,
    error,
    oauthUnavailable,
    refresh,
    connectPat,
    disconnect: disconnectGitHub,
    getOAuthUrl,
  };
}
