// hooks/useTargets.ts
// State target analisis: daftar target, ganti target, tambah repo/folder.
//
// DATA TIDAK DISIMPAN DI HOOK INI. Snapshot target hidup di lib/targets.ts
// supaya Overview, Cortex, dan Settings membaca sumber yang sama - kalau
// masing-masing punya state sendiri, dua halaman bisa menampilkan target
// yang berbeda dan user tidak bisa unexplain why angkanya beda.
//
// Yang disimpan di hook hanya status UI: loading, busy, error, dan hasil
// ingest terakhir. Mutasi menulis ke store lewat publishTargets(), yang
// sekaligus menaikkan penanda perubahan supaya halaman lain yang memuat
// data graph ikut fetch ulang.

"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  activateTarget as activateTargetApi,
  createLocalTarget,
  getGraphGeneration,
  getTargetSnapshot,
  listTargets,
  publishTargets,
  removeTarget as removeTargetApi,
  subscribeTargets,
  syncGitHubTarget,
  validateGitHubDraft,
  validateLocalDraft,
  type GitHubTargetDraft,
  type IngestSummary,
  type LocalTargetDraft,
} from "@/lib/targets";

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Nilai yang berubah setiap kali target aktif berpindah.
 *
 * Pakai ini sebagai dependency useEffect di halaman yang memuat data graph:
 * begitu target diganti, efeknya jalan ulang dan fetch baru ke /graph/*.
 * Tanpa itu, user pindah repo tapi grafik masih milik repo sebelumnya.
 */
export function useTargetGeneration(): number {
  return useSyncExternalStore(subscribeTargets, getGraphGeneration);
}

/** Target aktif + daftar target, langsung dari store. Tanpa fetch sendiri. */
export function useTargetSnapshot() {
  return useSyncExternalStore(subscribeTargets, getTargetSnapshot);
}

export function useTargets() {
  const { active, targets } = useTargetSnapshot();
  const [ingest, setIngest] = useState<IngestSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      publishTargets(await listTargets());
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Bungkus mutasi: busy + error seragam, publish ke store kalau sukses. */
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(message(err));
      throw err;
    } finally {
      setBusy(false);
    }
  }, []);

  const addLocal = useCallback(
    async (draft: LocalTargetDraft) => {
      const problems = validateLocalDraft(draft);
      if (problems.length) throw new Error(problems[0]);
      return run(async () => {
        const res = await createLocalTarget(draft);
        publishTargets(res);
        setIngest(res.ingest ?? null);
        return res;
      });
    },
    [run],
  );

  const addGitHub = useCallback(
    async (draft: GitHubTargetDraft) => {
      const problems = validateGitHubDraft(draft);
      if (problems.length) throw new Error(problems[0]);
      return run(async () => {
        const res = await syncGitHubTarget(draft);
        publishTargets(res);
        setIngest(res.ingest ?? null);
        return res;
      });
    },
    [run],
  );

  const activate = useCallback(
    async (id: string, opts: { ingest?: boolean } = {}) => {
      return run(async () => {
        const res = await activateTargetApi(id, opts);
        publishTargets(res);
        setIngest(res.ingest ?? null);
        return res;
      });
    },
    [run],
  );

  const remove = useCallback(
    async (id: string, opts: { removeGraph?: boolean } = {}) => {
      return run(async () => {
        const res = await removeTargetApi(id, opts);
        publishTargets(res);
        setIngest(null);
        return res;
      });
    },
    [run],
  );

  return {
    targets,
    active,
    ingest,
    loading,
    busy,
    error,
    refresh,
    addLocal,
    addGitHub,
    activate,
    remove,
    clearError: () => setError(null),
  };
}
