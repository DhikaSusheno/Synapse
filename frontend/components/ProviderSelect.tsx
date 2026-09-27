"use client";

// components/ProviderSelect.tsx
// Pemilih provider + model untuk panel chat Cortex.
//
// CortexPage sebelumnya mengirim providerId="openai:gpt-4o" dan model="gpt-4o"
// yang ditulis mati: /api/llm/chat mencari baris itu di llm_providers, tabel
// itu mulai kosong, jadi setiap chat berakhir "Provider not found or disabled".
// Sekarang id dan model datang dari registry yang benar-benar diisi user.

import { useEffect, useRef } from "react";
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

  // Kalau id yang tersimpan sudah tidak ada (provider dihapus, atau dimatikan),
  // jatuhkan ke provider pertama yang aktif - bukan kirim id mati ke backend.
  const active = usable.find((p) => p.id === providerId) ?? usable[0];
  const activeId = active?.id ?? null;
  const effectiveModel =
    active && activeId !== providerId
      ? reconcileDefault(active.models, model)
      : model;

  // BUG-42: `active` di atas hanya dipakai untuk ME-RENDER select. Kalau kita
  // tidak menyinkronkannya ke parent, select terlihat menunjukkan "Deepseek v4"
  // sementara state parent masih providerId="" (nilai awal CortexPage). Chat lalu
  // mengirim provider_id="" dan backend membalas 404 "Provider not found or
  // disabled" - user melihat provider yang benar tapi chat selalu gagal.
  //
  // Dua hal yang WAJIB berlaku di effect ini:
  // 1. Hook HARUS di atas semua `return` awal. Kalau tidak, render pertama
  //    (loading=true) sama sekali tidak memanggil hook ini, sementara render kedua
  //    memanggilnya -> React melempar "Rendered more hooks than during the
  //    previous render" dan seluruh halaman Cortex blank.
  // 2. Syaratnya perbandingan nilai, bukan "selalu panggil onChange", supaya
  //    tidak memicu render berulang.
  //
  // onChange dibaca lewat ref: parent sering mengirim arrow inline (CortexPage),
  // jadi identitasnya berubah tiap render. Kalau onChange ikut jadi dependensi,
  // effect jalan setiap render - dan kalau parent membalas dengan nilai yang
  // sedikit berbeda (mis. model dinormalkan), itu jadi render loop.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (activeId && (activeId !== providerId || effectiveModel !== model)) {
      onChangeRef.current(activeId, effectiveModel);
    }
  }, [activeId, effectiveModel, providerId, model]);

  if (loading) {
    return (
      <p className={`text-[10px] text-slate-500 animate-pulse ${className}`}>
        Memuat provider...
      </p>
    );
  }

  if (!active) {
    return (
      <p className={`text-[10px] text-amber-400 ${className}`}>
        Belum ada provider LLM aktif. Tambah dulu di{" "}
        <span className="font-mono text-slate-300">Settings &rarr; LLM</span>, kalau tidak
        chat akan gagal dengan &quot;Provider not found or disabled&quot;.
      </p>
    );
  }

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
