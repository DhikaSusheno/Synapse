// hooks/useLLMProviders.ts
// State registry LLM provider: load, create, patch, delete.
//
// Semua mutasi selesai di backend dulu; daftar di state baru ditulis ulang
// dari server, bukan dioptimistik. Optimistik di sini berarti UI menampilkan
// provider yang ditolak 409/422, dan user spend waktu mendiagnosis config
// yang memang tidak pernah ada.

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  type LLMProvider,
  type ProviderDraft,
} from "@/lib/llmProviders";

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useLLMProviders() {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProviders(await listProviders());
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (draft: ProviderDraft) => {
      setBusy(true);
      setError(null);
      try {
        const id = await createProvider(draft);
        await refresh();
        return id;
      } catch (err) {
        setError(message(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const update = useCallback(
    async (id: string, patch: Partial<ProviderDraft>) => {
      setBusy(true);
      setError(null);
      try {
        await updateProvider(id, patch);
        await refresh();
      } catch (err) {
        setError(message(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        await deleteProvider(id);
        await refresh();
      } catch (err) {
        setError(message(err));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  return { providers, loading, busy, error, refresh, create, update, remove };
}
