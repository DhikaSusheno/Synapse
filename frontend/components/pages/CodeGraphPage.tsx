"use client";
// components/pages/CodeGraphPage.tsx
// Halaman Code Graph — sesuai design section 1
// FE-1 @nabilfauzandafa

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { GraphNode } from "@/lib/types";

const SynapseGraph = dynamic(() => import("@/components/SynapseGraph"), {
  ssr: false,
  loading: () => <div className="flex items-center justify-center h-full text-slate-400 text-sm">Loading graph...</div>,
});

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const USE_LIVE    = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

const FILTER_TYPES = ["All", "File", "Symbol", "Dependency", "Doc"] as const;

interface SSELine { ts: string; message: string; }

function useLiveFeed(): SSELine[] {
  const [lines, setLines] = useState<SSELine[]>([]);
  useEffect(() => {
    if (!USE_LIVE) return;
    const es = new EventSource(`${BACKEND_URL}/stream`);
    es.onmessage = (e) => {
      try {
        const p = JSON.parse(e.data);
        if (p.event === "heartbeat" || p.event === "connected") return;
        const msg = p.data.operation_id
          ? `op ${String(p.data.operation_id).slice(0, 10)}… ${p.data.tool_name ?? p.event}`
          : p.data.current_doc ? `ingest: ${p.data.current_doc}` : p.event;
        setLines((prev) => [{ ts: new Date().toLocaleTimeString(), message: msg }, ...prev.slice(0, 9)]);
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);
  return lines;
}

interface Props {
  onNodeClick: (node: GraphNode) => void;
  onNodeCount: (n: number, l: number) => void;
  nodeCount: number;
  edgeCount: number;
}

export default function CodeGraphPage({ onNodeClick, onNodeCount, nodeCount, edgeCount }: Props) {
  const [filterType, setFilterType] = useState<typeof FILTER_TYPES[number]>("All");
  const [search, setSearch]         = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const liveFeed = useLiveFeed();

  function handleNodeClick(node: GraphNode) {
    setSelectedNode(node);
    onNodeClick(node);
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Graph area */}
      <div className="flex flex-col flex-1 overflow-hidden bg-[#080d14]">
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800/60 bg-[#0d1117] shrink-0">
          <div>
            <div className="text-sm font-semibold text-white">Code Graph</div>
            <div className="text-[10px] text-slate-500">Hybrid AST + semantic understanding</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-[10px] text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400"></span>
              {nodeCount}n / {edgeCount}e
            </span>
          </div>
        </div>

        {/* Search + filter */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800/40 bg-[#0d1117] shrink-0">
          <div className="flex items-center gap-2 flex-1 bg-slate-800/60 border border-slate-700/60 rounded-lg px-2.5 py-1.5">
            <svg className="w-3 h-3 text-slate-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search files, symbols, docs..."
              className="bg-transparent text-xs text-slate-300 placeholder-slate-600 outline-none flex-1"
            />
          </div>
          <div className="flex gap-1">
            {FILTER_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => setFilterType(t)}
                className={`text-[10px] px-2.5 py-1 rounded-lg transition-colors ${
                  filterType === t ? "bg-blue-600/30 text-blue-400 border border-blue-500/40" : "text-slate-500 hover:text-slate-300 border border-transparent"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Graph canvas */}
        <div className="flex-1 overflow-hidden">
          <SynapseGraph onNodeClick={handleNodeClick} onNodeCount={onNodeCount} />
        </div>
      </div>

      {/* Right panel — selected node + live feed */}
      <aside className="w-60 shrink-0 flex flex-col border-l border-slate-800/60 bg-[#0d1117] overflow-hidden">
        {/* Selected Node */}
        <div className="p-3 border-b border-slate-800/60">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">Selected Node</div>
          {selectedNode ? (
            <div className="bg-slate-800/40 rounded-xl border border-slate-700/60 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="w-6 h-6 rounded bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-[10px] text-blue-400 font-bold shrink-0">
                  {selectedNode.type === "file" ? "F" : selectedNode.type === "symbol" ? "S" : selectedNode.type === "doc" ? "D" : "N"}
                </span>
                <span className="text-xs font-medium text-white truncate">{selectedNode.name}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px]">
                <span className="text-slate-500">Type</span>
                <span className="text-slate-300">{selectedNode.type}</span>
                <span className="text-slate-500">Status</span>
                <span className="text-slate-300">{selectedNode.status}</span>
                {selectedNode.meta?.complexity !== undefined && (
                  <>
                    <span className="text-slate-500">Complexity</span>
                    <span className="text-slate-300">{String(selectedNode.meta.complexity)}</span>
                  </>
                )}
              </div>
              <button className="w-full text-[10px] text-slate-400 border border-slate-700/60 rounded-lg py-1.5 hover:text-slate-200 hover:border-slate-600 transition-colors">
                View Details &#8594;
              </button>
            </div>
          ) : (
            <div className="text-[10px] text-slate-600 text-center py-4">
              Click a node to inspect
            </div>
          )}
        </div>

        {/* Live SSE Activity */}
        <div className="flex-1 overflow-y-auto p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] text-slate-500 uppercase tracking-wide">Live SSE Activity</span>
            <span className="flex items-center gap-1 text-[10px] text-green-400">
              <span className="w-1 h-1 rounded-full bg-green-400"></span>
              {USE_LIVE ? "Live" : "Mock"}
            </span>
          </div>
          {liveFeed.length === 0 ? (
            <div className="text-[10px] text-slate-600 text-center py-4">Waiting for events…</div>
          ) : (
            <div className="space-y-1.5">
              {liveFeed.map((line, i) => (
                <div key={i} className="flex gap-2 text-[10px]">
                  <span className="text-slate-600 font-mono shrink-0">{line.ts}</span>
                  <span className="text-slate-400 truncate">{line.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
