"use client";

import { useState } from "react";
import type { FileTreeNode } from "@/lib/fileTree";

export type { FileTreeNode };

interface RowProps {
  node: FileTreeNode;
  depth: number;
  query: string;
  collapsed: Record<string, boolean>;
  toggle: (id: string) => void;
  onFileClick?: (node: FileTreeNode) => void;
}

function keep(node: FileTreeNode, query: string): boolean {
  if (!query) return true;
  if (node.name.toLowerCase().includes(query)) return true;
  return (node.children ?? []).some((child) => keep(child, query));
}

function Row({ node, depth, query, collapsed, toggle, onFileClick }: RowProps) {
  const open = !collapsed[node.id];
  const kids = node.children ?? [];
  const hasKids = kids.length > 0;

  const select = () => {
    if (hasKids) {
      toggle(node.id);
      return;
    }
    onFileClick?.(node);
  };

  return (
    <div>
      <div
        role="treeitem"
        aria-selected={false}
        aria-expanded={hasKids ? open : undefined}
        aria-level={depth + 1}
        tabIndex={0}
        onClick={select}
        onKeyDown={(e) => {
          if (e.key !== "Enter" && e.key !== " ") return;
          e.preventDefault();
          select();
        }}
        className="flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 hover:bg-slate-800/40"
        style={{ paddingLeft: depth * 12 }}
      >
        <span className="w-3 text-slate-500">{hasKids ? (open ? "▾" : "▸") : ""}</span>
        <span aria-hidden="true">{node.type === "dir" ? "📁" : "📄"}</span>
        <span className="truncate text-[11px] text-slate-200">{node.name}</span>
      </div>
      {hasKids && open ? (
        <div role="group">
          {kids
            .filter((child) => keep(child, query))
            .map((child) => (
              <Row
                key={child.id}
                node={child}
                depth={depth + 1}
                query={query}
                collapsed={collapsed}
                toggle={toggle}
                onFileClick={onFileClick}
              />
            ))}
        </div>
      ) : null}
    </div>
  );
}

export default function FileTreeBrowser({
  nodes,
  onFileClick,
  emptyLabel = "No files.",
}: {
  nodes: FileTreeNode[];
  onFileClick?: (node: FileTreeNode) => void;
  emptyLabel?: string;
}) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const needle = query.trim().toLowerCase();
  const shown = nodes.filter((node) => keep(node, needle));

  const toggle = (id: string) => {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="flex h-full flex-col">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter files..."
        className="mb-2 rounded border border-slate-700 bg-slate-800/60 px-2 py-1 text-xs text-slate-200 outline-none"
      />
      <div className="min-h-0 flex-1 overflow-auto" role="tree" aria-label="File tree">
        {shown.length === 0 ? (
          <p className="px-1 py-2 text-[10px] text-slate-500">{emptyLabel}</p>
        ) : (
          shown.map((node) => (
            <Row
              key={node.id}
              node={node}
              depth={0}
              query={needle}
              collapsed={collapsed}
              toggle={toggle}
              onFileClick={onFileClick}
            />
          ))
        )}
      </div>
    </div>
  );
}
