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
