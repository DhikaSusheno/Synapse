"use client";
// components/pages/CortexPage.tsx
// Halaman Cortex — sesuai design section 3
// FE-1 @nabilfauzandafa

import { useEffect, useState } from "react";
import type { GraphNode } from "@/lib/types";

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

const MOCK_TREE_NODES = [
  { id: "src", name: "src/", type: "dir", depth: 0 },
  { id: "app", name: "app.py", type: "file", depth: 1 },
  { id: "api", name: "api/", type: "dir", depth: 1 },
  { id: "routes", name: "routes.py", type: "file", depth: 2 },
  { id: "schemas", name: "schemas.py", type: "file", depth: 2 },
  { id: "core", name: "core/", type: "dir", depth: 1 },
  { id: "cortex_py", name: "cortex.py", type: "file", depth: 2 },
  { id: "guardian_py", name: "guardian.py", type: "file", depth: 2 },
  { id: "database", name: "database/", type: "dir", depth: 1 },
  { id: "database_py", name: "database.py", type: "file", depth: 2 },
  { id: "models_py", name: "models.py", type: "file", depth: 2 },
  { id: "utils", name: "utils/", type: "dir", depth: 1 },
  { id: "parser_py", name: "parser.py", type: "file", depth: 2 },
  { id: "readme", name: "README.md", type: "doc", depth: 0 },
];

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
  const [selectedFile, setSelectedFile] = useState("cortex_py");
  const [explainTopic, setExplainTopic] = useState("How does the guardian module work?");
  const [explainResult, setExplainResult] = useState<ExplainResult | null>(USE_LIVE ? null : MOCK_EXPLAIN);
  const [explainLoading, setExplainLoading] = useState(false);
  const [artifactPath, setArtifactPath] = useState("backend/guardian.py");
  const [reviewResult, setReviewResult] = useState<ReviewScores | null>(USE_LIVE ? null : MOCK_REVIEW);
  const [reviewLoading, setReviewLoading] = useState(false);

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
          {MOCK_TREE_NODES.map((node) => (
            <button
              key={node.id}
              onClick={() => node.type !== "dir" && setSelectedFile(node.id)}
              className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] transition-colors ${
                selectedFile === node.id ? "bg-blue-600/20 text-blue-400" : "text-slate-400 hover:bg-slate-800/60"
              }`}
              style={{ paddingLeft: `${12 + node.depth * 12}px` }}
            >
              <span>{node.type === "dir" ? "&#128193;" : node.type === "doc" ? "&#128196;" : "&#128462;"}</span>
              <span className="truncate">{node.name}</span>
            </button>
          ))}
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
      </div>

      {/* Right — Graph Context mini */}
      <div className="w-56 shrink-0 border-l border-slate-800/60 bg-[#0d1117] p-3 overflow-y-auto space-y-3">
        <div className="text-xs font-semibold text-white">Graph Context</div>
        <div className="bg-slate-800/40 rounded-xl border border-slate-700/60 h-40 flex items-center justify-center">
          <span className="text-[10px] text-slate-600">Mini graph preview</span>
        </div>
        <div className="text-[10px] text-slate-500">Selected: <span className="text-slate-300">{selectedFile}</span></div>
      </div>
    </div>
  );
}
