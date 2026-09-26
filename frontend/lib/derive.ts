// lib/derive.ts
// Derivasi data live backend -> UI. Semua pure, tidak fetch.
// FE-1 @nabilfauzandafa

import type { NodeStatus, Operation } from "./types";

export interface LiveOp {
  id: string;
  tool_name: string;
  params_json: string;
  target_node_id: string | null;
  blast_radius: string;
  status: NodeStatus | string;
  requires_approval: number;
  created_at: string;
  executed_at?: string | null;
  verified_at?: string | null;
}

const OPEN: readonly string[] = ["pending", "approved", "executing"];

export function isOpen(status: string): boolean {
  return OPEN.includes(status);
}

// Backend tulis timestamp sebagai UTC naive (datetime.utcnow().isoformat(), tanpa "Z"),
// jadi new Date() akan baca itu sebagai waktu lokal dan geser selisih zona waktu.
// ponytail: append "Z" kalau string tidak punya offset. Kalau backend nanti pindah ke
// datetime.now(datetime.UTC), helper ini jadi no-op.
export function parseTs(iso: string | null | undefined): number {
  if (!iso) return NaN;
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasOffset ? iso : `${iso}Z`).getTime();
}

// Jam HH:MM lokal dari timestamp backend.
export function clock(iso: string | null | undefined): string {
  const t = parseTs(iso);
  if (Number.isNaN(t)) return "-";
  return new Date(t).toLocaleTimeString("id", { hour: "2-digit", minute: "2-digit" });
}

// Tanggal + jam lengkap, untuk detail view.
export function stamp(iso: string | null | undefined): string {
  const t = parseTs(iso);
  if (Number.isNaN(t)) return "-";
  return new Date(t).toLocaleString();
}

export function pct(part: number, total: number): number {
  return total === 0 ? 0 : Math.round((part / total) * 100);
}

export function countBy(items: readonly unknown[], key: (item: never) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of items) {
    const k = key(item as never);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

export interface Bucket {
  label: string;
  count: number;
}

// Jumlah operasi per bucket waktu, bucket terbaru di akhir.
// ponytail: window relatif (spanMs ke belakang), bucket absolut butuh endpoint time-series backend.
export function bucketActivity(
  ops: readonly LiveOp[],
  buckets = 10,
  spanMs = 5 * 60 * 60 * 1000
): Bucket[] {
  const now = Date.now();
  const size = spanMs / buckets;
  const out: Bucket[] = Array.from({ length: buckets }, (_, i) => ({
    label: new Date(now - spanMs + i * size).toLocaleTimeString("id", { hour: "2-digit", minute: "2-digit" }),
    count: 0,
  }));
  for (const op of ops) {
    const t = parseTs(op.created_at);
    if (Number.isNaN(t)) continue;
    const idx = Math.floor((t - (now - spanMs)) / size);
    if (idx >= buckets) out[buckets - 1].count += 1;   // event tepat "sekarang" → bucket terakhir
    else if (idx >= 0) out[idx].count += 1;
  }
  return out;
}

export interface SecurityOverview {
  total_checks: number;
  violations: number;
  blocked_ops: number;
  verified_ops: number;
  is_healthy: boolean;
}

export function securityOverview(ops: readonly LiveOp[]): SecurityOverview {
  const by = countBy(ops, (op: LiveOp) => op.status);
  const violations = (by.failed ?? 0) + (by.rolled_back ?? 0);
  return {
    total_checks: ops.length,
    violations,
    blocked_ops: by.denied ?? 0,
    verified_ops: by.verified ?? 0,
    is_healthy: (by.executing ?? 0) === 0,
  };
}

export interface RollbackStats {
  total: number;
  successful: number;
  recent: { opId: string; timestamp: string; success: boolean }[];
}

export function rollbackStats(ops: readonly LiveOp[]): RollbackStats {
  const attempts = ops.filter((op) => op.verified_at || op.status === "rolled_back" || op.status === "verified");
  const recent = ops
    .filter((op) => op.status === "rolled_back" || op.status === "verified" || op.status === "failed")
    .slice(0, 5)
    .map((op) => ({
      opId: op.id,
      timestamp: clock(op.executed_at ?? op.created_at),
      success: op.status === "verified",
    }));
  return {
    total: attempts.length,
    successful: attempts.filter((op) => op.status === "verified").length,
    recent,
  };
}

export interface ConflictCandidate {
  opId: string;
  target: string;
  conflictsWith: string[];
}

// Backend tidak menyimpan kolom conflicts di tabel operations (hanya di respons propose),
// jadiklien wajib menghitung kandidat konflik dari target yang sama.
// ponytail: grouping naif per target_node_id. Upgrade ke /operations?conflicts=true
// kalau backend sudah torment conflicts sebagai kolom.
export function conflictCandidates(ops: readonly LiveOp[]): ConflictCandidate[] {
  const byTarget = new Map<string, LiveOp[]>();
  for (const op of ops) {
    if (!op.target_node_id) continue;
    const list = byTarget.get(op.target_node_id) ?? [];
    list.push(op);
    byTarget.set(op.target_node_id, list);
  }
  const out: ConflictCandidate[] = [];
  byTarget.forEach((list, target) => {
    if (list.length < 2) return;
    out.push({ opId: list[0].id, target, conflictsWith: list.slice(1).map((o: LiveOp) => o.id) });
  });
  return out;
}

export interface TreeNode {
  id: string;
  name: string;
  type: "dir" | "file" | "doc";
  depth: number;
}

export function buildFileTree(nodes: readonly { id: string; name: string; type: string }[]): TreeNode[] {
  const out: TreeNode[] = [];
  const seen = new Set<string>();
  const sorted = [...nodes].sort((a, b) => a.name.localeCompare(b.name));
  for (const node of sorted) {
    const raw = node.name.includes("::") ? node.name.split("::").pop()! : node.name;
    // Backend di Windows menyimpan path dengan backslash, di Linux dengan forward slash.
    const parts = raw.split(/[\\/]/).filter(Boolean);
    let prefix = "";
    parts.forEach((part, i) => {
      prefix = prefix ? `${prefix}/${part}` : part;
      const isLeaf = i === parts.length - 1;
      const type: TreeNode["type"] = isLeaf
        ? node.type === "doc" ? "doc" : "file"
        : "dir";
      if (seen.has(prefix)) return;
      seen.add(prefix);
      out.push({ id: prefix, name: part, type, depth: i });
    });
  }
  return out;
}

export function relativeTime(iso: string): string {
  const t = parseTs(iso);
  if (Number.isNaN(t)) return "-";
  const diff = Math.max(0, Date.now() - t);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} h ago`;
  return `${Math.floor(hr / 24)} d ago`;
}

export function opSummary(op: LiveOp): string {
  try {
    const p = JSON.parse(op.params_json || "{}") as { sql?: string };
    if (p.sql) return p.sql;
  } catch { /* params bukan JSON */ }
  return op.target_node_id ?? op.tool_name;
}

// FE-2: payload /list_pending_approvals -> Operation[] untuk kartu approval.
export function mapPending(raw: unknown): Operation[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = (item ?? {}) as Record<string, unknown>;
    return {
      id: (o.id as string) ?? "",
      tool_name: (o.tool_name as string) ?? "unknown",
      params_json: (o.params_json as string) ?? "{}",
      target_node_id: (o.target_node_id as string) ?? null,
      blast_radius: (o.blast_radius as Operation["blast_radius"]) ?? "unknown",
      status: (o.status as NodeStatus) ?? "pending",
      requires_approval: (o.requires_approval as number) ?? 1,
      conflicts: Array.isArray(o.conflicts) ? (o.conflicts as string[]) : undefined,
      created_at: (o.created_at as string) ?? new Date().toISOString(),
    };
  });
}

// Backend tidak punya kolom conflicts (conflict disimpan sebagai edge CONFLICTS_WITH),
// jadi list approve/deny tidak pernah mengirim field itu. Hitung di FE dengan aturan
// yang sama dengan guardian._check_conflict: status aktif + window 10 menit.
// ponytail: grouping per target_node_id di memory. Upgrade ke kolom backend kalau
// conflict jadi lifecycle-nya sendiri.
const CONFLICT_WINDOW_MS = 10 * 60 * 1000;

export function withConflicts(
  ops: readonly Operation[],
  now: number = Date.now(),
): Operation[] {
  const isLiveOp = (op: Operation) =>
    op.target_node_id !== null &&
    isOpen(op.status) &&
    now - parseTs(op.created_at) <= CONFLICT_WINDOW_MS;

  const byTarget = new Map<string, string[]>();
  for (const op of ops) {
    if (!isLiveOp(op)) continue;
    const list = byTarget.get(op.target_node_id!) ?? [];
    list.push(op.id);
    byTarget.set(op.target_node_id!, list);
  }
  return ops.map((op) => {
    if (op.conflicts?.length || !isLiveOp(op)) return op;
    const others = (byTarget.get(op.target_node_id!) ?? []).filter((id) => id !== op.id);
    return others.length > 0 ? { ...op, conflicts: others } : op;
  });
}
