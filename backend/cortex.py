"""
cortex.py — BE-2 Masrendra
Tanggung jawab:
  - understand_repo(repo_path): ingest repo via tree-sitter AST + baca docs
  - explain_topic(topic): query graph + jawab dengan konteks file
  - review_artifact(path_or_diff): scoring 4 dimensi (nice-to-have)
"""
import json
import uuid
import sqlite3
from pathlib import Path
from typing import Generator

import networkx as nx

from database import get_conn, DB_PATH

# ---------------------------------------------------------------------------
# In-memory graph (networkx) — di-rebuild dari SQLite setiap kali needed
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
    for row in conn.execute("SELECT source_id, target_id, relationship, confidence FROM edges"):
        g.add_edge(row["source_id"], row["target_id"],
                   relationship=row["relationship"],
                   confidence=row["confidence"])
    conn.close()
    return g


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".rs": "rust",
}

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json"}


def _new_id() -> str:
    return str(uuid.uuid4())


def _upsert_node(conn: sqlite3.Connection, node_id: str, ntype: str,
                 name: str, meta: dict) -> None:
    conn.execute(
        """INSERT INTO nodes (id, type, name, meta_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET meta_json=excluded.meta_json""",
        (node_id, ntype, name, json.dumps(meta))
    )


def _upsert_edge(conn: sqlite3.Connection, source_id: str, target_id: str,
                 relationship: str, confidence: float = 1.0) -> str:
    edge_id = f"{source_id}::{relationship}::{target_id}"
    conn.execute(
        """INSERT INTO edges (id, source_id, target_id, relationship, confidence)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO NOTHING""",
        (edge_id, source_id, target_id, relationship, confidence)
    )
    return edge_id


# ---------------------------------------------------------------------------
# SSE event bus (in-memory queue, dibaca oleh /stream endpoint)
# ---------------------------------------------------------------------------

import asyncio
from collections import deque

_sse_subscribers: list[asyncio.Queue] = []


def _emit(event_type: str, data: dict) -> None:
    """Kirim event SSE ke semua subscriber."""
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
# 1. understand_repo
# ---------------------------------------------------------------------------

def understand_repo(repo_path: str) -> dict:
    """
    Ingest sebuah repo ke SQLite graph.

    Langkah:
      1. Walk seluruh file repo
      2. Untuk setiap file kode yang didukung → parse AST via tree-sitter
         → extract file-node, symbol-nodes (fungsi/kelas), import-nodes
      3. Untuk setiap file doc (.md/.txt/.rst) → buat doc-node,
         coba buat edge DOCUMENTS ke file kode yang namanya disebut di dalamnya
      4. Emit SSE "graph_update" per batch
    """
    root = Path(repo_path)
    if not root.exists():
        return {"ok": False, "error": f"Path tidak ditemukan: {repo_path}"}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    stats = {"files": 0, "symbols": 0, "docs": 0, "edges": 0}
    graph_diff: list[dict] = []

    # --- Pass 1: file kode ---
    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        ext = fpath.suffix.lower()
        rel = str(fpath.relative_to(root))

        if ext in SUPPORTED_EXTENSIONS:
            lang = SUPPORTED_EXTENSIONS[ext]
            file_id = f"file::{rel}"
            _upsert_node(conn, file_id, "file", rel,
                         {"path": rel, "lang": lang, "abs_path": str(fpath)})
            graph_diff.append({"id": file_id, "type": "file", "name": rel})
            stats["files"] += 1

            # Parse AST
            symbols = _parse_ast(fpath, lang)
            for sym in symbols:
                sym_id = f"symbol::{rel}::{sym['name']}"
                _upsert_node(conn, sym_id, "symbol", sym["name"],
                             {"kind": sym["kind"], "line": sym["line"],
                              "file": rel})
                _upsert_edge(conn, file_id, sym_id, "IMPLEMENTED_BY")
                graph_diff.append({"id": sym_id, "type": "symbol",
                                   "name": sym["name"],
                                   "parent": file_id})
                stats["symbols"] += 1
                stats["edges"] += 1

        elif ext in DOC_EXTENSIONS:
            doc_id = f"doc::{rel}"
            _upsert_node(conn, doc_id, "doc", rel,
                         {"path": rel, "abs_path": str(fpath)})
            graph_diff.append({"id": doc_id, "type": "doc", "name": rel})
            stats["docs"] += 1

            # Coba buat edge DOCUMENTS ke file kode yang namanya disebut
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                edges_added = _link_doc_to_code(conn, doc_id, content, root)
                stats["edges"] += edges_added
            except Exception:
                pass

    conn.commit()
    conn.close()

    # Emit SSE
    _emit("graph_update", {
        "repo": repo_path,
        "nodes": graph_diff,
        "stats": stats
    })

    global _graph
    _graph = _rebuild_graph()

    return {
        "ok": True,
        "repo": repo_path,
        "stats": stats,
        "node_count": len(_graph.nodes),
        "edge_count": len(_graph.edges),
    }


def _parse_ast(fpath: Path, lang: str) -> list[dict]:
    """
    Parse file kode dengan tree-sitter.
    Return list of { name, kind, line }.
    Fallback ke parser Python bawaan kalau tree-sitter gagal.
    """
    symbols: list[dict] = []

    # --- tree-sitter ---
    try:
        from tree_sitter_languages import get_language, get_parser
        language = get_language(lang)
        parser = get_parser(lang)
        source = fpath.read_bytes()
        tree = parser.parse(source)
        root_node = tree.root_node

        # Query: function_definition dan class_definition (Python/JS/TS/Go)
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
                text = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
                kind = "function" if "fname" in cap_name else \
                       "class" if "cname" in cap_name else "import"
                symbols.append({
                    "name": text.strip('"\''),
                    "kind": kind,
                    "line": node.start_point[0] + 1,
                })
        else:
            # Generic: hanya extract nama node level atas
            for child in root_node.children:
                if hasattr(child, "child_by_field_name"):
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        text = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
                        symbols.append({
                            "name": text,
                            "kind": child.type,
                            "line": child.start_point[0] + 1,
                        })
        return symbols

    except Exception:
        pass

    # --- Fallback: Python ast module (hanya untuk .py) ---
    if lang == "python":
        try:
            import ast as pyast
            source_str = fpath.read_text(encoding="utf-8", errors="ignore")
            tree = pyast.parse(source_str)
            for node in pyast.walk(tree):
                if isinstance(node, (pyast.FunctionDef, pyast.AsyncFunctionDef)):
                    symbols.append({"name": node.name, "kind": "function",
                                    "line": node.lineno})
                elif isinstance(node, pyast.ClassDef):
                    symbols.append({"name": node.name, "kind": "class",
                                    "line": node.lineno})
                elif isinstance(node, pyast.Import):
                    for alias in node.names:
                        symbols.append({"name": alias.name, "kind": "import",
                                        "line": node.lineno})
                elif isinstance(node, pyast.ImportFrom):
                    if node.module:
                        symbols.append({"name": node.module, "kind": "import",
                                        "line": node.lineno})
        except Exception:
            pass

    return symbols


def _link_doc_to_code(conn: sqlite3.Connection, doc_id: str,
                      content: str, root: Path) -> int:
    """
    Cari nama file kode yang disebut dalam konten doc,
    buat edge DOCUMENTS kalau ketemu.
    Return jumlah edge yang dibuat.
    """
    edges = 0
    rows = conn.execute(
        "SELECT id, name FROM nodes WHERE type='file'"
    ).fetchall()
    content_lower = content.lower()
    for row in rows:
        fname = Path(row["name"]).name.lower()
        if fname and fname in content_lower:
            _upsert_edge(conn, doc_id, row["id"], "DOCUMENTS", confidence=0.8)
            edges += 1
    return edges


# ---------------------------------------------------------------------------
# 2. explain_topic
# ---------------------------------------------------------------------------

def explain_topic(topic: str) -> dict:
    """
    Cari entitas graph yang relevan dengan `topic`,
    baca isi file yang terkait, return penjelasan terstruktur.

    Output: { definition, mental_model, example, related_nodes }
    """
    global _graph
    if len(_graph.nodes) == 0:
        _graph = _rebuild_graph()

    topic_lower = topic.lower()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # --- Cari node yang namanya mengandung topic ---
    matched_nodes = []
    for row in conn.execute(
        "SELECT id, type, name, meta_json FROM nodes WHERE LOWER(name) LIKE ?",
        (f"%{topic_lower}%",)
    ):
        matched_nodes.append(dict(row))

    if not matched_nodes:
        conn.close()
        return {
            "ok": False,
            "topic": topic,
            "message": f"Tidak ditemukan entitas yang cocok dengan '{topic}' di graph."
        }

    # Ambil node utama (paling relevan: exact match atau tertinggi)
    exact = [n for n in matched_nodes if n["name"].lower() == topic_lower]
    primary = exact[0] if exact else matched_nodes[0]

    # --- Kumpulkan tetangga langsung dari graph ---
    related: list[dict] = []
    if primary["id"] in _graph:
        for neighbor_id in list(_graph.successors(primary["id"])) + \
                           list(_graph.predecessors(primary["id"])):
            if neighbor_id in _graph.nodes:
                ndata = _graph.nodes[neighbor_id]
                edge_data = _graph.get_edge_data(primary["id"], neighbor_id) or \
                            _graph.get_edge_data(neighbor_id, primary["id"]) or {}
                related.append({
                    "id": neighbor_id,
                    "name": ndata.get("name", neighbor_id),
                    "type": ndata.get("type", "unknown"),
                    "relationship": edge_data.get("relationship", "")
                })

    # --- Baca isi file yang relevan ---
    snippet = ""
    meta = json.loads(primary.get("meta_json") or "{}")
    abs_path = meta.get("abs_path") or meta.get("path", "")
    if abs_path and Path(abs_path).exists():
        try:
            lines = Path(abs_path).read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            start_line = meta.get("line", 1)
            # Ambil 20 baris setelah definisi
            snippet_lines = lines[max(0, start_line - 1): start_line + 19]
            snippet = "\n".join(snippet_lines)
        except Exception:
            pass
    elif primary["type"] == "file":
        file_path = meta.get("abs_path") or meta.get("path", "")
        if file_path and Path(file_path).exists():
            try:
                snippet = Path(file_path).read_text(
                    encoding="utf-8", errors="ignore"
                )[:1500]
            except Exception:
                pass

    conn.close()

    # --- Susun penjelasan terstruktur ---
    type_label = {
        "file": "file kode",
        "symbol": f"{meta.get('kind', 'symbol')} (simbol kode)",
        "doc": "dokumen",
        "dependency": "dependensi",
        "operation": "operasi",
    }.get(primary["type"], primary["type"])

    definition = (
        f"**{primary['name']}** adalah sebuah {type_label} "
        f"yang ditemukan di graph Synapse."
    )

    mental_model = (
        f"Bayangkan graph sebagai peta kode: "
        f"'{primary['name']}' adalah satu titik (node) bertipe '{primary['type']}'. "
        f"Node ini terhubung ke {len(related)} entitas lain, "
        f"termasuk: {', '.join(r['name'] for r in related[:5]) or 'tidak ada'}."
    )

    example = snippet if snippet else "(Tidak ada snippet tersedia)"

    return {
        "ok": True,
        "topic": topic,
        "primary_node": primary,
        "definition": definition,
        "mental_model": mental_model,
        "example": example,
        "related_nodes": related[:10],
    }


# ---------------------------------------------------------------------------
# 3. review_artifact (nice-to-have)
# ---------------------------------------------------------------------------

def review_artifact(path_or_diff: str) -> dict:
    """
    Scoring artifact (path file atau diff teks) pada 4 dimensi:
    completeness, clarity, correctness_vs_spec, risk.
    Return verdict: pass | needs_work | block.
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
            )[:4000]
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        content = path_or_diff  # anggap ini diff teks

    lines = content.splitlines()
    total_lines = len(lines)

    # --- Scoring heuristik (rule-based, bukan ML) ---

    # 1. Completeness: apakah ada TODO/FIXME/pass/... yang belum selesai?
    incomplete_markers = sum(
        1 for l in lines
        if any(m in l.upper() for m in ["TODO", "FIXME", "HACK", "XXX", "PASS", "..."])
    )
    completeness = max(0.0, 1.0 - (incomplete_markers / max(total_lines, 1)) * 10)

    # 2. Clarity: rata-rata panjang baris (terlalu panjang = kurang jelas)
    avg_len = sum(len(l) for l in lines) / max(total_lines, 1)
    clarity = 1.0 if avg_len < 80 else max(0.3, 1.0 - (avg_len - 80) / 200)

    # 3. Correctness vs spec: apakah nama fungsi/kelas ada di graph?
    graph_names = {
        data.get("name", "").lower()
        for _, data in _graph.nodes(data=True)
    }
    referenced = sum(
        1 for name in graph_names
        if name and name in content.lower()
    )
    correctness = min(1.0, 0.5 + referenced * 0.1)

    # 4. Risk: apakah ada keyword berisiko tinggi?
    risk_keywords = [
        "drop table", "delete from", "truncate", "rm -rf",
        "os.remove", "shutil.rmtree", "subprocess", "exec(",
        "eval(", "migration", "rollback"
    ]
    risk_hits = sum(
        1 for kw in risk_keywords if kw in content.lower()
    )
    risk_score = min(1.0, risk_hits * 0.2)  # 0 = aman, 1 = sangat berisiko

    # --- Verdict ---
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
        "artifact": path_or_diff,
        "scores": scores,
        "verdict": verdict,
    })

    return {
        "ok": True,
        "artifact": path_or_diff,
        "scores": scores,
        "verdict": verdict,
        "notes": {
            "incomplete_markers": incomplete_markers,
            "avg_line_length": round(avg_len, 1),
            "graph_references_found": referenced,
            "risk_keywords_found": risk_hits,
        }
    }
