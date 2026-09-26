"""
cortex.py — BE-2 Masrendra
Tanggung jawab:
  - understand_repo(repo_path)   : ingest repo via tree-sitter AST + baca docs
  - explain_topic(topic)         : query graph + jawab dengan konteks file
  - review_artifact(path_or_diff): scoring 4 dimensi
  - repo_health()                : laporan kesehatan repo (unik: dead code + complexity)
  - find_path(from_node, to_node): cari jalur antar dua entitas di graph
  - complexity_report()          : ranking fungsi paling kompleks di repo
  - suggest_refactor(node_id)    : saran refactor berbasis graph connectivity
"""
import json
import uuid
import sqlite3
import re
from pathlib import Path
from datetime import datetime

import networkx as nx

from database import DB_PATH

# ---------------------------------------------------------------------------
# In-memory graph (networkx)
# ---------------------------------------------------------------------------

_graph: nx.DiGraph = nx.DiGraph()


def _rebuild_graph() -> nx.DiGraph:
    """Load ulang graph dari SQLite ke networkx."""
    g = nx.DiGraph()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for row in conn.execute("SELECT id, type, name, meta_json FROM nodes"):
        g.add_node(row["id"], type=row["type"], name=row["name"],
                   meta=json.loads(row["meta_json"] or "{}"))
    for row in conn.execute(
        "SELECT source_id, target_id, relationship, confidence FROM edges"
    ):
        g.add_edge(row["source_id"], row["target_id"],
                   relationship=row["relationship"],
                   confidence=row["confidence"])
    conn.close()
    return g


# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".java": "java", ".go": "go", ".rb": "ruby",
    ".c": "c", ".cpp": "cpp", ".rs": "rust",
}

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json"}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".next", ".mypy_cache",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_node(conn, node_id, ntype, name, meta):
    conn.execute(
        """INSERT INTO nodes (id, type, name, meta_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET meta_json=excluded.meta_json""",
        (node_id, ntype, name, json.dumps(meta))
    )


def _upsert_edge(conn, source_id, target_id, relationship, confidence=1.0):
    edge_id = f"{source_id}::{relationship}::{target_id}"
    conn.execute(
        """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO NOTHING""",
        (edge_id, source_id, target_id, relationship, confidence)
    )
    return edge_id


# ---------------------------------------------------------------------------
# SSE event bus
# ---------------------------------------------------------------------------

import asyncio

_sse_subscribers: list[asyncio.Queue] = []


def _emit(event_type: str, data: dict) -> None:
    payload = json.dumps({"event": event_type, "data": data})
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_subscribers.remove(q)


def subscribe_sse() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_subscribers.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue) -> None:
    if q in _sse_subscribers:
        _sse_subscribers.remove(q)


# ---------------------------------------------------------------------------
# 1. understand_repo  (+ auto complexity scoring saat ingest)
# ---------------------------------------------------------------------------

def understand_repo(repo_path: str) -> dict:
    """
    Ingest repo ke SQLite graph.
    Tambahan unik vs standar:
      - Hitung complexity score tiap fungsi saat parsing (McCabe-approx)
      - Deteksi file tanpa doc-link (kandidat dead/undocumented code)
      - Emit SSE progress per-direktori, bukan hanya di akhir
    """
    root = Path(repo_path)
    if not root.exists():
        return {"ok": False, "error": f"Path tidak ditemukan: {repo_path}"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    stats = {"files": 0, "symbols": 0, "docs": 0, "edges": 0,
             "undocumented_files": 0, "high_complexity_symbols": 0}
    graph_diff: list[dict] = []
    documented_files: set[str] = set()

    # Pass 1: file kode
    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        if any(skip in fpath.parts for skip in SKIP_DIRS):
            continue

        ext = fpath.suffix.lower()
        rel = str(fpath.relative_to(root))

        if ext in SUPPORTED_EXTENSIONS:
            lang = SUPPORTED_EXTENSIONS[ext]
            file_id = f"file::{rel}"

            try:
                src = fpath.read_text(encoding="utf-8", errors="ignore")
                file_lines = len(src.splitlines())
            except Exception:
                src = ""
                file_lines = 0

            _upsert_node(conn, file_id, "file", rel, {
                "path": rel, "lang": lang,
                "abs_path": str(fpath),
                "lines": file_lines,
            })
            graph_diff.append({"id": file_id, "type": "file", "name": rel})
            stats["files"] += 1

            symbols = _parse_ast(fpath, lang, src)
            for sym in symbols:
                sym_id = f"symbol::{rel}::{sym['name']}"
                cx = sym.get("complexity", 1)
                if cx >= 5:
                    stats["high_complexity_symbols"] += 1
                _upsert_node(conn, sym_id, "symbol", sym["name"], {
                    "kind": sym["kind"],
                    "line": sym["line"],
                    "file": rel,
                    "complexity": cx,
                    "lines": sym.get("lines", 0),
                })
                _upsert_edge(conn, file_id, sym_id, "IMPLEMENTED_BY")
                graph_diff.append({
                    "id": sym_id, "type": "symbol",
                    "name": sym["name"], "parent": file_id,
                    "complexity": cx,
                })
                stats["symbols"] += 1
                stats["edges"] += 1

        elif ext in DOC_EXTENSIONS:
            doc_id = f"doc::{rel}"
            _upsert_node(conn, doc_id, "doc", rel,
                         {"path": rel, "abs_path": str(fpath)})
            graph_diff.append({"id": doc_id, "type": "doc", "name": rel})
            stats["docs"] += 1

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                edges_added = _link_doc_to_code(conn, doc_id, content, root,
                                                documented_files)
                stats["edges"] += edges_added
            except Exception:
                pass

            _emit("ingest_progress", {
                "repo": repo_path,
                "current_doc": rel,
                "stats_so_far": stats.copy(),
            })

    all_file_ids = {
        row["id"] for row in
        conn.execute("SELECT id FROM nodes WHERE type='file'").fetchall()
    }
    stats["undocumented_files"] = len(all_file_ids - documented_files)

    conn.commit()
    conn.close()

    global _graph
    _graph = _rebuild_graph()

    _emit("graph_update", {
        "repo": repo_path,
        "nodes": graph_diff,
        "stats": stats,
        "ingested_at": datetime.utcnow().isoformat(),
    })

    return {
        "ok": True,
        "repo": repo_path,
        "stats": stats,
        "node_count": len(_graph.nodes),
        "edge_count": len(_graph.edges),
        "ingested_at": datetime.utcnow().isoformat(),
    }


def _parse_ast(fpath: Path, lang: str, src: str = "") -> list[dict]:
    """
    Parse file kode + hitung complexity score per fungsi.
    """
    symbols: list[dict] = []

    try:
        from tree_sitter_languages import get_language, get_parser
        language = get_language(lang)
        parser = get_parser(lang)
        source = fpath.read_bytes()
        tree = parser.parse(source)
        root_node = tree.root_node

        QUERIES = {
            "python": """
                (function_definition name: (identifier) @fname)
                (class_definition name: (identifier) @cname)
                (import_statement name: (dotted_name) @imp)
                (import_from_statement module_name: (dotted_name) @imp)
            """,
            "javascript": """
                (function_declaration name: (identifier) @fname)
                (class_declaration name: (identifier) @cname)
                (import_statement source: (string) @imp)
            """,
            "typescript": """
                (function_declaration name: (identifier) @fname)
                (class_declaration name: (identifier) @cname)
                (import_statement source: (string) @imp)
            """,
        }
        query_src = QUERIES.get(lang)
        if query_src:
            q = language.query(query_src)
            captures = q.captures(root_node)
            for node, cap_name in captures:
                text = source[node.start_byte:node.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                kind = ("function" if "fname" in cap_name else
                        "class" if "cname" in cap_name else "import")
                func_src = source[node.start_byte:node.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                symbols.append({
                    "name": text.strip('"\''),
                    "kind": kind,
                    "line": node.start_point[0] + 1,
                    "complexity": _calc_complexity(func_src),
                    "lines": func_src.count("\n") + 1,
                })
        return symbols
    except Exception:
        pass

    if lang == "python":
        try:
            import ast as pyast
            source_str = src or fpath.read_text(encoding="utf-8", errors="ignore")
            tree = pyast.parse(source_str)
            src_lines = source_str.splitlines()
            for node in pyast.walk(tree):
                if isinstance(node, (pyast.FunctionDef, pyast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno)
                    func_src = "\n".join(src_lines[node.lineno - 1: end])
                    symbols.append({
                        "name": node.name, "kind": "function",
                        "line": node.lineno,
                        "complexity": _calc_complexity(func_src),
                        "lines": end - node.lineno + 1,
                    })
                elif isinstance(node, pyast.ClassDef):
                    symbols.append({
                        "name": node.name, "kind": "class",
                        "line": node.lineno, "complexity": 1, "lines": 1,
                    })
                elif isinstance(node, pyast.Import):
                    for alias in node.names:
                        symbols.append({
                            "name": alias.name, "kind": "import",
                            "line": node.lineno, "complexity": 0, "lines": 1,
                        })
                elif isinstance(node, pyast.ImportFrom):
                    if node.module:
                        symbols.append({
                            "name": node.module, "kind": "import",
                            "line": node.lineno, "complexity": 0, "lines": 1,
                        })
        except Exception:
            pass

    return symbols


def _calc_complexity(src: str) -> int:
    """McCabe Cyclomatic Complexity approx: 1 + jumlah branch keyword."""
    branch_keywords = [
        r"\bif\b", r"\belif\b", r"\belse\b", r"\bfor\b", r"\bwhile\b",
        r"\bexcept\b", r"\band\b", r"\bor\b", r"\bcase\b", r"\bcatch\b",
        r"\bswitch\b",
    ]
    count = 1
    for kw in branch_keywords:
        count += len(re.findall(kw, src))
    return count


def _link_doc_to_code(conn, doc_id, content, root, documented_files: set) -> int:
    edges = 0
    rows = conn.execute("SELECT id, name FROM nodes WHERE type='file'").fetchall()
    content_lower = content.lower()
    for row in rows:
        fname = Path(row["name"]).name.lower()
        if fname and fname in content_lower:
            _upsert_edge(conn, doc_id, row["id"], "DOCUMENTS", confidence=0.8)
            documented_files.add(row["id"])
            edges += 1
    return edges


# ---------------------------------------------------------------------------
# 2. explain_topic  (+ callers + how_to_use + relevance scoring)
# ---------------------------------------------------------------------------

def explain_topic(topic: str) -> dict:
    """
    Cari entitas di graph, baca snippet, return penjelasan.
    Tambahan unik:
      - Relevance scoring per node hasil pencarian
      - Sertakan "callers" (siapa yang memanggil entitas ini)
      - Sertakan "how_to_use" yang diinfer dari graph
      - Tampilkan complexity note
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    topic_lower = topic.lower()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    matched_nodes = []
    for row in conn.execute(
        "SELECT id, type, name, meta_json FROM nodes WHERE LOWER(name) LIKE ?",
        (f"%{topic_lower}%",)
    ):
        node = dict(row)
        name_l = node["name"].lower()
        node["relevance"] = (1.0 if name_l == topic_lower else
                             0.8 if name_l.startswith(topic_lower) else 0.5)
        matched_nodes.append(node)

    matched_nodes.sort(key=lambda x: x["relevance"], reverse=True)

    if not matched_nodes:
        conn.close()
        return {
            "ok": False, "topic": topic,
            "message": f"Tidak ditemukan entitas yang cocok dengan '{topic}' di graph."
        }

    primary = matched_nodes[0]

    related: list[dict] = []
    callers: list[dict] = []
    if primary["id"] in _graph:
        for nb_id in list(_graph.successors(primary["id"])):
            if nb_id in _graph.nodes:
                nd = _graph.nodes[nb_id]
                ed = _graph.get_edge_data(primary["id"], nb_id) or {}
                related.append({
                    "id": nb_id, "name": nd.get("name", nb_id),
                    "type": nd.get("type", "unknown"),
                    "relationship": ed.get("relationship", ""),
                    "direction": "outgoing",
                })
        for nb_id in list(_graph.predecessors(primary["id"])):
            if nb_id in _graph.nodes:
                nd = _graph.nodes[nb_id]
                ed = _graph.get_edge_data(nb_id, primary["id"]) or {}
                entry = {
                    "id": nb_id, "name": nd.get("name", nb_id),
                    "type": nd.get("type", "unknown"),
                    "relationship": ed.get("relationship", ""),
                    "direction": "incoming",
                }
                related.append(entry)
                if nd.get("type") == "symbol":
                    callers.append(entry)

    snippet = ""
    meta = json.loads(primary.get("meta_json") or "{}")
    abs_path = meta.get("abs_path") or meta.get("path", "")
    if abs_path and Path(abs_path).exists():
        try:
            lines = Path(abs_path).read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            start = max(0, meta.get("line", 1) - 1)
            snippet = "\n".join(lines[start: start + 25])
        except Exception:
            pass

    conn.close()

    type_label = {
        "file": "file kode",
        "symbol": f"{meta.get('kind','symbol')} (simbol kode)",
        "doc": "dokumen", "dependency": "dependensi", "operation": "operasi",
    }.get(primary["type"], primary["type"])

    how_to_use = ""
    if callers:
        how_to_use = (
            f"Dipakai oleh: {', '.join(c['name'] for c in callers[:3])}. "
            f"Lihat file-file tersebut sebagai contoh penggunaan."
        )
    elif primary["type"] == "symbol" and meta.get("kind") == "function":
        how_to_use = f"Panggil dengan: `{primary['name']}(...)`"

    cx = meta.get("complexity", None)
    complexity_note = (
        f"⚠️ Complexity tinggi ({cx}) — kandidat refactor." if cx and cx >= 10 else
        f"⚡ Complexity sedang ({cx})." if cx and cx >= 5 else
        f"✅ Complexity rendah ({cx})." if cx else ""
    )

    return {
        "ok": True,
        "topic": topic,
        "primary_node": primary,
        "definition": f"**{primary['name']}** adalah {type_label} di graph Synapse.",
        "mental_model": (
            f"'{primary['name']}' adalah node bertipe '{primary['type']}', "
            f"terhubung ke {len(related)} entitas. Caller langsung: {len(callers)}."
        ),
        "complexity_note": complexity_note,
        "how_to_use": how_to_use,
        "example": snippet or "(Tidak ada snippet tersedia)",
        "related_nodes": related[:10],
        "callers": callers[:5],
        "all_matches": [
            {"id": n["id"], "name": n["name"],
             "type": n["type"], "relevance": n["relevance"]}
            for n in matched_nodes[:5]
        ],
    }


# ---------------------------------------------------------------------------
# 3. review_artifact  (+ diff-aware + pattern-based risk detection)
# ---------------------------------------------------------------------------

def review_artifact(path_or_diff: str) -> dict:
    """
    Scoring artifact 4 dimensi.
    Tambahan unik:
      - Deteksi apakah ini git diff (baris +/-)
      - Hitung churn (added vs removed lines)
      - Pattern-based risk detection (bukan hanya keyword)
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    content = ""
    is_file = Path(path_or_diff).exists()

    if is_file:
        try:
            content = Path(path_or_diff).read_text(
                encoding="utf-8", errors="ignore"
            )[:5000]
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        content = path_or_diff

    lines = content.splitlines()
    added_lines = [l for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed_lines = [l for l in lines if l.startswith("-") and not l.startswith("---")]
    is_diff = len(added_lines) > 0 and len(removed_lines) > 0
    effective_lines = added_lines if is_diff else lines
    total_lines = len(effective_lines)

    # 1. Completeness
    incomplete_markers = sum(
        1 for l in effective_lines
        if any(m in l.upper() for m in ["TODO", "FIXME", "HACK", "XXX", "PASS ", "..."])
    )
    completeness = max(0.0, 1.0 - (incomplete_markers / max(total_lines, 1)) * 10)

    # 2. Clarity
    avg_len = sum(len(l.lstrip("+-")) for l in effective_lines) / max(total_lines, 1)
    clarity = 1.0 if avg_len < 80 else max(0.3, 1.0 - (avg_len - 80) / 200)

    # 3. Correctness vs spec
    graph_names = {
        data.get("name", "").lower()
        for _, data in _graph.nodes(data=True)
    }
    referenced = sum(1 for name in graph_names if name and name in content.lower())
    correctness = min(1.0, 0.5 + referenced * 0.1)

    # 4. Risk — pattern spesifik
    risk_patterns = [
        (r"drop\s+table", "DROP TABLE terdeteksi"),
        (r"delete\s+from\s+\w+\s*;", "DELETE tanpa WHERE"),
        (r"rm\s+-rf", "rm -rf terdeteksi"),
        (r"os\.remove|shutil\.rmtree", "File delete terdeteksi"),
        (r"subprocess\.call|subprocess\.run", "Subprocess execution"),
        (r"\beval\s*\(", "eval() — potensi code injection"),
        (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password"),
        (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded secret"),
        (r"ALTER\s+TABLE", "ALTER TABLE terdeteksi"),
        (r"TRUNCATE", "TRUNCATE terdeteksi"),
    ]
    risk_findings = [
        label for pattern, label in risk_patterns
        if re.search(pattern, content, re.IGNORECASE)
    ]
    risk_score = min(1.0, len(risk_findings) * 0.2)

    avg_positive = (completeness + clarity + correctness) / 3
    if risk_score >= 0.6 or avg_positive < 0.4:
        verdict = "block"
    elif avg_positive < 0.7 or risk_score >= 0.4:
        verdict = "needs_work"
    else:
        verdict = "pass"

    scores = {
        "completeness": round(completeness, 2),
        "clarity": round(clarity, 2),
        "correctness_vs_spec": round(correctness, 2),
        "risk": round(risk_score, 2),
    }

    _emit("review_done", {
        "artifact": path_or_diff if is_file else "(diff)",
        "scores": scores, "verdict": verdict, "risk_findings": risk_findings,
    })

    return {
        "ok": True,
        "artifact": path_or_diff if is_file else "(inline diff)",
        "is_diff": is_diff,
        "churn": {"added": len(added_lines), "removed": len(removed_lines)}
        if is_diff else None,
        "scores": scores,
        "verdict": verdict,
        "risk_findings": risk_findings,
        "notes": {
            "incomplete_markers": incomplete_markers,
            "avg_line_length": round(avg_len, 1),
            "graph_references_found": referenced,
        },
    }


# ---------------------------------------------------------------------------
# 4. repo_health()  — FITUR UNIK
# ---------------------------------------------------------------------------

def repo_health() -> dict:
    """
    Laporan kesehatan repo:
      - Coverage dokumentasi (% file punya edge DOCUMENTS)
      - Dead code candidates (simbol tanpa incoming edge)
      - High complexity symbols (complexity >= 10)
      - Isolated nodes
      - Hub nodes (node dengan koneksi terbanyak)
      - Health score 0-100
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    total_files = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE type='file'"
    ).fetchone()[0]

    documented_file_ids = {
        row["target_id"] for row in conn.execute(
            "SELECT DISTINCT target_id FROM edges WHERE relationship='DOCUMENTS'"
        ).fetchall()
    }
    doc_coverage = (
        round(len(documented_file_ids) / total_files * 100, 1)
        if total_files > 0 else 0.0
    )

    all_symbols = conn.execute(
        "SELECT id, name, meta_json FROM nodes WHERE type='symbol'"
    ).fetchall()
    dead_candidates = []
    for sym in all_symbols:
        meta = json.loads(sym["meta_json"] or "{}")
        if meta.get("kind") == "import":
            continue
        in_degree = _graph.in_degree(sym["id"]) if sym["id"] in _graph else 0
        if in_degree == 0:
            dead_candidates.append({
                "id": sym["id"], "name": sym["name"],
                "file": meta.get("file", ""), "kind": meta.get("kind", ""),
                "line": meta.get("line", 0),
            })

    high_cx = []
    for row in conn.execute(
        "SELECT id, name, meta_json FROM nodes WHERE type='symbol'"
    ).fetchall():
        meta = json.loads(row["meta_json"] or "{}")
        cx = meta.get("complexity", 0)
        if cx >= 10:
            high_cx.append({
                "id": row["id"], "name": row["name"],
                "complexity": cx, "file": meta.get("file", ""),
                "line": meta.get("line", 0),
            })
    high_cx.sort(key=lambda x: x["complexity"], reverse=True)

    isolated = [
        {"id": n, "name": _graph.nodes[n].get("name", n),
         "type": _graph.nodes[n].get("type", "")}
        for n in nx.isolates(_graph)
        if _graph.nodes[n].get("type") not in ("import",)
    ]

    hub_nodes = sorted(
        [
            {"id": n, "name": _graph.nodes[n].get("name", n),
             "type": _graph.nodes[n].get("type", ""),
             "degree": _graph.degree(n)}
            for n in _graph.nodes
        ],
        key=lambda x: x["degree"], reverse=True
    )[:5]

    conn.close()

    health_score = round(
        (doc_coverage * 0.4)
        + (max(0, 100 - len(dead_candidates) * 2) * 0.3)
        + (max(0, 100 - len(high_cx) * 5) * 0.3),
        1
    )

    summary = (
        f"{'🟢 Sehat' if health_score >= 80 else '🟡 Perlu perhatian' if health_score >= 60 else '🔴 Butuh perbaikan'}"
        f" — Skor {health_score}/100. Dokumentasi {doc_coverage}%, "
        f"{len(dead_candidates)} kandidat dead code, {len(high_cx)} fungsi kompleks."
    )

    _emit("health_report", {
        "health_score": health_score,
        "doc_coverage_percent": doc_coverage,
        "dead_code_count": len(dead_candidates),
        "high_complexity_count": len(high_cx),
    })

    return {
        "ok": True,
        "health_score": health_score,
        "summary": summary,
        "doc_coverage_percent": doc_coverage,
        "total_files": total_files,
        "documented_files": len(documented_file_ids),
        "dead_code_candidates": dead_candidates[:20],
        "high_complexity_symbols": high_cx[:10],
        "isolated_nodes_count": len(isolated),
        "isolated_nodes": isolated[:10],
        "hub_nodes": hub_nodes,
    }


# ---------------------------------------------------------------------------
# 5. find_path()  — FITUR UNIK
# ---------------------------------------------------------------------------

def find_path(from_node_name: str, to_node_name: str) -> dict:
    """
    Cari jalur terpendek antara dua entitas di knowledge graph.
    Menjawab: 'bagaimana A mempengaruhi B?'
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    def _find_id(name: str):
        row = conn.execute(
            "SELECT id FROM nodes WHERE LOWER(name) LIKE ? LIMIT 1",
            (f"%{name.lower()}%",)
        ).fetchone()
        return row["id"] if row else None

    from_id = _find_id(from_node_name)
    to_id = _find_id(to_node_name)
    conn.close()

    if not from_id:
        return {"ok": False, "error": f"Node '{from_node_name}' tidak ditemukan"}
    if not to_id:
        return {"ok": False, "error": f"Node '{to_node_name}' tidak ditemukan"}

    try:
        path_ids = nx.shortest_path(_graph, source=from_id, target=to_id)
        path_nodes = [
            {"id": nid, "name": _graph.nodes[nid].get("name", nid),
             "type": _graph.nodes[nid].get("type", "")}
            for nid in path_ids
        ]
        edges_in_path = [
            {
                "from": _graph.nodes[path_ids[i]].get("name", path_ids[i]),
                "to": _graph.nodes[path_ids[i + 1]].get("name", path_ids[i + 1]),
                "relationship": (_graph.get_edge_data(
                    path_ids[i], path_ids[i + 1]) or {}).get("relationship", "->"),
            }
            for i in range(len(path_ids) - 1)
        ]
        return {
            "ok": True,
            "from": from_node_name, "to": to_node_name,
            "path_length": len(path_ids) - 1,
            "path": path_nodes, "edges": edges_in_path,
        }
    except nx.NetworkXNoPath:
        return {"ok": False,
                "error": f"Tidak ada jalur dari '{from_node_name}' ke '{to_node_name}'"}
    except nx.NodeNotFound as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 6. complexity_report()  — FITUR UNIK
# ---------------------------------------------------------------------------

def complexity_report(top_n: int = 10) -> dict:
    """
    Ranking N fungsi dengan complexity score tertinggi.
    Berguna untuk menentukan prioritas refactor.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, meta_json FROM nodes WHERE type='symbol'"
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        meta = json.loads(row["meta_json"] or "{}")
        cx = meta.get("complexity", 0)
        if meta.get("kind") in ("function", "class") and cx > 0:
            results.append({
                "id": row["id"], "name": row["name"],
                "kind": meta.get("kind", ""),
                "file": meta.get("file", ""),
                "line": meta.get("line", 0),
                "complexity": cx,
                "lines": meta.get("lines", 0),
                "risk_level": (
                    "critical" if cx >= 15 else
                    "high" if cx >= 10 else
                    "medium" if cx >= 5 else "low"
                ),
            })

    results.sort(key=lambda x: x["complexity"], reverse=True)

    return {
        "ok": True,
        "top_n": top_n,
        "results": results[:top_n],
        "total_analyzed": len(results),
        "critical_count": sum(1 for r in results if r["risk_level"] == "critical"),
        "high_count": sum(1 for r in results if r["risk_level"] == "high"),
    }


# ---------------------------------------------------------------------------
# 7. suggest_refactor()  — FITUR UNIK
# ---------------------------------------------------------------------------

def suggest_refactor(node_name: str) -> dict:
    """
    Saran refactor berbasis graph:
      - Complexity terlalu tinggi → split function
      - Degree terlalu banyak → God Object
      - Lines terlalu panjang → split file
      - Tidak ada dokumentasi → tambah docstring
      - Tidak ada caller → dead code
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, name, type, meta_json FROM nodes WHERE LOWER(name) LIKE ? LIMIT 1",
        (f"%{node_name.lower()}%",)
    ).fetchone()
    conn.close()

    if not row:
        return {"ok": False, "error": f"Node '{node_name}' tidak ditemukan"}

    meta = json.loads(row["meta_json"] or "{}")
    node_id = row["id"]
    cx = meta.get("complexity", 1)
    lines = meta.get("lines", 0)
    degree = _graph.degree(node_id) if node_id in _graph else 0
    in_deg = _graph.in_degree(node_id) if node_id in _graph else 0
    out_deg = _graph.out_degree(node_id) if node_id in _graph else 0

    has_doc = any(
        (_graph.get_edge_data(pred, node_id) or {}).get("relationship") == "DOCUMENTS"
        for pred in _graph.predecessors(node_id)
    )

    suggestions = []

    if cx >= 15:
        suggestions.append({
            "type": "split_function", "priority": "critical",
            "message": (
                f"Complexity {cx} sangat tinggi. Pecah menjadi beberapa "
                f"fungsi kecil (Single Responsibility Principle)."
            ),
        })
    elif cx >= 10:
        suggestions.append({
            "type": "reduce_branches", "priority": "high",
            "message": (
                f"Complexity {cx} tinggi. Kurangi if/else/for bersarang. "
                f"Gunakan early return atau guard clause."
            ),
        })

    if lines >= 100:
        suggestions.append({
            "type": "split_file_or_function", "priority": "high",
            "message": f"Fungsi ini {lines} baris — terlalu panjang. Idealnya < 50 baris.",
        })

    if degree >= 15:
        suggestions.append({
            "type": "god_object", "priority": "high",
            "message": (
                f"Node ini punya {degree} koneksi — kemungkinan 'God Object'. "
                f"Pecah menjadi modul lebih kecil."
            ),
        })

    if not has_doc:
        suggestions.append({
            "type": "add_documentation", "priority": "medium",
            "message": "Tidak ada dokumentasi terhubung. Tambahkan docstring atau file .md.",
        })

    if in_deg == 0 and row["type"] == "symbol" and meta.get("kind") == "function":
        suggestions.append({
            "type": "dead_code", "priority": "medium",
            "message": "Tidak ada caller di graph — kemungkinan dead code. Pertimbangkan dihapus.",
        })

    if not suggestions:
        suggestions.append({
            "type": "no_action", "priority": "low",
            "message": "Entitas ini sehat — tidak ada saran refactor.",
        })

    _emit("refactor_suggestion", {
        "node": row["name"],
        "suggestion_count": len(suggestions),
        "top_priority": suggestions[0]["priority"],
    })

    return {
        "ok": True,
        "node": row["name"],
        "type": row["type"],
        "metrics": {
            "complexity": cx, "lines": lines,
            "degree": degree, "in_degree": in_deg,
            "out_degree": out_deg, "has_documentation": has_doc,
        },
        "suggestions": suggestions,
    }
