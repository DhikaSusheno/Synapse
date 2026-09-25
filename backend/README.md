# Backend

Owners: [@DhikaSusheno](https://github.com/DhikaSusheno) (BE-1 · Guardian), [@Masrendra](https://github.com/Masrendra) (BE-2 · Cortex)

- **Guardian**: `propose_operation` / `execute_operation`, snapshot + rollback + verification, conflict detection.
- **Cortex**: `understand_repo` (tree-sitter ingest) + `explain_topic` (mentor) + `review_artifact`, SSE stream.

MCP server (FastAPI). Schema and rule table: see section 4 of [`../SYNAPSE.md`](../SYNAPSE.md).

`pip install -r requirements.txt && uvicorn main:app` — no other services required.
