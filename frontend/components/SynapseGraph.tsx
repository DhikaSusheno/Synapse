"use client";

// components/SynapseGraph.tsx
// FE-1 @nabilfauzandafa - Force-directed live graph
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

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

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
}

// ─── Canvas pulse/blink renderer ────────────────────────────────────────────
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

// ─── Hook animasi waktu ─────────────────────────────────────────────────
function useAnimationTime(): number {
  const [t, setT] = useState(0);
  const rafRef = useRef<number>(0);
  const lastRef = useRef<number>(0);

  useEffect(() => {
    const tick = (now: number) => {
      const dt = lastRef.current ? (now - lastRef.current) / 1000 : 0;
      lastRef.current = now;
      setT((prev) => prev + dt);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return t;
}

// ─── Hook: load initial graph dari backend ───────────────────────────────────
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

        // nodes dari backend: { id, type, name, meta_json }
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

        // edges dari backend: { source_id, target_id, relationship }
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
        // backend offline — tetap pakai mock
      }
    }
    load();
  }, [enabled, setNodes, setLinks]);
}

// ─── Komponen utama ──────────────────────────────────────────────────────────
export default function SynapseGraph({ onNodeClick }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>(USE_LIVE ? [] : MOCK_NODES);
  const [links, setLinks] = useState<GraphLink[]>(USE_LIVE ? [] : MOCK_LINKS);
  const [ingestProgress, setIngestProgress] = useState<IngestProgress | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const animTime = useAnimationTime();
  const animTimeRef = useRef(animTime);
  animTimeRef.current = animTime;

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

  // Initial load dari backend (hanya saat LIVE)
  useInitialGraph(setNodes, setLinks, USE_LIVE);

  // Fungsi update status node
  const handleNodeStatusUpdate = useCallback(
    (nodeId: string, status: GraphNode["status"]) => {
      setNodes((prev) => {
        const exists = prev.find((n) => n.id === nodeId);
        if (exists) {
          return prev.map((n) => (n.id === nodeId ? { ...n, status } : n));
        }
        // Node baru dari SSE (operasi baru yang diproposekan)
        return [
          ...prev,
          { id: nodeId, name: nodeId, type: "operation" as const, status },
        ];
      });
    },
    []
  );

  // Fungsi tambah/update node dari SSE graph_update
  const handleGraphUpdate = useCallback((newNodes: GraphNode[]) => {
    setNodes((prev) => {
      const existingIds = new Set(prev.map((n) => n.id));
      const toAdd = newNodes.filter((n) => !existingIds.has(n.id));
      return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
    });
  }, []);

  // Mock simulation (aktif saat USE_LIVE = false)
  useMockSimulation(handleNodeStatusUpdate, !USE_LIVE);

  // Live SSE
  useSSE({
    onNodeUpdate: handleNodeStatusUpdate,
    onGraphUpdate: handleGraphUpdate,
    onIngestProgress: setIngestProgress,
    enabled: USE_LIVE,
  });

  // Hapus progress overlay setelah 3 detik tidak ada update
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
    []
  );

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
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {label}
          </span>
        ))}
        <span className="text-slate-400 font-semibold mt-2 mb-1">Operation</span>
        {(
          [
            ["#fbbf24", "Pending ⏳ (pulse)"],
            ["#38bdf8", "Approved"],
            ["#fb923c", "Executing ⚡"],
            ["#22c55e", "Verified ✅"],
            ["#ef4444", "Failed / Rolled back 🔁"],
          ] as [string, string][]
        ).map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>

      {/* Mode badge */}
      <div className="absolute top-3 right-3 z-10">
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-mono ${
            USE_LIVE ? "bg-green-900 text-green-300" : "bg-yellow-900 text-yellow-300"
          }`}
        >
          {USE_LIVE ? "🟢 LIVE" : "🟡 MOCK"}
        </span>
      </div>

      {/* Ingest progress overlay */}
      {ingestProgress && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-slate-800/90 backdrop-blur rounded-lg px-4 py-2 text-xs text-slate-300 flex items-center gap-2 shadow-lg">
          <span className="animate-spin inline-block">⧗</span>
          <span>
            Ingesting <span className="text-slate-100 font-mono">{ingestProgress.current_doc}</span>
            {ingestProgress.stats.files !== undefined && (
              <span className="text-slate-400">
                {" "}({ingestProgress.stats.files} files, {ingestProgress.stats.symbols} symbols)
              </span>
            )}
          </span>
        </div>
      )}

      {/* Empty state saat live mode dan graph kosong */}
      {USE_LIVE && nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-500">
          <span className="text-2xl">🧠</span>
          <span className="text-sm">Graph kosong. Panggil <code className="bg-slate-800 px-1 rounded">POST /understand_repo</code> untuk mulai ingest.</span>
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
