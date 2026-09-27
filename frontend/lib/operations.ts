// lib/operations.ts
// Satu-satunya tempat logika approve + execute Guardian (BUG-39).
//_FE-2 @ShannWasHere_

import type { NodeStatus } from "./types";

export interface DecideResult {
  /** true hanya kalau approve DAN (kalau approved) execute sama-sama sukses. */
  ok: boolean;
  /** Status akhir dari backend. null = approve gagal, jangan tampilkan status apa pun. */
  status: NodeStatus | null;
  /** Pesan error siap tampil. null = tidak ada error. */
  error: string | null;
}

interface ApiBody {
  ok?: boolean;
  status?: string;
  new_status?: string;
  error?: string;
  detail?: string;
}

const FAILED: DecideResult = { ok: false, status: null, error: "Approve ditolak backend." };

async function post(url: string, body: Record<string, unknown>): Promise<{ res: Response | null; data: ApiBody | null }> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => null);
  if (!res) return { res: null, data: null };
  return { res, data: (await res.json().catch(() => null)) as ApiBody | null };
}

/**
 * Approve/deny satu operasi, lalu eksekusi HANYA kalau approve benar-benar berhasil.
 * Backend butuh status 'approved' tersimpan sebelum execute boleh jalan, jadi
 * respons approve dicek dulu — jangan eksekusi dan jangan set status lokal kalau gagal.
 */
export async function decideOperation(
  operationId: string,
  decision: "approved" | "denied",
  backendUrl: string,
): Promise<DecideResult> {
  const { res: approveRes, data: approved } = await post(`${backendUrl}/approve_operation`, {
    operation_id: operationId,
    decision,
  });

  if (!approveRes?.ok || approved?.ok === false) {
    return { ...FAILED, error: approved?.detail ?? approved?.error ?? FAILED.error };
  }

  const status = ((approved?.status ?? approved?.new_status) as NodeStatus | undefined)
    ?? (decision === "approved" ? "approved" : "denied");

  if (decision === "denied") return { ok: true, status, error: null };

  const { res: execRes, data: executed } = await post(`${backendUrl}/execute_operation`, {
    operation_id: operationId,
  });

  if (!execRes?.ok || executed?.ok === false) {
    return {
      ok: false,
      status: (executed?.status as NodeStatus | undefined) ?? "failed",
      error: executed?.detail ?? executed?.error ?? "Execute gagal.",
    };
  }

  return { ok: true, status: (executed?.status as NodeStatus | undefined) ?? "verified", error: null };
}

export interface OpsEmptyContext {
  loading: boolean;
  liveEnabled: boolean;
  offline: boolean;
  /** Id target aktif, atau null kalau belum ada target yang dipilih. */
  activeTargetId: string | null;
}

/**
 * Pesan untuk daftar operasi yang kosong.
 *
 * PENTING: sejak operasi di-scope per target (backend cuma mengembalikan
 * operations milik target aktif), "kosong" punya beberapa sebab yang berbeda
 * dan user perlu tahu yang mana. Dulu semuanya dijawab "Belum ada operasi",
 * sehingga target yang salah aktif terlihat seperti riwayat approval hilang -
 * persis kekhawatiran user soal approval tercampur antar repository.
 *
 * `activeTargetId === null` berarti memang belum ada target; kalau tidak,
 * kosong berarti target ini belum punya operasi (History repository lain
 * sengaja tidak ditampilkan, dan tidak hilang dari database).
 */
export function opsEmptyMessage(ctx: OpsEmptyContext): string {
  if (ctx.loading) return "Loading operations...";
  if (!ctx.liveEnabled) return "Live data OFF - set NEXT_PUBLIC_USE_LIVE_SSE=true.";
  if (ctx.offline) return "Backend offline - no data.";
  if (!ctx.activeTargetId) {
    return "Belum ada target aktif, jadi tidak ada operasi yang bisa ditampilkan. Pilih target di Settings.";
  }
  return "Belum ada operasi untuk target ini. Riwayat repository lain tidak ditampilkan.";
}
