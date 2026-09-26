"""
cortex.py — Shim kompatibilitas. Implementasi pindah ke engine.py.

Tujuh fungsi di sini tidak lagi punya implementasi sendiri; semuanya meneruskan
ke engine.py. Modul ini dipertahankan karena main.py dan frontend masih
memakai nama lama:

    cortex.understand_repo   -> engine.ingest_repository
    cortex.explain_topic     -> engine.ask_about
    cortex.review_artifact   -> engine.review_change
    cortex.repo_health       -> engine.health_report
    cortex.find_path         -> engine.trace_connection
    cortex.complexity_report -> engine.rank_complexity
    cortex.suggest_refactor  -> engine.propose_refactor

Kenapa tidak dihapus: guardian.py memakai `import cortex` untuk SSE, dan
main.py memanggil ketujuh fungsi di atas. Menghapus modul ini akan
memecahkan keduanya tanpa manfaat.

PERUBAHAN PERILAKU YANG PENTING
--------------------------------
Dulu cortex menulis ke tabel legacy nodes/edges di synapse.db. Sekarang
graph disimpan di entities/relations di synapse_v2.db (lewat storage.py).
Konsekuensi:
  - Graph hasil ingest_repository() tidak lagi muncul di query SQL mentah
    terhadap synapse.db. Endpoint /graph/nodes dan /graph/edges sudah
    diarahkan ke storage.py.
  - guardian.py TIDAK terpengaruh: operasinya tetap di tables operations/
    approvals di synapse.db, dan itu memang tidak ikut pindah.

Event SSE (set_event_loop, subscribe_sse, unsubscribe_sse) juga pindah ke
engine.py. Yang di sini cuma alias, supaya main.py dan guardian.py tidak
perlu diubah.
"""

from __future__ import annotations

import warnings

import engine

# ---------------------------------------------------------------------------
# Fungsi analisis
# ---------------------------------------------------------------------------

understand_repo = engine.ingest_repository
explain_topic = engine.ask_about
review_artifact = engine.review_change
repo_health = engine.health_report
find_path = engine.trace_connection
complexity_report = engine.rank_complexity
suggest_refactor = engine.propose_refactor

# Nama baru, supaya kode baru tidak perlu lewat "cortex" sama sekali.
ingest_repository = engine.ingest_repository
ask_about = engine.ask_about
review_change = engine.review_change
health_report = engine.health_report
trace_connection = engine.trace_connection
rank_complexity = engine.rank_complexity
propose_refactor = engine.propose_refactor

# ---------------------------------------------------------------------------
# Event bus SSE
# ---------------------------------------------------------------------------

set_event_loop = engine.set_event_loop
subscribe_sse = engine.subscribe_sse
unsubscribe_sse = engine.unsubscribe_sse
_emit = engine._emit

# Akses graph untuk kode yang butuh (mis. endpoint /graph/*).
get_graph_snapshot = engine.get_graph_snapshot
get_graph_edges = engine.get_graph_edges
graph_stats = engine.graph_stats

__all__ = [
    # nama lama (dipakai main.py & frontend)
    "understand_repo", "explain_topic", "review_artifact", "repo_health",
    "find_path", "complexity_report", "suggest_refactor",
    # nama baru
    "ingest_repository", "ask_about", "review_change", "health_report",
    "trace_connection", "rank_complexity", "propose_refactor",
    # SSE
    "set_event_loop", "subscribe_sse", "unsubscribe_sse",
    # graph
    "get_graph_snapshot", "get_graph_edges", "graph_stats",
]


def _warn_legacy_use() -> None:
    warnings.warn(
        "cortex.py sudah menjadi shim; implementasi ada di engine.py. "
        "Impor engine langsung di kode baru.",
        DeprecationWarning,
        stacklevel=3,
    )
