"use client";

// components/SynapseGraph.tsx
// FE-1 @nabilfauzandafa — Force-directed live graph
//
// Mode mock  : useMockSimulation aktif, useSSE nonaktif
// Mode live  : set env NEXT_PUBLIC_USE_LIVE_SSE=true

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { MOCK_NODES, MOCK_LINKS } from "@/lib/mockData";
import { getNodeColor, getNodeSize, getNodeLabel, getLinkColor } from "@/lib/nodeVisuals";
import { useMockSimulation } from "@/hooks/useMockSimulation";
import { useSSE } from "@/hooks/useSSE";
import type { GraphNode, GraphLink } from "@/lib/types";

// react-force-graph-2d tidak support SSR
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400">
      Loading graph engine…
    </div>
  ),
});

const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

// ─── Tipe internal yang diterima ForceGraph2D ───────────────────────────────
interface RawNode extends GraphNode {
  x?: number;
  y?: number;
}

interface Props {
  onNodeClick?: (node: GraphNode) => void;
}

export default function SynapseGraph({ onNodeClick }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>(MOCK_NODES);
  const [links, setLinks] = useState<GraphLink[]>(MOCK_LINKS);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Sesuaikan ukuran canvas dengan container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setDimensions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Fungsi update status node — dipakai oleh mock & SSE
  const handleNodeStatusUpdate = useCallback(
    (nodeId: string, status: GraphNode["status"]) => {
      setNodes((prev) =>
        prev.map((n) => (n.id === nodeId ? { ...n, status } : n))
      );
    },
    []
  );

  // Fungsi tambah node baru dari SSE graph_update
  const handleGraphUpdate = useCallback((newNodes: GraphNode[]) => {
    setNodes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const toAdd = newNodes.filter((n) => !existingIds.has(n.id));
      return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
    });
  }, []);

  // Mock simulation (aktif saat USE_LIVE = false)
  useMockSimulation(handleNodeStatusUpdate, !USE_LIVE);

  // Live SSE (aktif saat USE_LIVE = true)
  useSSE({
    onNodeUpdate: handleNodeStatusUpdate,
    onGraphUpdate: handleGraphUpdate,
    enabled: USE_LIVE,
  });

  const graphData = { nodes, links };

  return (
    <div ref={containerRef} className="w-full h-full relative">
      {/* Legend */}
      <div className="absolute top-3 left-3 z-10 flex flex-col gap-1 bg-slate-900/80 backdrop-blur rounded-lg px-3 py-2 text-xs">
        <span className="text-slate-400 font-semibold mb-1">Node</span>
        {(
          [
            ["#60a5fa", "File"],
            ["#a78bfa", "Symbol"],
            ["#64748b", "Dependency"],
            ["#34d399", "Doc"],
          ] as [string, string][]
        ).map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: color }}
            />
            {label}
          </span>
        ))}
        <span className="text-slate-400 font-semibold mt-2 mb-1">Operation</span>
        {(
          [
            ["#fbbf24", "Pending ⏳"],
            ["#38bdf8", "Approved"],
            ["#fb923c", "Executing ⚡"],
            ["#22c55e", "Verified ✅"],
            ["#ef4444", "Failed / Rolled back"],
          ] as [string, string][]
        ).map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: color }}
            />
            {label}
          </span>
        ))}
      </div>

      {/* Mode badge */}
      <div className="absolute top-3 right-3 z-10">
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-mono ${
            USE_LIVE
              ? "bg-green-900 text-green-300"
              : "bg-yellow-900 text-yellow-300"
          }`}
        >
          {USE_LIVE ? "● LIVE" : "◌ MOCK"}
        </span>
      </div>

      <ForceGraph2D
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="#0f172a"
        // Node rendering
        nodeLabel={(node) => getNodeLabel(node as RawNode)}
        nodeColor={(node) => getNodeColor(node as RawNode)}
        nodeVal={(node) => getNodeSize(node as RawNode)}
        // Edge rendering
        linkLabel={(link) => (link as unknown as GraphLink).relationship}
        linkColor={(link) => getLinkColor((link as unknown as GraphLink).relationship)}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkWidth={1.2}
        // Interaksi
        onNodeClick={(node) => onNodeClick?.(node as GraphNode)}
        // Fisika: node yang tidak terhubung tidak terlalu jauh menyebar
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
      />
    </div>
  );
}
