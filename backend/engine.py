"""
engine.py — Mesin analisis repo berbasis knowledge graph (SQLite + networkx).

Pengganti cortex.py sebagai layer analisis. Tujuh fungsi publiknya dipindahkan
dari cortex.py dengan nama yang lebih deskriptif:

    Understand_repo   -> ingest_repository()
    explain_topic     -> ask_about()
    review_artifact   -> review_change()
    repo_health       -> health_report()
    find_path         -> trace_connection()
    complexity_report -> rank_complexity()
    suggest_refactor  -> propose_refactor()

Perilaku inti (skoring, ambang batas, bentuk return) sengaja dipertahankan
agar frontend tidak perlu berubah. Yang berubah adalah nama fungsi dan layer
data di bawahnya: cortex.py menulis ke tabel legacy nodes/edges di synapse.db,
engine.py menulis ke entities/relations di synapse_v2.db lewat storage.py.

cortex.py tetap ada sebagai shim yang meneruskan ke modul ini, jadi
`import cortex; cortex.understand_repo(...)` masih bekerja.

KEADAAN TREE-SITTER DI PROYEK INI
--------------------------------
requirements.txt lama pin tree-sitter==0.21.3 + tree-sitter-languages==1.10.2.
Pasangan itu MATI di tree-sitter >= 0.22: Language() di-bind ke signature
`__init__(self, ptr, name)` sementara 0.22+ hanya punya `__init__(self, ptr)`, jadi
setiap pemanggilan tree_sitter_languages.get_parser() melempar
`TypeError: __init__() takes exactly 1 argument (2 given)`.

Sebelum engine.py, itu berarti tree-sitter TIDAK PERNAH berhasil dipakai —
_cortex._parse_ast() selalu jatuh ke fallback `ast`, dan fallback itu hanya
bisa menangani Python. File .js/.ts/.go/.java/.rs menghasilkan nol simbol.

Engine ini memakai language pack terpisah (tree_sitter_python,
tree_sitter_javascript) dan mendukung dua generations API:

    tree-sitter < 0.25      tree-sitter >= 0.25
    -------------------     ----------------------
    get_parser(lang)        Language(pack.language())
    lang.query(src)        Query(lang, src)
    q.captures(node)        QueryCursor(q).captures(node)
    -> dict[Node, name]     -> dict[name, list[Node]]

Hasil keduanya dinormalisasi jadi list[(nama_capture, Node)] di _load_parser.
Bahasa tanpa pack terpasang jatuh ke regex, dan Python selalu punya fallback
`ast` sebagai jaring pengaman terakhir.
"""

from __future__ import annotations

import ast as pyast
import asyncio
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import networkx as nx

from storage import (
    DB_PATH,
    get_conn,
    record_audit,
    upsert_entity,
    upsert_relation,
)

__all__ = [
    "ingest_repository",
    "ask_about",
    "review_change",
    "health_report",
    "trace_connection",
    "rank_complexity",
    "propose_refactor",
    "set_event_loop",
    "subscribe_sse",
    "unsubscribe_sse",
    "graph_stats",
    "get_graph_snapshot",
    # alias lama, dipertahankan supaya cortex.py / main.py tidak pecah
    "understand_repo",
    "explain_topic",
    "review_artifact",
    "repo_health",
    "find_path",
    "complexity_report",
    "suggest_refactor",
]


# ===========================================================================
# 1. In-memory graph (networkx) — dilindungi lock
# ===========================================================================
# FastAPI menjalankan endpoint sync di threadpool. Tanpa lock, satu thread
# bisa meng-assign _graph sementara thread lain sedang iterasi _graph.nodes,
# yang bikin RuntimeError: dictionary changed size during iteration.
#
# Aturan: JANGAN pernah mengembalikan _graph langsung ke pemanggil. Semua
# pembaca lewat _get_graph(). Rebuild lewat _rebuild_and_swap() supaya
# penukaran _graph lama ke yang baru terjadi atomik di bawah lock.

_graph_lock: threading.Lock = threading.Lock()
_graph: nx.DiGraph = nx.DiGraph()

# Root repo yang terakhir di-ingest. Symbol entity hanya menyimpan
# source_path RELATIF (menjimka ruang di setiap baris), jadi pembaca snippet
# butuh ini untuk resolve path yang benar. Tanpa ini _read_snippet() hanya
# worked kalau CWD kebetulan sama dengan repo yang di-ingest.
_repo_root: Path | None = None


def _rebuild_and_swap() -> nx.DiGraph:
    """Bangun graph baru dari SQLite, lalu tukar secara atomik di bawah lock."""
    global _graph
    new_graph = _build_graph_from_db()
    with _graph_lock:
        _graph = new_graph
    return new_graph


def _build_graph_from_db() -> nx.DiGraph:
    """Load entities + relations dari SQLite ke networkx.DiGraph (tanpa lock)."""
    g = nx.DiGraph()
    conn = get_conn()
    for row in conn.execute(
        "SELECT id, kind, label, attributes_json, complexity FROM entities"
    ):
        try:
            attrs = json.loads(row["attributes_json"] or "{}")
        except (TypeError, ValueError):
            attrs = {}
        g.add_node(
            row["id"],
            kind=row["kind"],
            label=row["label"],
            name=row["label"],          # alias: frontend & cortex lama pakai "name"
            complexity=row["complexity"] or 0,
            meta=attrs,
        )
    for row in conn.execute(
        "SELECT from_id, to_id, relation_type, weight FROM relations"
    ):
        if row["from_id"] in g and row["to_id"] in g:
            g.add_edge(
                row["from_id"],
                row["to_id"],
                relation_type=row["relation_type"],
                relationship=row["relation_type"],  # alias kompatibilitas
                weight=row["weight"] or 1.0,
                confidence=row["weight"] or 1.0,      # alias kompatibilitas
            )
    return g


def _get_graph() -> nx.DiGraph:
    """
    Ambil graph aktif. Kalau masih kosong, rebuild sekali dari SQLite.

    Ini yang membuat analyze_*.py tetap berguna setelah restart: proses baru
    mulai dengan _graph kosong, dan tidak ada yang memanggil ingest_repository()
    kalau user cuma langsung nanya /repo_health.
    """
    with _graph_lock:
        if len(_graph) == 0:
            needs_rebuild = True
        else:
            return _graph
    if needs_rebuild:
        return _rebuild_and_swap()
    return _graph


# ===========================================================================
# 2. SSE event bus
# ===========================================================================
# BUG-08 (fixed): _emit() dipanggil dari sync thread (threadpool FastAPI),
# sedangkan asyncio.Queue hanya aman_disentuh dari thread event loop. Solusinya
# menyimpan referensi loop utama lalu lompat lewat call_soon_threadsafe().

_sse_subscribers: list[asyncio.Queue] = []
_sse_lock = threading.Lock()
_event_loop: asyncio.AbstractEventLoop | None = None

_QUEUE_MAXSIZE = 200


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Dipanggil sekali dari on_startup() (async context)."""
    global _event_loop
    _event_loop = loop


def _emit(event_type: str, data: dict) -> None:
    """Kirim event ke semua subscriber. Aman dipanggil dari thread mana pun."""
    payload = json.dumps({"event": event_type, "data": data}, default=str)
    with _sse_lock:
        targets = list(_sse_subscribers)

    dead: list[asyncio.Queue] = []
    for q in targets:
        try:
            loop = _event_loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, payload)
            else:
                # Tidak ada loop hidup (mis. dipanggil dari script/pytest).
                # q.put_nowait() masih aman karena Queue tanpa waiter tidak
                # butuh loop; yang tidak bisa dilakukan hanya await get().
                q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
        except Exception:
            dead.append(q)

    if dead:
        with _sse_lock:
            for q in dead:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)


def subscribe_sse() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    with _sse_lock:
        _sse_subscribers.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue) -> None:
    with _sse_lock:
        if q in _sse_subscribers:
            _sse_subscribers.remove(q)


# ===========================================================================
# 3. Konstanta parsing
# ===========================================================================

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".rs": "rust",
}

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json"}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "target", "vendor", "coverage", ".tox", ".idea", ".vscode",
}

SKIP_FILE_SUFFIXES = {
    ".dll", ".so", ".dylib", ".exe", ".pyc", ".pyo", ".pyd", ".class",
    ".jar", ".war", ".o", ".a", ".bin", ".wasm",
}

# Ukuran file maksimum yang diparse. File raksasa (>2 MB) hampir selalu
# generated/minified dan hanya menambah lambat tanpa menambah insight.
MAX_PARSE_BYTES = 2_000_000

# Tree-sitter language pack per nama bahasa. Hanya yang terpasang yang dipakai;
# sisanya jatuh ke regex. "typescript" sengaja tidak ada: grammar TS butuh
# kamus tambahan, dan regex memberi hasil yang cukup untuk kebutuhan saat ini.
_TS_PACKAGES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
}

# Query tree-sitter per bahasa: naga capture = simbol yang di-ingest.
_TS_QUERIES: dict[str, str] = {
    "python": """
        (function_definition) @func
        (class_definition) @cls
        (import_statement name: (dotted_name) @mod)
        (import_statement name: (aliased_import name: (dotted_name) @mod))
        (import_from_statement module_name: (dotted_name) @mod)
        (import_from_statement module_name: (relative_import) @mod)
    """,
    "javascript": """
        (function_declaration) @func
        (generator_function_declaration) @func
        (class_declaration) @cls
        (method_definition) @func
        (variable_declarator
          value: [(arrow_function) (function_expression)]) @func
        (import_statement source: (string) @mod
        (import_statement source: (template_string) @mod
    """,
}

# Regex fallback untuk bahasa tanpa tree-sitter pack. Cukup untuk statistik
# (jumlah simbol + kompleksitas kasar), bukan parser.
_REGEX_SYMBOLS: dict[str, list[tuple[str, str]]] = {
    "typescript": [
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", "class"),
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
         r"(?:async\s*)?\(", "function"),
        (r"^\s*(?:public|private|protected|internal)?\s*(\w+)\s*\([^)]*\)\s*[:{]",
         "method"),
    ],
    "java": [
        (r"^\s*(?:public|private|protected|static|final|abstract|\s)*"
         r"(?:class|interface|enum)\s+(\w+)", "class"),
        (r"^\s*(?:public|private|protected|static|final|synchronized|\s)+"
         r"[\w<>\[\],.\s]+\s+(\w+)\s*\([^;]*\)\s*\{", "function"),
    ],
    "go": [
        (r"^\s*func\s+\(\s*\w+\s+\*?\w+\s*\)\s+(\w+)", "method"),
        (r"^\s*func\s+(\w+)", "function"),
        (r"^\s*type\s+(\w+)\s+struct", "class"),
        (r"^\s*type\s+(\w+)\s+interface", "class"),
    ],
    "ruby": [
        (r"^\s*def\s+([\w?!.]+)", "function"),
        (r"^\s*class\s+(\w+)", "class"),
        (r"^\s*module\s+(\w+)", "class"),
    ],
    "c": [
        (r"^[A-Za-z_][\w\s\*]*\s+\**(\w+)\s*\([^;]*\)\s*\{", "function"),
        (r"^\s*struct\s+(\w+)", "class"),
    ],
    "cpp": [
        (r"^[A-Za-z_][\w\s\*:<>,]*\s+\**(\w+)\s*\([^;]*\)\s*\{", "function"),
        (r"^\s*(?:class|struct)\s+(\w+)", "class"),
    ],
    "rust": [
        (r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", "function"),
        (r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)", "class"),
        (r"^\s*impl(?:<[^>]*>)?\s+(\w+)", "class"),
    ],
}

# Keyword branch untuk estimasi cyclomatic complexity.
_BRANCH_KEYWORDS = (
    "if", "elif", "else", "for", "while", "case", "catch", "except",
    "&&", "||", "and", "or", "?",
)
_BRANCH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(k) for k in _BRANCH_KEYWORDS) + r")(?![A-Za-z0-9_])"
)

# Buang komentar dan string sebelum menghitung branch keyword. Tanpa ini,
# docstring seperti "if the caller returns None" menaikkan skor secara palsu.
_PY_STRIP_RE = re.compile(
    r"'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'[^'\n]*'|\"[^\"\n]*\""
)
_C_STYLE_COMMENT_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_HASH_COMMENT_RE = re.compile(r"#[^\n]*")


def _strip_noise(src: str, lang: str) -> str:
    """Buang komentar + string literal supaya hitungan branch tidak noise."""
    if lang == "python":
        out = _PY_STRIP_RE.sub(" ", src)
        return _HASH_COMMENT_RE.sub(" ", out)
    if lang in ("c", "cpp", "java", "javascript", "typescript", "go", "rust"):
        out = _C_STYLE_COMMENT_RE.sub(" ", src)
        return _PY_STRIP_RE.sub(" ", out)
    if lang in ("ruby",):
        return _HASH_COMMENT_RE.sub(" ", src)
    return src


def calc_complexity(src: str, lang: str = "python") -> int:
    """
    Cyclomatic complexity approx: 1 + jumlah keyword branch.

    Menghitung pada sumber yang sudah dibuang komentar/string-nya — menghitung
    pada sumber mentah membuat docstring dan komentar menginflasi skor secara
    tidak proporsional, yang membuat rank_complexity() useless.
    """
    if not src:
        return 1
    return 1 + len(_BRANCH_RE.findall(_strip_noise(src, lang)))


# ===========================================================================
# 4. Tree-sitter loader (support dua generations API)
# ===========================================================================

_ts_cache: dict[str, Any] = {}
_ts_lock = threading.Lock()
_ts_unavailable: set[str] = set()


def _normalize_captures(raw: Any) -> list[tuple[str, Any]]:
    """
    Samakan bentuk hasil captures() dari dua generations API.

    >= 0.25 : dict[capture_name, list[Node]]  ->  [(name, node), ...]
    <  0.25 : dict[Node, capture_name]        ->  [(name, node), ...]
    """
    out: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str):
                for node in value:
                    out.append((key, node))
            else:
                out.append((str(value), key))
    return out


def _load_ts(lang: str):
    """
    Muat parser tree-sitter untuk satu bahasa, atau None kalau tidak ada.

    Hasil di-cache per proses. Kalau sebuah bahasa sudah terbukti tidak
    tersedia, percobaan berikutnya dilewati supaya ingest repo besar tidak
    pays ImportError berulang thousands kali.
    """
    with _ts_lock:
        if lang in _ts_cache:
            return _ts_cache[lang]
        if lang in _ts_unavailable:
            return None

    loaded = _load_ts_uncached(lang)
    with _ts_lock:
        if loaded is None:
            _ts_unavailable.add(lang)
        else:
            _ts_cache[lang] = loaded
    return loaded


def _load_ts_uncached(lang: str):
    package = _TS_PACKAGES.get(lang)
    if not package:
        return None
    query_src = _TS_QUERIES.get(lang)
    if not query_src:
        return None

    # --- Generation baru (tree-sitter >= 0.25) ---
    try:
        import importlib

        from tree_sitter import Language, Parser, Query, QueryCursor  # type: ignore

        pack = importlib.import_module(package)
        ts_lang = Language(pack.language())      # pack.language() -> PyCapsule
        parser = Parser(ts_lang)
        query = Query(ts_lang, query_src)
        cursor_factory = QueryCursor
        return {
            "api": "new",
            "parse": lambda src: parser.parse(src),
            "captures": lambda root: _normalize_captures(
                cursor_factory(query).captures(root)
            ),
        }
    except Exception:
        pass

    # --- Generation lama (tree-sitter < 0.25, mis. 0.21.3) ---
    try:
        from tree_sitter_languages import get_language, get_parser  # type: ignore

        parser = get_parser(lang)
        ts_lang = get_language(lang)
        query = ts_lang.query(query_src)
        return {
            "api": "legacy",
            "parse": lambda src: parser.parse(src),
            "captures": lambda root: _normalize_captures(query.captures(root)),
        }
    except Exception:
        return None


# ===========================================================================
# 5. Parser per bahasa
# ===========================================================================

def _capture_kind(cap_name: str) -> str:
    if cap_name == "func":
        return "function"
    if cap_name == "cls":
        return "class"
    return "import"


def _parse_tree_sitter(path: Path, lang: str, source: bytes) -> list[dict]:
    ts = _load_ts(lang)
    if ts is None:
        return []
    try:
        tree = ts["parse"](source)
        root = tree.root_node
        symbols: list[dict] = []
        seen: set[tuple[str, int]] = set()
        for cap_name, node in ts["captures"](root):
            if cap_name == "mod":
                # Node yang tertangkap adalah NAMA MODUL-nya langsung
                # (dotted_name / string), bukan seluruh statement import.
                text = node.text.decode("utf-8", errors="ignore").strip()
                name = re.sub(r"""^['"`]|['"`]$""", "", text).strip()
                if not name:
                    continue
                key = (name, node.start_point[0])
                if key in seen:
                    continue
                seen.add(key)
                symbols.append({
                    "name": name, "kind": "import",
                    "line": node.start_point[0] + 1,
                    "complexity": 0, "lines": 1,
                })
                continue

            # Node yang tertangkap adalah definisi utuh, bukan identifier-nya.
            # Nama diambil dari field "name"; body dari node itu sendiri.
            name_node = node.child_by_field_name("name")
            if name_node is None:
                # Arrow function terikat di variable_declarator: nama ada di
                # field "name" tapi body ada di field "value".
                name_node = node
            name = name_node.text.decode("utf-8", errors="ignore").strip()
            if not name or not name.replace("_", "").isalnum():
                continue
            key = (name, node.start_point[0])
            if key in seen:
                continue
            seen.add(key)

            body_node = node
            if node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value is None:
                    continue
                body_node = value
                name = node.child_by_field_name("name").text.decode(
                    "utf-8", errors="ignore"
                ).strip()

            body = body_node.text.decode("utf-8", errors="ignore")
            symbols.append({
                "name": name,
                "kind": _capture_kind(cap_name),
                "line": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1,
                "complexity": calc_complexity(body, lang),
                "lines": node.end_point[0] - node.start_point[0] + 1,
            })
        return symbols
    except Exception:
        return []


def _parse_python_ast(src: str) -> list[dict]:
    """Fallback Python: modul ast bawaan. Dipakai kalau tree-sitter gagal."""
    symbols: list[dict] = []
    try:
        tree = pyast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()

    for node in pyast.walk(tree):
        if isinstance(node, (pyast.FunctionDef, pyast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            body = "\n".join(lines[node.lineno - 1:end])
            symbols.append({
                "name": node.name, "kind": "function",
                "line": node.lineno, "line_end": end,
                "complexity": calc_complexity(body, "python"),
                "lines": end - node.lineno + 1,
            })
        elif isinstance(node, pyast.ClassDef):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            body = "\n".join(lines[node.lineno - 1:end])
            symbols.append({
                "name": node.name, "kind": "class",
                "line": node.lineno, "line_end": end,
                "complexity": calc_complexity(body, "python"),
                "lines": end - node.lineno + 1,
            })
        elif isinstance(node, pyast.Import):
            for alias in node.names:
                symbols.append({
                    "name": alias.name, "kind": "import",
                    "line": node.lineno,
                    "complexity": 0, "lines": 1,
                })
        elif isinstance(node, pyast.ImportFrom):
            if node.module:
                symbols.append({
                    "name": node.module, "kind": "import",
                    "line": node.lineno,
                    "complexity": 0, "lines": 1,
                })
    return symbols


def _parse_regex(src: str, lang: str) -> list[dict]:
    """Fallback terakhir: pola regex per bahasa (kasar, tapi tidak nol)."""
    symbols: list[dict] = []
    patterns = _REGEX_SYMBOLS.get(lang, [])
    if not patterns:
        return symbols
    seen: set[tuple[str, int]] = set()
    for idx, line in enumerate(src.splitlines(), start=1):
        if len(line) > 500:
            continue
        for pattern, kind in patterns:
            m = re.match(pattern, line)
            if not m:
                continue
            name = m.group(1) if m.groups() else None
            if not name or name in ("if", "for", "while", "switch", "return"):
                continue
            if (name, idx) in seen:
                continue
            seen.add((name, idx))
            symbols.append({
                "name": name, "kind": kind, "line": idx,
                "complexity": 1, "lines": 1,
            })
            break
    return symbols


def parse_source(path: Path, lang: str) -> list[dict]:
    """
    Ambil daftar simbol dari satu file. Rantai fallback:

        tree-sitter -> (python: ast) -> regex

    Tidak pernah melempar exception; file yang tidak bisa diparse menghasilkan
    list kosong supaya satu file rusak tidak menghentikan seluruh ingest.
    """
    try:
        if path.stat().st_size > MAX_PARSE_BYTES:
            return []
    except OSError:
        return []

    try:
        source_bytes = path.read_bytes()
    except OSError:
        return []
    if not source_bytes.strip():
        return []

    symbols = _parse_tree_sitter(path, lang, source_bytes)
    if symbols:
        return symbols

    if lang == "python":
        symbols = _parse_python_ast(source_bytes.decode("utf-8", errors="ignore"))
        if symbols:
            return symbols

    return _parse_regex(source_bytes.decode("utf-8", errors="ignore"), lang)



# ===========================================================================
# 6. ingest_repository()  (dulu cortex.understand_repo)
# ===========================================================================

def _iter_repo_files(root: Path) -> Iterator[Path]:
    """Walk repo, skip direktori build/vendor dan file biner."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_FILE_SUFFIXES:
            continue
        yield path


def _link_docs_to_code(
    root: Path, documented_ids: set[str]
) -> int:
    """
    Hubungkan tiap file dokumen ke file kode yang namanya disebut di isinya.

    Dipisah dari ingest utama karena harus jalan SETELUH semua file kode
    tercatat — kalau doc kebaca lebih dulu, tidak ada yang bisa dicocokkan.
    """
    conn = get_conn()
    code_files = [
        (r["id"], r["source_path"] or r["label"])
        for r in conn.execute(
            "SELECT id, label, source_path FROM entities WHERE kind='file'"
        )
    ]
    if not code_files:
        return 0

    # Balik index: nama file -> id. Including stem ("main") supaya
    # "lihat main.py" dan "lihat main" sama-sama ketemu.
    index: dict[str, list[str]] = {}
    for file_id, rel in code_files:
        if not rel:
            continue
        name = Path(rel).name.lower()
        stem = Path(rel).stem.lower()
        index.setdefault(name, []).append(file_id)
        if stem != name:
            index.setdefault(stem, []).append(file_id)

    added = 0
    for doc in conn.execute(
        "SELECT id, source_path FROM entities WHERE kind='doc'"
    ).fetchall():
        doc_path = root / (doc["source_path"] or "")
        try:
            if not doc_path.exists() or doc_path.stat().st_size > MAX_PARSE_BYTES:
                continue
            content = doc_path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if not content:
            continue

        for token in set(re.findall(r"[A-Za-z0-9_.\-]{3,}", content)):
            for file_id in index.get(token, ()):
                if upsert_relation(doc["id"], file_id, "DOCUMENTS", weight=0.8):
                    added += 1
                    documented_ids.add(file_id)
    return added


def _link_imports() -> int:
    """
    Hubungkan file ke file yang di-import-nya dengan relasi DEPENDS_ON.

    Tanpa ini graph cuma consisting dari file -> simbol dan doc -> file,
    sehingga trace_connection() tidak pernah menemukan jalur antara dua file
    dan daftar caller di ask_about() selalu kosong.

    Resolusi nama modul sengaja konservatif: hanya module yang namanya cocok
    dengan file yang benar-benar ada di repo yang dihubungkan, supaya graph
    tidak dipenuhi edge ke stdlib/site-packages yang tidak di-ingest.
    """
    conn = get_conn()

    # nama file (tanpa ekstensi) -> id entity file
    by_stem: dict[str, str] = {}
    by_relpath: dict[str, str] = {}
    for row in conn.execute(
        "SELECT id, label, source_path FROM entities WHERE kind='file'"
    ):
        rel = row["source_path"] or row["label"] or ""
        if not rel:
            continue
        rel_norm = rel.replace("\\", "/").lower()
        by_relpath[rel_norm] = row["id"]
        by_relpath[rel_norm[:-3] if rel_norm.endswith(".py") else rel_norm] = row["id"]
        stem = Path(rel_norm).stem
        # Jangan timpa kalau ada dua file bernama sama di folder berbeda;
        # yang menang adalah yang ditemukan paling awal (deterministik
        # karena iterate ORDER BY id).
        by_stem.setdefault(stem, row["id"])

    if not by_stem:
        return 0

    imports = conn.execute(
        """SELECT id, parent_id, label FROM entities
            WHERE kind='symbol' AND symbol_kind='import'
              AND parent_id IS NOT NULL
            ORDER BY id"""
    ).fetchall()

    added = 0
    for row in imports:
        source_file = row["parent_id"]
        module = (row["label"] or "").strip()
        if not module or not source_file:
            continue

        #Buang relative import: "from . import x" tidak menunjuk file lain.
        if module.startswith("."):
            continue

        parts = module.replace("\\", "/").split("/")
        target = None
        dotted = ".".join(parts)
        if dotted.lower() in by_relpath:
            target = by_relpath[dotted.lower()]
        if target is None:
            for candidate in (parts[-1], dotted.split(".")[-1]):
                if candidate in by_stem:
                    target = by_stem[candidate]
                    break
        if target is None or target == source_file:
            continue
        if upsert_relation(source_file, target, "DEPENDS_ON", weight=0.9):
            added += 1
    return added


def ingest_repository(repo_path: str) -> dict:
    """
    Walk repo, parse simbol, bangun knowledge graph di storage.py.

    Statistik yang dikembalikan:
      files                     file kode yang berhasil diparse
      symbols                   fungsi/kelas/import yang ditemukan
      docs                      file dokumentasi
      edges                     sisi graph yang dibuat
      undocumented_files        file kode yang tidak disinggung dokumen mana pun
      high_complexity_symbols   simbol dengan complexity >= 5
    """
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        return {"ok": False, "error": f"Path tidak ditemukan: {repo_path}"}
    if not root.is_dir():
        return {"ok": False, "error": f"Bukan directory: {repo_path}"}

    started = datetime.now()
    global _repo_root
    _repo_root = root
    stats = {
        "files": 0, "symbols": 0, "docs": 0, "edges": 0,
        "undocumented_files": 0, "high_complexity_symbols": 0,
    }
    graph_diff: list[dict] = []
    doc_count = 0

    # Kind doc ditulis setelah file kode selesai, supaya _link_docs_to_code()
    # punya target. Counter dipakai untuk progres yang jujur.
    for path in _iter_repo_files(root):
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS and ext not in DOC_EXTENSIONS:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            continue

        if ext in SUPPORTED_EXTENSIONS:
            lang = SUPPORTED_EXTENSIONS[ext]
            file_id = f"file::{rel}"
            try:
                line_count = len(
                    path.read_text(encoding="utf-8", errors="ignore").splitlines()
                )
            except OSError:
                line_count = 0

            upsert_entity(
                file_id, "file", rel,
                {"path": rel, "lang": lang, "abs_path": str(path),
                 "lines": line_count},
                line_count=line_count, source_path=rel,
            )
            graph_diff.append({"id": file_id, "type": "file", "name": rel})
            stats["files"] += 1

            for sym in parse_source(path, lang):
                symbol_id = f"symbol::{rel}::{sym['name']}"
                cx = int(sym.get("complexity") or 0)
                if cx >= 5:
                    stats["high_complexity_symbols"] += 1
                changed = upsert_entity(
                    symbol_id, "symbol", sym["name"],
                    {
                        "symbol_kind": sym["kind"],
                        "file": rel,
                        "line": sym.get("line", 0),
                        "lines": sym.get("lines", 0),
                        "complexity": cx,
                    },
                    complexity=cx,
                    line_start=int(sym.get("line") or 0),
                    line_count=int(sym.get("lines") or 0),
                    parent_id=file_id,
                    symbol_kind=sym["kind"],
                    source_path=rel,
                )
                if upsert_relation(file_id, symbol_id, "IMPLEMENTED_BY"):
                    stats["edges"] += 1
                if changed:
                    graph_diff.append({
                        "id": symbol_id, "type": "symbol",
                        "name": sym["name"], "parent": file_id,
                        "complexity": cx,
                    })
                stats["symbols"] += 1
        else:
            doc_id = f"doc::{rel}"
            upsert_entity(doc_id, "doc", rel,
                          {"path": rel, "abs_path": str(path)},
                          source_path=rel)
            graph_diff.append({"id": doc_id, "type": "doc", "name": rel})
            stats["docs"] += 1
            doc_count += 1

        done = stats["files"] + doc_count
        if done % 25 == 0:
            _emit("ingest_progress", {
                "repo": repo_path,
                "current_file": rel,
                "files_done": done,
                "stats_so_far": dict(stats),
            })

    documented_ids: set[str] = set()
    stats["edges"] += _link_docs_to_code(root, documented_ids)
    stats["edges"] += _link_imports()

    conn = get_conn()
    total_files = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE kind='file'"
    ).fetchone()[0]
    stats["undocumented_files"] = int(total_files) - len(documented_ids)

    g = _rebuild_and_swap()

    payload = {
        "repo": repo_path,
        "nodes": graph_diff,
        "stats": dict(stats),
        "ingested_at": started.isoformat(),
    }
    _emit("graph_update", payload)
    record_audit(None, "repo_ingested", {
        "repo": repo_path, "stats": dict(stats),
    })

    return {
        "ok": True,
        "repo": repo_path,
        "stats": stats,
        "node_count": len(g.nodes),
        "edge_count": len(g.edges),
        "duration_seconds": round((datetime.now() - started).total_seconds(), 2),
        "ingested_at": started.isoformat(),
    }


# ===========================================================================
# 7. ask_about()  (dulu cortex.explain_topic)
# ===========================================================================

_SNIPPET_RADIUS = 25


def _relevance(label: str, topic_lower: str) -> float:
    """exact = 1.0, prefix = 0.8, partial = 0.5."""
    name = label.lower()
    if name == topic_lower:
        return 1.0
    if name.startswith(topic_lower):
        return 0.8
    return 0.5


def ask_about(topic: str) -> dict:
    """
    Jawab pertanyaan tentang sebuah entitas di graph.

    relevance: exact 1.0 | prefix 0.8 | partial 0.5. Kalau tidak ada yang
    cocok, return ok=False — bukan diam-diam mengembalikan entitas acak.
    """
    g = _get_graph()
    topic_lower = topic.strip().lower()
    if not topic_lower:
        return {"ok": False, "topic": topic, "message": "Topic kosong."}

    conn = get_conn()
    rows = conn.execute(
        """SELECT id, kind, label, attributes_json, complexity, symbol_kind,
                  source_path, line_start
             FROM entities
            WHERE LOWER(label) LIKE ?""",
        (f"%{topic_lower}%",),
    ).fetchall()

    matches: list[dict] = []
    for row in rows:
        try:
            attrs = json.loads(row["attributes_json"] or "{}")
        except (TypeError, ValueError):
            attrs = {}
        matches.append({
            "id": row["id"],
            "kind": row["kind"],
            "label": row["label"],
            "name": row["label"],          # alias untuk frontend
            "type": row["kind"],           # alias untuk frontend
            "complexity": row["complexity"] or 0,
            "symbol_kind": row["symbol_kind"] or "",
            "source_path": row["source_path"] or "",
            "line_start": row["line_start"] or 0,
            "attributes": attrs,
            "relevance": _relevance(row["label"], topic_lower),
        })

    # Sort by relevance, lalu complexity desc supaya kandidat yang sama
    # relevansinya diurutkan oleh yang paling butuh perhatian.
    matches.sort(key=lambda m: (m["relevance"], m["complexity"]), reverse=True)

    if not matches:
        return {
            "ok": False, "topic": topic,
            "message": f"Tidak ditemukan entitas yang cocok dengan '{topic}' di graph.",
        }

    primary = matches[0]
    related: list[dict] = []
    callers: list[dict] = []

    if primary["id"] in g:
        for nb in g.successors(primary["id"]):
            data = g.nodes[nb]
            edge = g.get_edge_data(primary["id"], nb) or {}
            related.append({
                "id": nb, "label": data.get("label", nb),
                "name": data.get("label", nb), "kind": data.get("kind", ""),
                "type": data.get("kind", ""),
                "relationship": edge.get("relation_type", ""),
                "direction": "outgoing",
            })
        for nb in g.predecessors(primary["id"]):
            data = g.nodes[nb]
            edge = g.get_edge_data(nb, primary["id"]) or {}
            entry = {
                "id": nb, "label": data.get("label", nb),
                "name": data.get("label", nb), "kind": data.get("kind", ""),
                "type": data.get("kind", ""),
                "relationship": edge.get("relation_type", ""),
                "direction": "incoming",
            }
            related.append(entry)
            # Caller = simbol yang menunjuk ke simbol ini. File dan dokumen
            # juga_edge ke simbol, tapi itu bukan "pemanggil".
            if data.get("kind") == "symbol":
                callers.append(entry)

    snippet = _read_snippet(primary)
    cx = primary["complexity"]
    complexity_note = (
        f"⚠️ Complexity tinggi ({cx}) — kandidat refactor." if cx >= 10 else
        f"⚡ Complexity sedang ({cx})." if cx >= 5 else
        f"✅ Complexity rendah ({cx})." if cx else ""
    )

    type_label = {
        "file": "file kode", "symbol": f"{primary['symbol_kind'] or 'simbol'} (simbol kode)",
        "doc": "dokumen", "dependency": "dependensi", "action": "operasi",
    }.get(primary["kind"], primary["kind"])

    if callers:
        how_to_use = (
            f"Dipakai oleh: {', '.join(c['label'] for c in callers[:3])}. "
            f"Lihat file-file tersebut sebagai contoh penggunaan."
        )
    elif primary["kind"] == "symbol" and primary["symbol_kind"] == "function":
        how_to_use = f"Panggil dengan: `{primary['label']}(...)`"
    else:
        how_to_use = ""

    return {
        "ok": True,
        "topic": topic,
        "primary_node": primary,
        "definition": f"**{primary['label']}** adalah {type_label} di graph Synapse.",
        "mental_model": (
            f"'{primary['label']}' adalah entitas bertipe '{primary['kind']}', "
            f"terhubung ke {len(related)} entitas. Caller langsung: {len(callers)}."
        ),
        "complexity_note": complexity_note,
        "how_to_use": how_to_use,
        "example": snippet or "(Tidak ada snippet tersedia)",
        "related_nodes": related[:10],
        "callers": callers[:5],
        "all_matches": [
            {"id": m["id"], "label": m["label"], "name": m["label"],
             "kind": m["kind"], "type": m["kind"],
             "relevance": m["relevance"]}
            for m in matches[:5]
        ],
    }


def _read_snippet(entity: dict) -> str:
    """Baca ±_SNIPPET_RADIUS baris sekitar lokasi simbol."""
    rel = entity.get("source_path") or ""
    line = int(entity.get("line_start") or 0)
    if not rel or line <= 0:
        return ""

    # Prioritaskan abs_path kalau ada (entitas file/doc menyimpannya), lalu
    # source_path yang di-resolve terhadap root repo yang terakhir di-ingest.
    abs_hint = entity["attributes"].get("abs_path")
    candidates = [Path(abs_hint)] if abs_hint else []
    candidates.append(Path(rel))
    if _repo_root is not None:
        candidates.insert(0 if not abs_hint else 1, _repo_root / rel)

    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    start = max(0, line - 1 - _SNIPPET_RADIUS)
    end = min(len(lines), line + _SNIPPET_RADIUS)
    return "\n".join(f"{i + 1:>5}  {lines[i]}" for i in range(start, end))


# ===========================================================================
# 8. review_change()  (dulu cortex.review_artifact)
# ===========================================================================

_INCOMPLETE_MARKERS = ("TODO", "FIXME", "HACK", "XXX", "PASS ", "...", "NOT IMPLEMENTED")

_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"drop\s+table", "DROP TABLE terdeteksi"),
    (r"delete\s+from\s+\w+\s*;", "DELETE tanpa WHERE"),
    (r"truncate\s+table", "TRUNCATE terdeteksi"),
    (r"rm\s+-rf", "rm -rf terdeteksi"),
    (r"os\.remove|shutil\.rmtree", "File delete terdeteksi"),
    (r"subprocess\.(call|run|Popen)", "Subprocess execution"),
    (r"\beval\s*\(", "eval() — potensi code injection"),
    (r"\bexec\s*\(", "exec() — potensi code injection"),
    (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password"),
    (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded secret"),
    (r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]", "Hardcoded API key"),
    (r"ghp_[A-Za-z0-9]{20,}", "Hardcoded GitHub token"),
    (r"alter\s+table", "ALTER TABLE terdeteksi"),
)


def review_change(path_or_diff: str) -> dict:
    """
    Skor 4 dimensi untuk sebuah file ATAU potongan diff/patch.

    Deteksi input: kalau string-nya menunjuk file yang ada, dibaca dari disk;
    selain itu diperlakukan sebagai diff inline. Diff dikenali dari baris
    yang diawali +/- dan hanya baris '+' yang dinilai.
    """
    g = _get_graph()

    is_file = False
    content = ""
    if path_or_diff and len(path_or_diff) < 4096:
        try:
            candidate = Path(path_or_diff).expanduser()
            is_file = candidate.is_file()
        except OSError:
            is_file = False

    if is_file:
        try:
            content = candidate.read_text(
                encoding="utf-8", errors="ignore"
            )[:200_000]
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
    else:
        content = path_or_diff or ""

    lines = content.splitlines()
    added = [l for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in lines if l.startswith("-") and not l.startswith("---")]
    is_diff = bool(added) and bool(removed)
    effective = added if is_diff else lines
    total = max(len(effective), 1)

    markers = sum(
        1 for line in effective
        if any(m in line.upper() for m in _INCOMPLETE_MARKERS)
    )
    completeness = max(0.0, 1.0 - (markers / total) * 10)

    avg_len = sum(len(l.lstrip("+-")) for l in effective) / total
    clarity = 1.0 if avg_len < 80 else max(0.3, 1.0 - (avg_len - 80) / 200)

    lowered = content.lower()
    referenced = sum(
        1 for _, data in g.nodes(data=True)
        if data.get("label") and data["label"].lower() in lowered
    )
    correctness = min(1.0, 0.5 + referenced * 0.1)

    findings = [
        label for pattern, label in _RISK_PATTERNS
        if re.search(pattern, content, re.IGNORECASE)
    ]
    risk = min(1.0, len(findings) * 0.2)

    avg_positive = (completeness + clarity + correctness) / 3
    if risk >= 0.6 or avg_positive < 0.4:
        verdict = "block"
    elif avg_positive < 0.7 or risk >= 0.4:
        verdict = "needs_work"
    else:
        verdict = "pass"

    scores = {
        "completeness": round(completeness, 2),
        "clarity": round(clarity, 2),
        "correctness_vs_spec": round(correctness, 2),
        "risk": round(risk, 2),
    }
    _emit("review_done", {
        "artifact": path_or_diff if is_file else "(diff)",
        "scores": scores, "verdict": verdict, "risk_findings": findings,
    })

    return {
        "ok": True,
        "artifact": path_or_diff if is_file else "(inline diff)",
        "is_file": is_file,
        "is_diff": is_diff,
        "churn": {"added": len(added), "removed": len(removed)} if is_diff else None,
        "scores": scores,
        "verdict": verdict,
        "risk_findings": findings,
        "notes": {
            "incomplete_markers": markers,
            "avg_line_length": round(avg_len, 1),
            "graph_references_found": referenced,
        },
    }


# ===========================================================================
# 9. health_report()  (dulu cortex.repo_health)
# ===========================================================================

HIGH_COMPLEXITY_THRESHOLD = 10
MEDIUM_COMPLEXITY_THRESHOLD = 5


def health_report() -> dict:
    """
    Skor kesehatan repo.

    health_score = 40% doc coverage + 30% dead code + 30% complexity
    Dead code dan complexity diskalakan linear lalu di-clamp di 0, jadi
    1 file ";drop table" saja sudah menurunkan skor dengan proporsional.
    """
    g = _get_graph()
    conn = get_conn()

    total_files = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE kind='file'"
    ).fetchone()[0]

    documented = {
        r["to_id"] for r in conn.execute(
            "SELECT DISTINCT to_id FROM relations WHERE relation_type='DOCUMENTS'"
        )
    }
    doc_coverage = (
        round(len(documented) / total_files * 100, 1) if total_files else 0.0
    )

    dead_candidates: list[dict] = []
    high_cx: list[dict] = []
    for row in conn.execute(
        """SELECT id, label, source_path, line_start, complexity, symbol_kind
             FROM entities WHERE kind='symbol'"""
    ).fetchall():
        cx = row["complexity"] or 0
        if cx >= HIGH_COMPLEXITY_THRESHOLD:
            high_cx.append({
                "id": row["id"], "label": row["label"], "name": row["label"],
                "complexity": cx, "file": row["source_path"] or "",
                "line": row["line_start"] or 0,
            })
        # Import bukan dead code — dia cuma sisi dependency, dan in-degree 0
        # adalah hal yang diharapkan untuk import yang tidak dipakai lokal.
        if row["symbol_kind"] == "import":
            continue
        in_degree = g.in_degree(row["id"]) if row["id"] in g else 0
        if in_degree == 0:
            dead_candidates.append({
                "id": row["id"], "label": row["label"], "name": row["label"],
                "file": row["source_path"] or "", "kind": row["symbol_kind"] or "",
                "line": row["line_start"] or 0,
            })

    high_cx.sort(key=lambda x: x["complexity"], reverse=True)
    dead_candidates.sort(key=lambda x: x["label"])

    isolated = [
        {"id": n, "label": g.nodes[n].get("label", n),
         "name": g.nodes[n].get("label", n),
         "kind": g.nodes[n].get("kind", ""), "type": g.nodes[n].get("kind", "")}
        for n in nx.isolates(g)
        if g.nodes[n].get("kind") != "import"
    ]
    hubs = sorted(
        [
            {"id": n, "label": g.nodes[n].get("label", n),
             "name": g.nodes[n].get("label", n),
             "kind": g.nodes[n].get("kind", ""), "type": g.nodes[n].get("kind", ""),
             "degree": g.degree(n)}
            for n in g.nodes
        ],
        key=lambda x: x["degree"], reverse=True,
    )[:5]

    dead_penalty = min(100.0, len(dead_candidates) * 2)
    cx_penalty = min(100.0, len(high_cx) * 5)
    health_score = round(
        doc_coverage * 0.4 + (100 - dead_penalty) * 0.3 + (100 - cx_penalty) * 0.3,
        1,
    )
    label = (
        "\U0001f7e2 Sehat" if health_score >= 80 else
        "\U0001f7e1 Perlu perhatian" if health_score >= 60 else
        "\U0001f7e4 Butuh perbaikan"
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
        "health_label": label,
        "summary": (
            f"{label} — Skor {health_score}/100. Dokumentasi {doc_coverage}%, "
            f"{len(dead_candidates)} kandidat dead code, {len(high_cx)} fungsi kompleks."
        ),
        "doc_coverage_percent": doc_coverage,
        "total_files": total_files,
        "documented_files": len(documented),
        "dead_code_candidates": dead_candidates[:20],
        "dead_code_count": len(dead_candidates),
        "high_complexity_symbols": high_cx[:10],
        "high_complexity_count": len(high_cx),
        "isolated_nodes_count": len(isolated),
        "isolated_nodes": isolated[:10],
        "hub_nodes": hubs,
    }


# ===========================================================================
# 10. trace_connection()  (dulu cortex.find_path)
# ===========================================================================

def _resolve_entity_id(conn, name: str) -> str | None:
    """Cari id entitas dari nama: exact dulu, baru LIKE."""
    row = conn.execute(
        "SELECT id FROM entities WHERE LOWER(label)=? ORDER BY LENGTH(label) LIMIT 1",
        (name.strip().lower(),),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM entities WHERE LOWER(label) LIKE ? LIMIT 1",
        (f"%{name.strip().lower()}%",),
    ).fetchone()
    return row["id"] if row else None


def trace_connection(from_name: str, to_name: str) -> dict:
    """
    Jalur terpendek antara dua entitas, plus relasi di sepanjang jalur.

    Dicoba dua kali: dulu pada graph berarah (cocok untuk "apa yang mengimpor
    apa"), lalu pada graph tak berarah. Tanpa fallback kedua, pasangan seperti
    (cortex.py, main.py) selalu dijawab "tidak ada jalur" padahal main.py
    memang mengimpor cortex.py — hanya arahnya kebalik. Field "direction"
    memberi tahu pemanggil jalur mana yang dipakai.
    """
    g = _get_graph()
    conn = get_conn()

    from_id = _resolve_entity_id(conn, from_name or "")
    if not from_id:
        return {"ok": False, "error": f"Entitas '{from_name}' tidak ditemukan"}
    to_id = _resolve_entity_id(conn, to_name or "")
    if not to_id:
        return {"ok": False, "error": f"Entitas '{to_name}' tidak ditemukan"}

    path_ids: list[str] = []
    direction = "directed"
    try:
        path_ids = nx.shortest_path(g, source=from_id, target=to_id)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        try:
            path_ids = nx.shortest_path(
                g.to_undirected(as_view=False), source=from_id, target=to_id
            )
            direction = "undirected"
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return {
                "ok": False,
                "error": f"Tidak ada jalur dari '{from_name}' ke '{to_name}'",
                "hint": (
                    "Kedua entitas tidak terhubung. Graph hanya punya sisi "
                    "file->simbol (IMPLEMENTED_BY), file->file (DEPENDS_ON), "
                    "dan doc->file (DOCUMENTS) — belum ada call graph antar simbol."
                ),
            }

    def _label(nid: str) -> str:
        return g.nodes[nid].get("label", nid) if nid in g else nid

    def _kind(nid: str) -> str:
        return g.nodes[nid].get("kind", "") if nid in g else ""

    steps = []
    for i in range(len(path_ids) - 1):
        a, b = path_ids[i], path_ids[i + 1]
        forward = (g.get_edge_data(a, b) or {}).get("relation_type")
        if forward is None:
            forward = (g.get_edge_data(b, a) or {}).get("relation_type", "->")
            steps.append({"from": _label(a), "to": _label(b),
                          "relationship": forward, "traversed": "reverse"})
        else:
            steps.append({"from": _label(a), "to": _label(b),
                          "relationship": forward, "traversed": "forward"})

    return {
        "ok": True,
        "from": from_name, "to": to_name,
        "direction": direction,
        "path_length": len(path_ids) - 1,
        "path": [
            {"id": nid, "label": _label(nid), "name": _label(nid),
             "kind": _kind(nid), "type": _kind(nid)}
            for nid in path_ids
        ],
        "edges": steps,
    }


# ===========================================================================
# 11. rank_complexity()  (dulu cortex.complexity_report)
# ===========================================================================

def _risk_level(cx: int) -> str:
    if cx >= 15:
        return "critical"
    if cx >= HIGH_COMPLEXITY_THRESHOLD:
        return "high"
    if cx >= MEDIUM_COMPLEXITY_THRESHOLD:
        return "medium"
    return "low"


def rank_complexity(top_n: int = 10) -> dict:
    """
    Ranking simbol dengan complexity tertinggi.

    Disortir di SQL, bukan Python: kolom complexity di-index, jadi ini tetap
    cepat untuk repo besar (versi lama memindai attributes_json semua baris).
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, label, source_path, line_start, complexity, line_count,
                  symbol_kind
             FROM entities
            WHERE kind='symbol'
              AND symbol_kind IN ('function', 'class')
              AND complexity > 0
            ORDER BY complexity DESC
            LIMIT ?""",
        (max(1, int(top_n)),),
    ).fetchall()

    results = [
        {
            "id": r["id"], "label": r["label"], "name": r["label"],
            "kind": r["symbol_kind"] or "", "file": r["source_path"] or "",
            "line": r["line_start"] or 0, "complexity": r["complexity"] or 0,
            "lines": r["line_count"] or 0,
            "risk_level": _risk_level(r["complexity"] or 0),
        }
        for r in rows
    ]

    totals = {
        level: conn.execute(
            """SELECT COUNT(*) FROM entities
                WHERE kind='symbol' AND symbol_kind IN ('function','class')
                  AND complexity >= ?""",
            (threshold,),
        ).fetchone()[0]
        for level, threshold in (
            ("critical", 15), ("high", 10), ("medium", 5), ("low", 1),
        )
    }

    return {
        "ok": True,
        "top_n": top_n,
        "results": results,
        "total_returned": len(results),
        "critical_count": totals["critical"],
        "high_count": totals["high"],
        "medium_count": totals["medium"],
        "low_count": totals["low"],
    }


# ===========================================================================
# 12. propose_refactor()  (dulu cortex.suggest_refactor)
# ===========================================================================

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def propose_refactor(entity_name: str) -> dict:
    """
    Saran refactor berbasis metrik graph, diurut dari prioritas tertinggi.

    Saran yangJlalu Already "no_action" berarti metriknya sehat.
    """
    g = _get_graph()
    conn = get_conn()
    row = conn.execute(
        """SELECT id, kind, label, source_path, line_start, line_count,
                  complexity, symbol_kind
             FROM entities WHERE LOWER(label) LIKE ? LIMIT 1""",
        (f"%{(entity_name or '').strip().lower()}%",),
    ).fetchone()
    if not row:
        return {"ok": False, "error": f"Entitas '{entity_name}' tidak ditemukan"}

    nid = row["id"]
    cx = row["complexity"] or 0
    lines = row["line_count"] or 0
    degree = g.degree(nid) if nid in g else 0
    in_degree = g.in_degree(nid) if nid in g else 0
    out_degree = g.out_degree(nid) if nid in g else 0
    has_doc = any(
        (g.get_edge_data(pred, nid) or {}).get("relation_type") == "DOCUMENTS"
        for pred in g.predecessors(nid)
    ) if nid in g else False

    suggestions: list[dict] = []
    if cx >= 15:
        suggestions.append({
            "type": "split_function", "priority": "critical",
            "message": (
                f"Complexity {cx} sangat tinggi. Pecah menjadi beberapa "
                f"fungsi kecil (Single Responsibility Principle)."
            ),
        })
    elif cx >= HIGH_COMPLEXITY_THRESHOLD:
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
                f"Entitas ini punya {degree} koneksi — kemungkinan 'God Object'. "
                f"Pecah menjadi modul lebih kecil."
            ),
        })
    if not has_doc and row["kind"] == "symbol":
        suggestions.append({
            "type": "add_documentation", "priority": "medium",
            "message": "Tidak ada dokumentasi terhubung. Tambahkan docstring atau file .md.",
        })
    if in_degree == 0 and row["symbol_kind"] == "function":
        suggestions.append({
            "type": "dead_code", "priority": "medium",
            "message": "Tidak ada caller di graph — kemungkinan dead code. Pertimbangkan dihapus.",
        })

    if not suggestions:
        suggestions.append({
            "type": "no_action", "priority": "low",
            "message": "Entitas ini sehat — tidak ada saran refactor.",
        })

    suggestions.sort(key=lambda s: _PRIORITY_ORDER.get(s["priority"], 9))

    _emit("refactor_suggestion", {
        "node": row["label"],
        "suggestion_count": len(suggestions),
        "top_priority": suggestions[0]["priority"],
    })

    return {
        "ok": True,
        "node": row["label"], "label": row["label"],
        "kind": row["kind"], "type": row["kind"],
        "metrics": {
            "complexity": cx, "lines": lines, "degree": degree,
            "in_degree": in_degree, "out_degree": out_degree,
            "has_documentation": has_doc,
        },
        "suggestions": suggestions,
    }


# ===========================================================================
# 13. Helper graph untuk endpoint
# ===========================================================================

def graph_stats() -> dict:
    """Ringkasan graph untuk /graph/summary."""
    g = _get_graph()
    by_kind: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        kind = data.get("kind", "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    by_relation: dict[str, int] = {}
    for _, _, data in g.edges(data=True):
        rel = data.get("relation_type", "unknown")
        by_relation[rel] = by_relation.get(rel, 0) + 1
    return {
        "ok": True,
        "node_count": g.number_of_nodes(),
        "edge_count": g.number_of_edges(),
        "nodes_by_kind": by_kind,
        "edges_by_relationship": by_relation,
        "db_path": str(DB_PATH),
    }


def get_graph_snapshot(kind: str | None = None) -> list[dict]:
    """
    Node graph dalam bentuk yang소비 frontend: name/type/meta.

    entities/relations memakai label/kind/attributes_json, sedangkan
    GraphNode di frontend/lib/types.ts mengharapkan name/type/meta.
    Mapping ini yang menutup selisih tipe; tanpa ini CodeGraph dapat node
    dengan semua field undefined.
    """
    g = _get_graph()
    out: list[dict] = []
    for nid, data in g.nodes(data=True):
        if kind and data.get("kind") != kind:
            continue
        out.append({
            "id": nid,
            "name": data.get("label", nid),
            "type": data.get("kind", ""),
            "status": "ok",
            "meta": data.get("meta", {}),
        })
    return out


def get_graph_edges(relationship: str | None = None) -> list[dict]:
    """Edge graph dalam bentuk frontend: source/target/relationship."""
    g = _get_graph()
    out: list[dict] = []
    for src, dst, data in g.edges(data=True):
        rel = data.get("relation_type", "")
        if relationship and rel != relationship:
            continue
        out.append({
            "source": src,
            "target": dst,
            "relationship": rel,
            "confidence": data.get("weight", 1.0),
        })
    return out


# ===========================================================================
# 14. Alias nama lama
# ===========================================================================
# cortex.pyUY dan main.py masih memakai nama lama. Alias ini menjaga kompatibilitas
# tanpa menduplikasi implementasi.

understand_repo = ingest_repository
explain_topic = ask_about
review_artifact = review_change
repo_health = health_report
find_path = trace_connection
complexity_report = rank_complexity
suggest_refactor = propose_refactor
