"use client";
// components/pages/CortexPage.tsx
// Halaman Cortex — sesuai design section 3
// FE-1 @nabilfauzandafa

import { useEffect, useState, useSyncExternalStore } from "react";
import { buildFileTree, type TreeNode } from "@/lib/derive";
import { num, arr, str } from "@/lib/coerce";
import { LLMChatPanel } from "@/components/LLMChatPanel";
import ProviderSelect from "@/components/ProviderSelect";
import TargetPicker from "@/components/TargetPicker";
import { useTargetGeneration } from "@/hooks/useTargets";
import { getActiveTarget, subscribeActiveTarget } from "@/lib/targets";
import {
  clearArtifact,
  getArtifact,
  subscribe as subscribeArtifact,
} from "@/lib/workspaceArtifact";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "/backend";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

interface ExplainResult {
  definition: string;
  mental_model: string;
  complexity_note?: string;
  how_to_use?: string;
  example?: string;
}

interface ReviewScores {
  completeness: number;
  clarity: number;
  correctness_vs_spec: number;
  risk: number;
  verdict: string;
  risk_findings?: { severity?: string; message?: string }[];
  notes?: Record<string, number>;
  artifact?: string;
  is_file?: boolean;
}

// --- Bentuk response mengikuti engine.py (backend/main.py meneruskan lewat cortex.py) ---

interface RepoHealth {
  ok: boolean;
  health_score: number;
  health_label: string;
  summary: string;
  doc_coverage_percent: number;
  total_files: number;
  documented_files: number;
  dead_code_count: number;
  high_complexity_count: number;
  hub_nodes: { id: string; name: string; kind: string; degree: number }[];
}

interface ComplexityRow {
  id: string;
  name: string;
  kind: string;
  file: string;
  line: number;
  complexity: number;
  lines: number;
  risk_level: string;
}

interface ComplexityReport {
  ok: boolean;
  results: ComplexityRow[];
  total_returned: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

interface FindPathResult {
  ok: boolean;
  from: string;
  to: string;
  direction: string;
  path_length: number;
  path: { id: string; name: string; kind: string }[];
  edges: { from: string; to: string; relationship: string; traversed: string }[];
}

interface RefactorResult {
  ok: boolean;
  node: string;
  kind: string;
  metrics: {
    complexity: number;
    lines: number;
    degree: number;
    in_degree: number;
    out_degree: number;
    has_documentation: boolean;
  };
  suggestions: { type: string; priority: string; message: string }[];
}

const RISK_CLASS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-yellow-500/20 text-yellow-400",
  low: "bg-green-500/20 text-green-400",
};

const PRIORITY_CLASS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-yellow-500/20 text-yellow-400",
  low: "bg-slate-700/60 text-slate-400",
};

function healthClass(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  return "text-red-400";
}

// FastAPI balas error sebagai { detail: string } dengan HTTP 4xx. Tanpa ini
// layar diam saja saat entitas tidak ketemu — bug yang sama seperti issue #39.
async function errorDetail(r: Response, fallback: string): Promise<string> {
  try {
    const d = await r.json();
    return typeof d?.detail === "string" ? d.detail : fallback;
  } catch {
    return fallback;
  }
}

// Tree repo dari node graph backend (/graph/nodes) — bukan mock.
// reloadKey datang dari useTargetGeneration: ganti target = ganti DB graph,
// jadi tree lama harus dibuang, bukan ditimpa kalau yang baru tidak kosong.
function useFileTree(
  enabled: boolean,
  reloadKey: number
): { tree: TreeNode[]; loading: boolean; error: string | null } {
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetch(`${BACKEND_URL}/graph/nodes?type=file`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : [])),
      fetch(`${BACKEND_URL}/graph/nodes?type=doc`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([files, docs]) => {
        if (cancelled) return;
        const all = [
          ...(Array.isArray(files) ? files : []),
          ...(Array.isArray(docs) ? docs : []),
        ] as { id: string; name: string; type: string }[];
        setTree(buildFileTree(all));
        setError(null);
      })
      .catch(() => { if (!cancelled) setError("Backend tidak dapat dijangkau"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [enabled, reloadKey]);

  return { tree, loading, error };
}

const MOCK_EXPLAIN: ExplainResult = {
  definition: "The guardian module handles risky operation protection, including conflict detection, snapshots and rollback.",
  mental_model: "Think of it as a safety layer that intercepts operations, checks the blast radius, and ensures reversibility before execution.",
  complexity_note: "McCabe complexity: 8 (medium)",
  how_to_use: "Call propose_operation() first, then approve_operation() and execute_operation().",
  example: `guardian.propose_operation(
  tool_name="db.run_migration",
  params={"sql": "ALTER TABLE..."},
  target="synapse.db"
)`,
};

const MOCK_REVIEW: ReviewScores = {
  completeness: 8.9, clarity: 8.0, correctness_vs_spec: 7.5, risk: 6.0, verdict: "pass",
};

export default function CortexPage() {
  // Target analisis yang aktif. Kalau berubah, tree di bawah ini dibaca ulang
  // dari DB graph yang baru - dan selectedFile harus dibuang, karena path
  // yang ada di repo lama belum tentu ada di repo yang baru.
  const targetGeneration = useTargetGeneration();
  const activeTarget = useSyncExternalStore(subscribeActiveTarget, getActiveTarget, getActiveTarget);
  const { tree, loading: treeLoading, error: treeError } = useFileTree(USE_LIVE, targetGeneration);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  // Path yang valid di repo lama belum tentu ada di repo baru. Kalau tidak
  // dibuang, panel review akan mengirim path yang sudah tidak ada dan user
  // melihat error dari file yang tidak pernah dipilih.
  useEffect(() => {
    setSelectedFile(null);
  }, [targetGeneration]);
  const [explainTopic, setExplainTopic] = useState("How does the guardian module work?");
  const [explainResult, setExplainResult] = useState<ExplainResult | null>(USE_LIVE ? null : MOCK_EXPLAIN);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [artifactPath, setArtifactPath] = useState("backend/guardian.py");
  // Dipilih lewat Settings (tab LLM), bukan ditulis mati: /api/llm/chat hanya
  // menerima provider yang ada di llm_providers.
  const [chatProviderId, setChatProviderId] = useState("");
  const [chatModel, setChatModel] = useState("");
  // File yang dikirim dari tab GitHub / Folder Lokal di Settings. useSyncExternalStore
  // supaya Cortex ikut berubah walau Settings sudah ditutup - dan tanpa effect
  // yang menulis state setiap render.
  const artifact = useSyncExternalStore(subscribeArtifact, getArtifact, getArtifact);
  const [reviewResult, setReviewResult] = useState<ReviewScores | null>(USE_LIVE ? null : MOCK_REVIEW);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const [health, setHealth] = useState<RepoHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [complexity, setComplexity] = useState<ComplexityReport | null>(null);
  const [complexityError, setComplexityError] = useState<string | null>(null);
  const [pathFrom, setPathFrom] = useState("main.py");
  const [pathTo, setPathTo] = useState("database.py");
  const [pathResult, setPathResult] = useState<FindPathResult | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [pathLoading, setPathLoading] = useState(false);
  const [refactorTarget, setRefactorTarget] = useState("main.py");
  const [refactorResult, setRefactorResult] = useState<RefactorResult | null>(null);
  const [refactorError, setRefactorError] = useState<string | null>(null);
  const [refactorLoading, setRefactorLoading] = useState(false);

  // GET /repo_health + GET /complexity_report — dua-duanya read-only, ambil sekali
  // saat mount. beide endpoint sudah ada di backend tapi sebelumnya tidak pernah dipanggil.
  useEffect(() => {
    if (!USE_LIVE) return;
    let cancelled = false;

    // Normalisasi di trust boundary: backend boleh kirim field partial, dan
    // `as RepoHealth` akan membuat TypeScript percaya pada value yang tidak ada.
    fetch(`${BACKEND_URL}/repo_health`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as Partial<RepoHealth>) : Promise.reject(await errorDetail(r, "Gagal ambil /repo_health"))))
      .then((d) => { if (!cancelled) { setHealth({ ...d, health_score: num(d.health_score), total_files: num(d.total_files), documented_files: num(d.documented_files), doc_coverage_percent: num(d.doc_coverage_percent), dead_code_count: num(d.dead_code_count), high_complexity_count: num(d.high_complexity_count), hub_nodes: arr(d.hub_nodes) } as RepoHealth); setHealthError(null); } })
      .catch((e: string) => { if (!cancelled) setHealthError(e); });

    fetch(`${BACKEND_URL}/complexity_report?top_n=10`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as Partial<ComplexityReport>) : Promise.reject(await errorDetail(r, "Gagal ambil /complexity_report"))))
      .then((d) => { if (!cancelled) { setComplexity({ ...d, results: arr(d.results), total_returned: num(d.total_returned), critical_count: num(d.critical_count), high_count: num(d.high_count), medium_count: num(d.medium_count), low_count: num(d.low_count) } as ComplexityReport); setComplexityError(null); } })
      .catch((e: string) => { if (!cancelled) setComplexityError(e); });

    return () => { cancelled = true; };
  }, []);

  async function runExplain() {
    if (!USE_LIVE) { setExplainResult(MOCK_EXPLAIN); return; }
    setExplainLoading(true);
    setExplainError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/explain_topic`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: explainTopic }),
      });
      // 404 di sini berarti "tidak ada entitas graph yang cocok dengan topik",
      // bukan endpoint rusak. Kalau errornya dibuang, tombolnya terlihat mati.
      if (!r.ok) { setExplainError(await errorDetail(r, "Gagal menjelaskan topik")); return; }
      const d = await r.json();
      if (d.ok) setExplainResult(d as ExplainResult);
      else setExplainError(d.error ?? "Backend tidak mengembalikan penjelasan");
    } catch (e) {
      setExplainError("Backend tidak dapat dijangkau");
    } finally { setExplainLoading(false); }
  }

  async function runReview() {
    if (!USE_LIVE) { setReviewResult(MOCK_REVIEW); return; }
    setReviewLoading(true);
    setReviewError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/review_artifact`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path_or_diff: artifactPath }),
      });
      if (!r.ok) { setReviewError(await errorDetail(r, "Gagal me-review artefak")); return; }
      const d = await r.json();
      // Skor datang di dalam objek `scores` (engine.review_artifact), bukan di
      // top-level. Bacanya dari d.completeness selalu menghasilkan 0, jadi
      // panel Review menampilkan nol untuk artefak apa pun.
      const s = (d.scores ?? {}) as Record<string, unknown>;
      if (d.ok) {
        setReviewResult({
          artifact: str(d.artifact),
          is_file: d.is_file === true,
          completeness: num(s.completeness),
          clarity: num(s.clarity),
          correctness_vs_spec: num(s.correctness_vs_spec),
          risk: num(s.risk),
          verdict: str(d.verdict),
          risk_findings: arr(d.risk_findings) as ReviewScores["risk_findings"],
          notes: (d.notes ?? {}) as Record<string, number>,
        });
      } else {
        setReviewError(d.error ?? "Backend tidak mengembalikan skor");
      }
    } catch {
      setReviewError("Backend tidak dapat dijangkau");
    } finally { setReviewLoading(false); }
  }

  async function runFindPath() {
    if (!USE_LIVE || !pathFrom.trim() || !pathTo.trim()) return;
    setPathLoading(true);
    setPathError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/find_path`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_node: pathFrom.trim(), to_node: pathTo.trim() }),
      });
      if (!r.ok) { setPathResult(null); setPathError(await errorDetail(r, "Gagal cari jalur")); return; }
      const d = await r.json();
      if (d.ok) { setPathResult({ ...d, path: arr(d.path), edges: arr(d.edges), path_length: num(d.path_length) } as FindPathResult); setPathError(null); }
      else { setPathResult(null); setPathError(d.error ?? "Jalur tidak ditemukan"); }
    } catch {
      setPathResult(null);
      setPathError("Backend tidak dapat dijangkau");
    } finally { setPathLoading(false); }
  }

  async function runSuggestRefactor() {
    if (!USE_LIVE || !refactorTarget.trim()) return;
    setRefactorLoading(true);
    setRefactorError(null);
    try {
      const r = await fetch(`${BACKEND_URL}/suggest_refactor`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_name: refactorTarget.trim() }),
      });
      if (!r.ok) { setRefactorResult(null); setRefactorError(await errorDetail(r, "Gagal ambil saran refactor")); return; }
      const d = await r.json();
      if (d.ok) { setRefactorResult({ ...d, metrics: { ...(d.metrics ?? {}), complexity: num(d.metrics?.complexity), lines: num(d.metrics?.lines), degree: num(d.metrics?.degree), in_degree: num(d.metrics?.in_degree), out_degree: num(d.metrics?.out_degree) }, suggestions: arr(d.suggestions) } as unknown as RefactorResult); setRefactorError(null); }
      else { setRefactorResult(null); setRefactorError(d.error ?? "Entitas tidak ditemukan"); }
    } catch {
      setRefactorResult(null);
      setRefactorError("Backend tidak dapat dijangkau");
    } finally { setRefactorLoading(false); }
  }

  // ponytail: satu-satunya tempat yang menyentuh angka dari backend. Backend
  // boleh kirim field ini hilang; `num` yangpegang, bukan setiap call site.
  const ScoreBar = ({ label, value }: { label: string; value: unknown }) => {
    const n = num(value);
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-[10px]">
          <span className="text-slate-400">{label}</span>
          <span className="text-slate-300 font-mono">{n.toFixed(1)}</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-800">
          <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${Math.min(100, Math.max(0, (n / 10) * 100))}%` }} />
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-1 overflow-hidden bg-[#080d14]">
      {/* Left — Repo Tree */}
      <div className="w-52 shrink-0 flex flex-col border-r border-slate-800/60 bg-[#0d1117] overflow-hidden">
        <div className="px-3 py-3 border-b border-slate-800/60">
          <div className="text-xs font-semibold text-white mb-2">Repository Tree</div>
          <div className="flex items-center gap-2 bg-slate-800/60 border border-slate-700/60 rounded-lg px-2 py-1.5">
            <svg className="w-3 h-3 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="text-[10px] text-slate-600">Search files...</span>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {treeError ? (
            <div className="px-3 py-4 text-[10px] text-red-400">{treeError}</div>
          ) : tree.length === 0 ? (
            <div className="px-3 py-4 text-[10px] text-slate-600">
              {treeLoading ? "Loading tree..." : !USE_LIVE ? "Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true." : "Graph kosong. POST /understand_repo untuk ingest."}
            </div>
          ) : (
            tree.map((node) => (
              <button
                key={node.id}
                onClick={() => {
                  if (node.type === "dir") return;
                  setSelectedFile(node.id);
                  setArtifactPath(node.id);
                  setExplainTopic(`How does ${node.name} work?`);
                }}
                className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] text-left transition-colors ${
                  selectedFile === node.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800/60"
                }`}
                style={{ paddingLeft: `${12 + node.depth * 12}px` }}
              >
                <span>{node.type === "dir" ? "&#128193;" : node.type === "doc" ? "&#128196;" : "&#128462;"}</span>
                <span className="truncate">{node.name}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Center — Explain Topic */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-white">Cortex</h1>
          <span className="text-[10px] px-2.5 py-1 rounded-full bg-purple-500/20 text-purple-400 border border-purple-500/30 font-bold">REVIEW MODE</span>
        </div>

        {/* Target analisis. Cortex menjawab dari graph target yang aktif, jadi
            ganti target di sini mengganti konteks semua jawaban. */}
        <details className="rounded-xl border border-slate-800 bg-slate-900/30 px-3 py-2">
          <summary className="cursor-pointer text-[11px] text-slate-400 select-none">
            {activeTarget
              ? `Target: ${activeTarget.label}`
              : "Belum ada target analisis"}
          </summary>
          <div className="mt-3">
            <TargetPicker compact />
          </div>
        </details>

        {/* Provider + model. Dulu ditulis mati sebagai openai:gpt-4o, padahal
            llm_providers tidak punya baris itu, jadi chat selalu 404. */}
        <ProviderSelect
          providerId={chatProviderId}
          model={chatModel}
          onChange={(id, m) => {
            setChatProviderId(id);
            setChatModel(m);
          }}
        />

        {/* Artefak dari Settings. Isinya TIDAK dikirim sampai tombol di bawah
            ditekan - untuk folder lokal ini penting, karena isinya dibaca di
            browser dan tidak pernah lewat backend tanpa stringify. */}
        {artifact && (
          <div className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-purple-500/40 bg-purple-500/10 px-2 py-0.5 text-[9px] uppercase tracking-wide text-purple-300">
                {artifact.source === "local" ? "Folder lokal" : "GitHub"}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-300">
                {artifact.label}
              </span>
              <button
                type="button"
                onClick={() => setArtifactPath(artifact.content)}
                className="rounded-lg border border-slate-700/60 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800/60"
              >
                Pakai untuk review
              </button>
              <button
                type="button"
                onClick={() => clearArtifact()}
                className="rounded-lg border border-slate-700/60 px-3 py-1 text-xs text-slate-400 hover:bg-slate-800/60"
              >
                Buang
              </button>
            </div>
            <p className="text-[10px] text-slate-500">
              {artifact.content.length.toLocaleString("id-ID")} karakter. &quot;Pakai untuk
              review&quot; hanya mengisi kolom artefak; belum ada yang dikirim ke LLM sampai kamu menekan Review Artifact.
            </p>
          </div>
        )}

        {/* LLM Chat Panel - Explain, Review, Refactor */}
        <LLMChatPanel
          providerId={chatProviderId}
          model={chatModel}
          onExplain={runExplain}
          onReview={runReview}
          onRefactor={runSuggestRefactor}
        />

        {/* Hasil tombol Explain / Review di panel chat. Sebelumnya
            runExplain dan runReview mengisi state tapi tidak ada yang merender,
            jadi klik tombolnya kelihatan tidak terjadi apa-apa. */}
        {(explainError || explainResult) && (
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="text-sm font-semibold text-white">Explain</div>
            {explainError ? (
              <div className="text-[10px] text-red-400">{explainError}</div>
            ) : explainResult ? (
              <div className="space-y-2">
                {explainResult.definition && (
                  <p className="text-[11px] text-slate-300">{explainResult.definition}</p>
                )}
                {explainResult.mental_model && (
                  <p className="text-[10px] text-slate-400 italic">{explainResult.mental_model}</p>
                )}
                {explainResult.complexity_note && (
                  <p className="text-[10px] text-slate-500">{explainResult.complexity_note}</p>
                )}
                {explainResult.how_to_use && (
                  <p className="text-[10px] text-slate-400">{explainResult.how_to_use}</p>
                )}
                {explainResult.example && (
                  <pre className="whitespace-pre-wrap break-words text-[10px] font-mono text-slate-400 bg-slate-800/40 rounded p-2">
                    {explainResult.example}
                  </pre>
                )}
              </div>
            ) : null}
          </div>
        )}

        {(reviewError || reviewResult) && (
          <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-white">Review Artifact</div>
              {reviewResult?.artifact && (
                <span className="truncate font-mono text-[10px] text-slate-500 max-w-48">
                  {reviewResult.artifact}
                </span>
              )}
            </div>
            {reviewError ? (
              <div className="text-[10px] text-red-400">{reviewError}</div>
            ) : reviewResult ? (
              <div className="space-y-2">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                  {([
                    ["Completeness", reviewResult.completeness],
                    ["Clarity", reviewResult.clarity],
                    ["Vs Spec", reviewResult.correctness_vs_spec],
                    ["Risk", reviewResult.risk],
                  ] as const).map(([label, value]) => (
                    <div key={label} className="bg-slate-800/40 rounded-lg border border-slate-700/60 py-2 px-2">
                      <div className="text-sm font-bold font-mono text-slate-200">
                        {value.toFixed(1)}
                      </div>
                      <div className="text-[9px] text-slate-500 uppercase tracking-wide">
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
                {reviewResult.verdict && (
                  <div className="text-[10px]">
                    <span className="text-slate-500">Verdict: </span>
                    <span
                      className={
                        reviewResult.verdict === "pass"
                          ? "text-emerald-400"
                          : reviewResult.verdict === "warn"
                            ? "text-amber-400"
                            : "text-red-400"
                      }
                    >
                      {reviewResult.verdict}
                    </span>
                  </div>
                )}
                {reviewResult.risk_findings && reviewResult.risk_findings.length > 0 && (
                  <div className="space-y-1">
                    <div className="text-[9px] text-slate-500 uppercase tracking-wide">
                      Risk findings
                    </div>
                    {reviewResult.risk_findings.map((f, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="shrink-0 px-1.5 py-0.5 rounded-full bg-slate-700/60 text-slate-400 font-bold text-[9px] uppercase">
                          {f.severity ?? "info"}
                        </span>
                        <span className="text-[10px] text-slate-300">
                          {f.message ?? JSON.stringify(f)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {reviewResult.notes && Object.keys(reviewResult.notes).length > 0 && (
                  <div className="flex flex-wrap gap-2 text-[10px] font-mono text-slate-500">
                    {Object.entries(reviewResult.notes).map(([k, v]) => (
                      <span key={k}>
                        {k}: {num(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}

        {/* Repo Health — GET /repo_health */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-white">Repo Health</div>
            {health && (
              <div className="flex items-baseline gap-2">
                <span className={`text-2xl font-bold font-mono ${healthClass(health.health_score)}`}>
                  {health.health_score.toFixed(1)}
                </span>
                <span className="text-[10px] text-slate-500">/100</span>
              </div>
            )}
          </div>

          {healthError ? (
            <div className="text-[10px] text-red-400">{healthError}</div>
          ) : !USE_LIVE ? (
            <div className="text-[10px] text-slate-600">Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true.</div>
          ) : !health ? (
            <div className="text-[10px] text-slate-600">Memuat health report…</div>
          ) : (
            <div className="space-y-3">
              <div className="text-xs text-slate-400">{health.summary}</div>
              <div className="grid grid-cols-4 gap-2 text-center">
                {[
                  { label: "Files", value: health.total_files },
                  { label: "Documented", value: `${health.doc_coverage_percent}%` },
                  { label: "Dead code", value: health.dead_code_count },
                  { label: "Complex", value: health.high_complexity_count },
                ].map((s) => (
                  <div key={s.label} className="bg-slate-800/40 rounded-lg border border-slate-700/60 py-2">
                    <div className="text-sm font-bold font-mono text-slate-200">{s.value}</div>
                    <div className="text-[9px] text-slate-500 uppercase tracking-wide">{s.label}</div>
                  </div>
                ))}
              </div>
              {health.hub_nodes.length > 0 && (
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Hub nodes</div>
                  <div className="flex flex-wrap gap-1.5">
                    {health.hub_nodes.map((n) => (
                      <span key={n.id} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/60 text-slate-300 font-mono">
                        {n.name} <span className="text-slate-500">Â·{n.degree}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Complexity Ranking — GET /complexity_report */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-white">Complexity Ranking</div>
            {complexity && (
              <div className="flex items-center gap-2 text-[10px] font-mono">
                <span className="text-red-400">{complexity.critical_count} crit</span>
                <span className="text-orange-400">{complexity.high_count} high</span>
                <span className="text-yellow-400">{complexity.medium_count} med</span>
              </div>
            )}
          </div>

          {complexityError ? (
            <div className="text-[10px] text-red-400">{complexityError}</div>
          ) : !USE_LIVE ? (
            <div className="text-[10px] text-slate-600">Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true.</div>
          ) : !complexity ? (
            <div className="text-[10px] text-slate-600">Memuat ranking…</div>
          ) : complexity.results.length === 0 ? (
            <div className="text-[10px] text-slate-600">
              Belum ada simbol terindeks. POST /understand_repo untuk ingest.
            </div>
          ) : (
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-slate-500 uppercase tracking-wide text-left">
                  <th className="py-1 font-normal">Symbol</th>
                  <th className="py-1 font-normal w-12">Cx</th>
                  <th className="py-1 font-normal w-12">Lines</th>
                  <th className="py-1 font-normal w-16">Risk</th>
                </tr>
              </thead>
              <tbody className="font-mono text-slate-300">
                {complexity.results.map((row) => (
                  <tr key={row.id} className="border-t border-slate-800/60">
                    <td className="py-1 pr-2 truncate">
                      {row.name}
                      {row.file && <span className="text-slate-600"> Â· {row.file}:{row.line}</span>}
                    </td>
                    <td className="py-1">{row.complexity}</td>
                    <td className="py-1 text-slate-500">{row.lines}</td>
                    <td className="py-1">
                      <span className={`px-1.5 py-0.5 rounded-full font-bold ${RISK_CLASS[row.risk_level] ?? "bg-slate-700/60 text-slate-400"}`}>
                        {row.risk_level}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Find Path — POST /find_path */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="text-sm font-semibold text-white">Find Path</div>
          <div className="flex gap-2">
            <input
              value={pathFrom}
              onChange={(e) => setPathFrom(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runFindPath()}
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600 font-mono"
              placeholder="from node"
            />
            <span className="self-center text-slate-600 text-xs">&rarr;</span>
            <input
              value={pathTo}
              onChange={(e) => setPathTo(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runFindPath()}
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600 font-mono"
              placeholder="to node"
            />
            <button onClick={runFindPath} disabled={pathLoading || !USE_LIVE}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold disabled:opacity-50 transition-colors">
              {pathLoading ? "…" : "Trace"}
            </button>
          </div>

          {pathError ? (
            <div className="text-[10px] text-red-400">{pathError}</div>
          ) : !USE_LIVE ? (
            <div className="text-[10px] text-slate-600">Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true.</div>
          ) : pathResult ? (
            <div className="space-y-2 pt-2 border-t border-slate-800/60">
              <div className="text-[10px] text-slate-500">
                {pathResult.path_length} hop Â· {pathResult.direction}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-mono">
                {pathResult.path.map((n, i) => (
                  <span key={n.id} className="flex items-center gap-1.5">
                    {i > 0 && (
                      <span className="text-slate-600">
                        {pathResult.edges[i - 1]?.relationship ?? "&rarr;"}
                        {pathResult.edges[i - 1]?.traversed === "reverse" ? " (rev)" : ""}
                      </span>
                    )}
                    <span className="px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/60 text-slate-300">
                      {n.name}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {/* Refactor Suggestions — POST /suggest_refactor */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="text-sm font-semibold text-white">Refactor Suggestions</div>
          <div className="flex gap-2">
            <input
              value={refactorTarget}
              onChange={(e) => setRefactorTarget(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSuggestRefactor()}
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600 font-mono"
              placeholder="entity name"
            />
            <button onClick={runSuggestRefactor} disabled={refactorLoading || !USE_LIVE}
              className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold disabled:opacity-50 transition-colors">
              {refactorLoading ? "…" : "Suggest"}
            </button>
          </div>

          {refactorError ? (
            <div className="text-[10px] text-red-400">{refactorError}</div>
          ) : !USE_LIVE ? (
            <div className="text-[10px] text-slate-600">Live data OFF — set NEXT_PUBLIC_USE_LIVE_SSE=true.</div>
          ) : refactorResult ? (
            <div className="space-y-2 pt-2 border-t border-slate-800/60">
              <div className="flex flex-wrap gap-2 text-[10px] font-mono text-slate-500">
                <span className="text-slate-300">{refactorResult.node}</span>
                <span>cx {refactorResult.metrics.complexity}</span>
                <span>{refactorResult.metrics.lines} lines</span>
                <span>deg {refactorResult.metrics.degree}</span>
                <span>{refactorResult.metrics.has_documentation ? "documented" : "no docs"}</span>
              </div>
              {refactorResult.suggestions.map((s, i) => (
                <div key={`${s.type}-${i}`} className="flex items-start gap-2">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded-full font-bold text-[9px] uppercase ${PRIORITY_CLASS[s.priority] ?? "bg-slate-700/60 text-slate-400"}`}>
                    {s.priority}
                  </span>
                  <span className="text-[10px] text-slate-300">{s.message}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {/* Right — Graph Context mini */}
      <div className="w-56 shrink-0 border-l border-slate-800/60 bg-[#0d1117] p-3 overflow-y-auto space-y-3">
        <div className="text-xs font-semibold text-white">Graph Context</div>
        <div className="bg-slate-800/40 rounded-xl border border-slate-700/60 h-40 flex items-center justify-center">
          <span className="text-[10px] text-slate-600">Mini graph preview</span>
        </div>
        <div className="text-[10px] text-slate-500">Selected: <span className="text-slate-300">{selectedFile ?? "none"}</span></div>
      </div>
    </div>
  );
}
