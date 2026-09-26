"use client";

// components/SynapseGraph.tsx
// FE-1 @nabilfauzandafa - Force-directed live graph
// FE-2 @ShannWasHere - encoding fix (garbled emoji -> text labels)
//
// Mode mock : useMockSimulation aktif, useSSE nonaktif
// Mode live : set env NEXT_PUBLIC_USE_LIVE_SSE=true

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { MOCK_NODES, MOCK_LINKS } from "@/lib/mockData";
import { getNodeColor, getNodeSize, getNodeLabel, getLinkColor, hexToRgba } from "@/lib/nodeVisuals";
import { useMockSimulation } from "@/hooks/useMockSimulation";
import { useSSE, type IngestProgress } from "@/hooks/useSSE";
import type { GraphNode, GraphLink } from "@/lib/types";

// react-force-graph-2d tidak support SSR
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-slate-400">
      Loading graph engine...
    </div>
  ),
});

const USE_LIVE = process.env.NEXT_PUBLIC_USE_LIVE_SSE === "true";

interface RawNode extends GraphNode {
  x?: number;
  y?: number;
}

interface BackendEdge {
  source_id: string;
  target_id: string;
  relationship: GraphLink["relationship"];
}

interface Props {
  onNodeClick?: (node: GraphNode) => void;
  onNodeCount?: (nodes: number, links: number) => void;
}

// --- Canvas pulse/blink renderer ---
function drawNode(
  node: RawNode,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  animTime: number
) {
  const x = node.x ?? 0;
  const y = node.y ?? 0;
  const r = getNodeSize(node) / globalScale;
  const color = getNodeColor(node);

  // Pulse glow untuk pending (kuning)
  if (node.status === "pending") {
    const pulse = (Math.sin(animTime * Math.PI) + 1) / 2;
    const glowR = r * (1.8 + pulse * 1.2);
    const grad = ctx.createRadialGradient(x, y, r * 0.5, x, y, glowR);
    grad.addColorStop(0, hexToRgba("#fbbf24", 0.55 * pulse));
    grad.addColorStop(1, hexToRgba("#fbbf24", 0));
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, 2 * Math.PI);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Blink merah untuk failed & rolled_back
  if (node.status === "failed" || node.status === "rolled_back") {
    const blink = (Math.sin(animTime * 2 * Math.PI * 2) + 1) / 2;
    const glowR = r * (2.0 + blink * 0.8);
    const grad = ctx.createRadialGradient(x, y, r * 0.5, x, y, glowR);
    grad.addColorStop(0, hexToRgba("#ef4444", 0.7 * blink));
    grad.addColorStop(1, hexToRgba("#ef4444", 0));
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, 2 * Math.PI);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Glow oranye untuk executing
  if (node.status === "executing") {
    const pulse = (Math.sin(animTime * 1.5 * Math.PI) + 1) / 2;
    const glowR = r * (1.5 + pulse * 0.8);
    const grad = ctx.createRadialGradient(x, y, r * 0.4, x, y, glowR);
    grad.addColorStop(0, hexToRgba("#fb923c", 0.4 * pulse));
    grad.addColorStop(1, hexToRgba("#fb923c", 0));
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, 2 * Math.PI);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Lingkaran utama
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fillStyle = color;
  ctx.fill();

  // Ring tipis untuk operation node
  if (node.type === "operation") {
    ctx.beginPath();
    ctx.arc(x, y, r + 1.5 / globalScale, 0, 2 * Math.PI);
    ctx.strokeStyle = hexToRgba(color, 0.6);
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();
  }

  // Label
  const fontSize = Math.max(8 / globalScale, 1.5);
  ctx.font = `${fontSize}px Inter, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "rgba(241,245,249,0.85)";
  ctx.fillText(node.name, x, y + r + 2 / globalScale);
}

// --- Hook animasi waktu ---
// BUG-40: versi lama setState tiap frame (~60x/detik) → re-render SynapseGraph terus
// mentoring dan objek graphData baru tiap frame. animTime hanya dipakai di canvas
// draw callback, jadi cukup ref — tidak perlu memicu render sama sekali.
function useAnimationTimeRef(): React.MutableRefObject<number> {
  const timeRef = useRef(0);
  const rafRef = useRef<number>(0);
  const lastRef = useRef<number>(0);

  useEffect(() => {
    const tick = (now: number) => {
      const dt = lastRef.current ? (now - lastRef.current) / 1000 : 0;
      lastRef.current = now;
      timeRef.current += dt;
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return timeRef;
}

// --- Hook: load initial graph dari backend ---
function useInitialGraph(
  setNodes: React.Dispatch<React.SetStateAction<GraphNode[]>>,
  setLinks: React.Dispatch<React.SetStateAction<GraphLink[]>>,
  enabled: boolean
) {
  useEffect(() => {
    if (!enabled) return;
    async function load() {
      try {
        const res = await fetch("/api/graph");
        if (!res.ok) return;
        const data = await res.json();
        if (Array.isArray(data.nodes) && data.nodes.length > 0) {
          setNodes(
            data.nodes.map((n: { id: string; type: GraphNode["type"]; name: string }) => ({
              id: n.id,
              name: n.name,
              type: n.type ?? "file",
              status: "idle" as const,
            }))
          );
        }
        if (Array.isArray(data.edges) && data.edges.length > 0) {
          setLinks(
            data.edges.map((e: BackendEdge) => ({
              source: e.source_id,
              target: e.target_id,
              relationship: e.relationship,
            }))
          );
        }
      } catch {
        // backend offline - tetap pakai mock
      }
    }
    load();
  }, [enabled, setNodes, setLinks]);
}

// Legend entries: [color, label]
const NODE_LEGEND: [string, string][] = [
  ["#60a5fa", "File"],
  ["#a78bfa", "Symbol"],
  ["#64748b", "Dependency"],
  ["#34d399", "Doc"],
];

const OP_LEGEND: [string, string][] = [
  ["#fbbf24", "Pending (pulse)"],
  ["#38bdf8", "Approved"],
  ["#fb923c", "Executing..."],
  ["#22c55e", "Verified"],
  ["#ef4444", "Failed / Rolled back"],
];

// --- Komponen utama ---
export default function SynapseGraph({ onNodeClick, onNodeCount }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>(USE_LIVE ? [] : MOCK_NODES);
  const [links, setLinks] = useState<GraphLink[]>(USE_LIVE ? [] : MOCK_LINKS);
  const [ingestProgress, setIngestProgress] = useState<IngestProgress | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const animTimeRef = useAnimationTimeRef();

  // Kirim node/link count ke parent tiap kali berubah
  useEffect(() => {
    onNodeCount?.(nodes.length, links.length);
  }, [nodes.length, links.length, onNodeCount]);

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

  useInitialGraph(setNodes, setLinks, USE_LIVE);

  const handleNodeStatusUpdate = useCallback(
    (nodeId: string, status: GraphNode["status"]) => {
      setNodes((prev) => {
        const exists = prev.find((n) => n.id === nodeId);
        if (exists) return prev.map((n) => (n.id === nodeId ? { ...n, status } : n));
        return [...prev, { id: nodeId, name: nodeId, type: "operation" as const, status }];
      });
    },
    []
  );

  const handleGraphUpdate = useCallback((newNodes: GraphNode[]) => {
    setNodes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const toAdd = newNodes.filter((n) => !existingIds.has(n.id));
      return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
    });
  }, []);

  useMockSimulation(handleNodeStatusUpdate, !USE_LIVE);

  useSSE({
    onNodeUpdate: handleNodeStatusUpdate,
    onGraphUpdate: handleGraphUpdate,
    onIngestProgress: setIngestProgress,
    enabled: USE_LIVE,
  });

  useEffect(() => {
    if (!ingestProgress) return;
    const t = setTimeout(() => setIngestProgress(null), 3000);
    return () => clearTimeout(t);
  }, [ingestProgress]);

  const graphData = { nodes, links };

  const nodeCanvasObject = useCallback(
    (node: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
      drawNode(node as RawNode, ctx, globalScale, animTimeRef.current);
    },
    [animTimeRef]
  );

  return (
    <div ref={containerRef} className="w-full h-full relative">
      {/* Legend */}
      <div className="absolute top-3 left-3 z-10 flex flex-col gap-1 bg-slate-900/80 backdrop-blur rounded-lg px-3 py-2 text-xs">
        <span className="text-slate-400 font-semibold mb-1">Node</span>
        {NODE_LEGEND.map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {label}
          </span>
        ))}
        <span className="text-slate-400 font-semibold mt-2 mb-1">Operation</span>
        {OP_LEGEND.map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {label}
          </span>
        ))}
        {/* Node + Edge count */}
        <div className="mt-2 pt-2 border-t border-slate-700 text-slate-500 space-y-0.5">
          <div>{nodes.length} nodes</div>
          <div>{links.length} edges</div>
        </div>
      </div>

      {/* Mode badge */}
      <div className="absolute top-3 right-3 z-10">
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-mono ${
            USE_LIVE ? "bg-green-900 text-green-300" : "bg-yellow-900 text-yellow-300"
          }`}
        >
          {USE_LIVE ? "LIVE" : "MOCK"}
        </span>
      </div>

      {/* Ingest progress overlay */}
      {ingestProgress && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-slate-800/90 backdrop-blur rounded-lg px-4 py-2 text-xs text-slate-300 flex items-center gap-2 shadow-lg">
          <span className="inline-block animate-spin">&#9696;</span>
          <span>
            Ingesting{" "}
            <span className="text-slate-100 font-mono">{ingestProgress.current_doc}</span>
            {ingestProgress.stats.files !== undefined && (
              <span className="text-slate-400">
                {" "}({ingestProgress.stats.files} files,{" "}
                {ingestProgress.stats.symbols} symbols)
              </span>
            )}
          </span>
        </div>
      )}

      {/* Empty state saat live mode dan graph kosong */}
      {USE_LIVE && nodes.length === 0 && !ingestProgress && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-500 pointer-events-none">
          <span className="text-3xl">&#x1F4CA;</span>
          <span className="text-sm">
            Graph kosong.{" "}
            <code className="bg-slate-800 px-1 rounded text-slate-400">
              POST /understand_repo
            </code>{" "}
            untuk mulai ingest.
          </span>
        </div>
      )}

      <ForceGraph2D
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="#0f172a"
        nodeCanvasObject={nodeCanvasObject}
        nodeCanvasObjectMode={() => "replace"}
        nodeLabel={(node) => getNodeLabel(node as RawNode)}
        linkLabel={(link) => (link as unknown as GraphLink).relationship}
        linkColor={(link) => getLinkColor((link as unknown as GraphLink).relationship)}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkWidth={1.2}
        onNodeClick={(node) => onNodeClick?.(node as GraphNode)}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
      />
    </div>
  );
}