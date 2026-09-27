"use client";

// components/ProviderSelect.tsx
// Pemilih provider + model untuk panel chat Cortex.
//
// CortexPage sebelumnya mengirim providerId="openai:gpt-4o" dan model="gpt-4o"
// yang ditulis mati: /api/llm/chat mencari baris itu di llm_providers, tabel
// itu mulai kosong, jadi setiap chat berakhir "Provider not found or disabled".
// Sekarang id dan model datang dari registry yang benar-benar diisi user.

import { useLLMProviders } from "@/hooks/useLLMProviders";
import { reconcileDefault } from "@/lib/llmProviders";

export interface ProviderSelectProps {
  providerId: string;
  model: string;
  onChange: (providerId: string, model: string) => void;
  className?: string;
}

export default function ProviderSelect({
  providerId,
  model,
  onChange,
  className = "",
}: ProviderSelectProps) {
  const { providers, loading } = useLLMProviders();

  // Hanya provider enabled yang bisa dipakai: /api/llm/chat menambah filter
  // `AND enabled = 1`, jadi memilih yang nonaktif akan 404.
  const usable = providers.filter((p) => p.enabled);

  if (loading) {
    return (
      <p className={`text-[10px] text-slate-500 animate-pulse ${className}`}>
        Memuat provider...
      </p>
    );
  }

  if (usable.length === 0) {
    return (
      <p className={`text-[10px] text-amber-400 ${className}`}>
        Belum ada provider LLM aktif. Tambah dulu di{" "}
        <span className="font-mono text-slate-300">Settings &rarr; LLM</span>, kalau tidak
        chat akan gagal dengan &quot;Provider not found or disabled&quot;.
      </p>
    );
  }

  const active = usable.find((p) => p.id === providerId) ?? usable[0];
  // Kalau id yang tersimpan sudah tidak ada (provider dihapus, atau dimatikan),
  // jatuhkan ke provider pertama yang aktif - bukan kirim id mati ke backend.
  const effectiveModel = active.id === providerId ? model : reconcileDefault(active.models, model);

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <select
        value={active.id}
        onChange={(e) => {
          const next = usable.find((p) => p.id === e.target.value);
          if (!next) return;
          // Model ikut provider: model milik provider lama tidak berlaku di sini.
          onChange(next.id, reconcileDefault(next.models, ""));
        }}
        className="rounded-lg border border-slate-700/60 bg-slate-800 px-2 py-1 text-[10px] text-slate-200 outline-none"
        aria-label="LLM provider"
      >
        {usable.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.type})
          </option>
        ))}
      </select>

      <select
        value={effectiveModel}
        onChange={(e) => onChange(active.id, e.target.value)}
        className="rounded-lg border border-slate-700/60 bg-slate-800 px-2 py-1 font-mono text-[10px] text-slate-200 outline-none"
        aria-label="Model"
      >
        {active.models.length === 0 && <option value="">(belum ada model)</option>}
        {active.models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </div>
  );
}
