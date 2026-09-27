"use client";
// components/pages/CortexPage.tsx
// Halaman Cortex — sesuai design section 3
// FE-1 @nabilfauzandafa

import { useEffect, useState } from "react";
import { buildFileTree, type TreeNode } from "@/lib/derive";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
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
function useFileTree(enabled: boolean): { tree: TreeNode[]; loading: boolean; error: string | null } {
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    let cancelled = false;
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
  }, [enabled]);

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
  const { tree, loading: treeLoading, error: treeError } = useFileTree(USE_LIVE);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [explainTopic, setExplainTopic] = useState("How does the guardian module work?");
  const [explainResult, setExplainResult] = useState<ExplainResult | null>(USE_LIVE ? null : MOCK_EXPLAIN);
  const [explainLoading, setExplainLoading] = useState(false);
  const [artifactPath, setArtifactPath] = useState("backend/guardian.py");
  const [reviewResult, setReviewResult] = useState<ReviewScores | null>(USE_LIVE ? null : MOCK_REVIEW);
  const [reviewLoading, setReviewLoading] = useState(false);

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

    fetch(`${BACKEND_URL}/repo_health`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as RepoHealth) : Promise.reject(await errorDetail(r, "Gagal ambil /repo_health"))))
      .then((d) => { if (!cancelled) { setHealth(d); setHealthError(null); } })
      .catch((e: string) => { if (!cancelled) setHealthError(e); });

    fetch(`${BACKEND_URL}/complexity_report?top_n=10`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as ComplexityReport) : Promise.reject(await errorDetail(r, "Gagal ambil /complexity_report"))))
      .then((d) => { if (!cancelled) { setComplexity(d); setComplexityError(null); } })
      .catch((e: string) => { if (!cancelled) setComplexityError(e); });

    return () => { cancelled = true; };
  }, []);

  async function runExplain() {
    if (!USE_LIVE) { setExplainResult(MOCK_EXPLAIN); return; }
    setExplainLoading(true);
    try {
      const r = await fetch(`${BACKEND_URL}/explain_topic`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: explainTopic }),
      });
      const d = await r.json();
      if (d.ok) setExplainResult(d as ExplainResult);
    } catch { /* ignore */ } finally { setExplainLoading(false); }
  }

  async function runReview() {
    if (!USE_LIVE) { setReviewResult(MOCK_REVIEW); return; }
    setReviewLoading(true);
    try {
      const r = await fetch(`${BACKEND_URL}/review_artifact`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path_or_diff: artifactPath }),
      });
      const d = await r.json();
      if (d.ok) setReviewResult(d as ReviewScores);
    } catch { /* ignore */ } finally { setReviewLoading(false); }
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
      if (d.ok) { setPathResult(d as FindPathResult); setPathError(null); }
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
      if (d.ok) { setRefactorResult(d as RefactorResult); setRefactorError(null); }
      else { setRefactorResult(null); setRefactorError(d.error ?? "Entitas tidak ditemukan"); }
    } catch {
      setRefactorResult(null);
      setRefactorError("Backend tidak dapat dijangkau");
    } finally { setRefactorLoading(false); }
  }

  const ScoreBar = ({ label, value }: { label: string; value: number }) => (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300 font-mono">{value.toFixed(1)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-800">
        <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${(value / 10) * 100}%` }} />
      </div>
    </div>
  );

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

        {/* Explain Topic */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="text-sm font-semibold text-white">Explain Topic</div>
          <div className="flex gap-2">
            <input
              value={explainTopic}
              onChange={(e) => setExplainTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runExplain()}
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600"
              placeholder="How does the guardian module work?"
            />
            <button onClick={runExplain} disabled={explainLoading}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold disabled:opacity-50 transition-colors">
              {explainLoading ? "…" : "Explain"}
            </button>
          </div>

          {explainResult && (
            <div className="space-y-3 pt-2 border-t border-slate-800/60">
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Definition</div>
                <p className="text-xs text-slate-300">{explainResult.definition}</p>
              </div>
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Mental Model</div>
                <p className="text-xs text-slate-400 italic">{explainResult.mental_model}</p>
              </div>
              {explainResult.complexity_note && (
                <div className="text-xs text-yellow-400">{explainResult.complexity_note}</div>
              )}
              {explainResult.example && (
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Example</div>
                  <pre className="text-[10px] text-slate-300 bg-slate-900 rounded-lg p-3 overflow-x-auto">{explainResult.example}</pre>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Review Artifact */}
        <div className="bg-[#0d1117] rounded-xl border border-slate-800/60 p-4 space-y-3">
          <div className="text-sm font-semibold text-white">Review Artifact</div>
          <div className="flex gap-2">
            <input
              value={artifactPath}
              onChange={(e) => setArtifactPath(e.target.value)}
              className="flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 outline-none placeholder-slate-600 font-mono"
              placeholder="backend/guardian.py or paste diff..."
            />
            <button onClick={runReview} disabled={reviewLoading}
              className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold disabled:opacity-50 transition-colors">
              {reviewLoading ? "…" : "Run Review"}
            </button>
          </div>

          {reviewResult && (
            <div className="space-y-2 pt-2 border-t border-slate-800/60">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-slate-400">Verdict:</span>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                  reviewResult.verdict === "pass" ? "bg-green-500/20 text-green-400" :
                  reviewResult.verdict === "block" ? "bg-red-500/20 text-red-400" :
                  "bg-yellow-500/20 text-yellow-400"
                }`}>{reviewResult.verdict.toUpperCase()}</span>
              </div>
              <ScoreBar label="Completeness" value={reviewResult.completeness} />
              <ScoreBar label="Clarity" value={reviewResult.clarity} />
              <ScoreBar label="Correctness vs Spec" value={reviewResult.correctness_vs_spec} />
              <ScoreBar label="Risk" value={reviewResult.risk} />
            </div>
          )}
        </div>

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
                        {n.name} <span className="text-slate-500">·{n.degree}</span>
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
                      {row.file && <span className="text-slate-600"> · {row.file}:{row.line}</span>}
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
                {pathResult.path_length} hop · {pathResult.direction}
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
