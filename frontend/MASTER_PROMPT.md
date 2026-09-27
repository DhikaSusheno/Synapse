# Master Prompt — Synapse Frontend

Prompt siap salin untuk AI agent yang melanjutkan pekerjaan frontend Synapse.
Wraps [`PRD.md`](./PRD.md) (scope + bug ledger) dan [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) (tokens + spec 9 halaman).

Konteks produk penuh: [`../SYNAPSE.md`](../SYNAPSE.md).

---

## Cara pakai

Salin blok di bawah ke agent yang bekerja di `frontend/`. Bagian **WORKING AGREEMENT**
bukan opsional — dia yang membuat output agent bisa di-review.

---

## Prompt

````text
You are working in `frontend/` of "Synapse" — a live code graph + control
dashboard for a reversible, conflict-aware guardrail system for AI coding
agents (IBM Bob 2.0 Hackathon).

Stack is fixed and already installed: Next.js 14 (app router) + React 18 +
TypeScript + Tailwind + `react-force-graph-2d`. Backend is FastAPI + SQLite.
Read `package.json` before assuming any library is available. **Zero new
dependencies** — if a feature seems to need one, it does not.

## ROLE

You render state. Rollback logic, conflict detection, and blast radius live in
the backend. If you catch yourself deciding whether an operation should be
rolled back, you are in the wrong file.

## READ FIRST, IN THIS ORDER

1. `../SYNAPSE.md` — product context, data contracts
2. `PRD.md` — current scope, goals, non-goals, and the B-01..B-27 bug ledger
3. `DESIGN_SYSTEM.md` — color tokens, layout shell, spec for the 9 dashboard pages
4. `README.md` — how to run, endpoint map, SSE events

The project's own docs win over this prompt. If they disagree with something
written here, the docs are right — fix this file.

## ROUTES

| Route | What | Rendering |
|---|---|---|
| `/` | 9-page dashboard, 3-column shell | Client, `h-full` inside the root layout flex column |
| `/landing` | Explainer page for hackathon judges | **Server component.** No state, no fetch, no `"use client"` |
| `/api/graph` | Next route proxying backend graph data | Server |

Never put a `position: fixed` banner or bar at `top-0` here. The root layout
is a full-height flex column; anything `fixed` will cover `TopNavbar` and the
`LeftNav` logo. That was bug B-01.

## WORKING AGREEMENT

**Do not ship a control that does not do anything.** A button, chevron, or
`⌘K` hint with no handler is a bug, not a placeholder. Three legal resolutions:

1. Wire it up.
2. Remove the affordance.
3. Write a one-line `ponytail:` comment naming the ceiling and the upgrade path
   — only if it genuinely cannot be built right now.

If you are tempted to add a library, stop and reread the ladder in
`lib/derive.ts` conventions: does it need to exist, can CSS do it, can an
already-installed dependency do it, can it be one line.

**One source of truth for connection status.** Import `useBackendStatus()` from
`hooks/useBackendStatus.ts`. It is a single module-level poller with many
subscribers. Never call `/health` from a component. Two independent polls can
disagree, which is how the UI ended up showing "Live Connection" and "OFFLINE"
at the same time (B-02).

**Mock data must announce itself.** When `NEXT_PUBLIC_USE_LIVE_SSE=false`, the
UI is showing samples, not real runs. `BackendStatusBanner` says `DEMO DATA`.
Never claim mock data as real, in UI copy or in a commit message.

**Never swallow an error.** `catch { return; }` makes "the request failed" and
"there is no data" indistinguishable. Render the backend's own error text when
it gives one, and abort in-flight requests on unmount with `AbortController`.

**Accessibility is not polish.** A `<span>` next to an `<input>` is not a label.
Icon-only buttons need `aria-label`. Switches need `role="switch"` +
`aria-checked`. The project defines `:focus-visible` in `app/globals.css` —
do not remove it and do not suppress the outline without a replacement.

**Content on `/landing` must be verifiable.** Every claim must be checkable
against the code in this repo. No invented traction, user, or performance
numbers. No "revolutionary", "next-generation", "seamless".

## BEFORE YOU WRITE

1. `npm run typecheck` — must be green before you start.
2. Find the sibling file that already does the same thing. Match its shape:
   fetch pattern, error copy, card markup, class naming, state naming.
3. Reuse the shared primitives in `components/shared/` (`RiskBadge`,
   `StatusBadge`, `AgentBadge`, `BackendStatusBanner`) and the panel class
   `rounded-xl border border-slate-800/60 bg-[#0d1117]`.

## PATTERNS THAT ARE ALREADY RIGHT — DO NOT "FIX" THEM

- **`lib/sseStream.ts` is a singleton** — one `/stream` connection, fanout to
  subscribers, exponential backoff. Not per-component.
- **`lib/operations.ts` `decideOperation`** — approve, then execute, in one
  helper with real error handling. Do not inline a second approve-then-execute
  path.
- **`SynapseGraph` animation time is a `useRef`**, not `useState`. Putting it
  back into state causes ~60 re-renders per second.
- **`app/page.tsx` routes 9 pages from one `activePage` state.** There is no
  router. Keep it that way unless asked.
- **Node colors, sizes, and labels live in `lib/nodeVisuals.ts`**, not inline
  in the canvas draw function.
- **`lib/*.ts` files with branches ship with a `lib/*.test.ts`.** `npm test`
  runs `node --test "lib/*.test.ts"`. No test framework, no fixtures, no
  snapshots.
- **A hardcoded UI string needs no test.** A branch, loop, parser, or money path
  does.

## FINISHING

Run all four. Three green does not imply the fourth.

```
npm run lint
npm run typecheck
npm test
npm run build
```

Then report in this shape, one line each, nothing else:

```
[x] what you did
skipped: [what], add when [the condition that justifies it]
```

Update `PRD.md` if you fixed or deferred a bug in the ledger. If you added a
route, add it to this table and to `README.md`.

## DO NOT TOUCH

`backend/` and `security/`. If a UI change needs a new backend endpoint, write
it down as a request at the bottom of `PRD.md` and keep going with the frontend
degraded-but-honest path.
````

---

## Yang sengaja tidak ada di prompt ini

| Tidak ada | Kenapa |
|---|---|
| Daftar aesthetic (warna, font, spacing) | Sudah ada di `DESIGN_SYSTEM.md`; mengulangnya di sini hanya membuat drift |
| Spec 9 halaman | Sudah ada di `DESIGN_SYSTEM.md` |
| Daftar endpoint | Sudah ada di `README.md` |
| Timeline hackathon | Fase ada di `PRD.md` §10 sebagai checklist demo, bukan jadwal kerja |
