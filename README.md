# WIDO — the operations agent for GÜIDO CAPUZZI

WIDO runs the day-to-day operations of [GÜIDO CAPUZZI](https://güidocapuzzi.com), an independent
Argentine fashion brand, from a Telegram chat. It is an LLM agent ([Hermes Agent](https://github.com/NousResearch/hermes-agent))
on top of a **deterministic tool layer** exposed as an [MCP](https://modelcontextprotocol.io) server:
the model understands the request, the tools own every number and every write.

**In production since 2026-10-05**, on a Linux VPS, against the store's live Supabase database.

```
                   ┌── Telegram · Hermes Agent  (internal ops)        ← live
MCP server `guido` ┤
 one tool layer    └── /api/asistente · web widget (customers)       ← roadmap M5
   ├─ consultar_stock · ventas_recientes · movimientos_recientes     ← live
   ├─ preparar_ajuste_stock → confirmar_ajuste  (human-in-the-loop)  ← live
   └─ buscar_conocimiento  (RAG over pgvector, with citations)       ← roadmap M3
```

## What it does today

- **Purchase alerts.** Every paid order lands in the team chat with items, SKUs, the stock left,
  customer, delivery method and amounts — and shouts when a variant hits zero.
- **Stock by chat.** *"Sold a logo tee, size M, at the fair"* → WIDO asks which tee if the request is
  ambiguous, proposes `4 → 3`, and writes **only after an explicit "yes"**. Every adjustment is
  audited (who, when, why, before → after) and can be undone.
- **Sales questions.** Recent paid orders, shipping state, what moved this week.

## Design decisions

These are the parts worth reading. Each one exists because the obvious alternative fails in a
specific way.

| Decision | Why |
|---|---|
| **The LLM never produces a number.** Stock, prices and sales come only from tools that query Postgres. | A model that "remembers" stock is reporting a stale number. The agent's instructions forbid answering stock without a tool call, and its built-in memory is **off** (it was injecting old facts into every prompt — learned on a sibling agent, see [Lineage](#lineage)). |
| **Writes are two-phase: dry-run → token → confirm.** `preparar_ajuste_stock` returns the proposal and a single-use, 10-minute token; only `confirmar_ajuste(token)` writes. | The confirmation is enforced by the tool contract, not only by the prompt. A token can't be reused, and a changed request means a new proposal. |
| **Atomic, audited writes in the database.** `ajustar_stock()` locks the row (`FOR UPDATE`), refuses negative stock, and records the movement in the same transaction. Executable by `service_role` only. | Two people selling the last unit at once can't both win, and a number that "doesn't add up" can be reconstructed. |
| **Ambiguity is a question, not a guess.** Search returns every matching variant; without an exact SKU there is no proposal. | "Logo tee red M" matches two different products in the real catalog. |
| **Purchase alerts bypass the agent.** The store's backend calls the Telegram Bot API directly, with its own idempotency flag that is released on failure so the next pass retries. | An alert about money can't depend on an LLM process being up. |
| **Least privilege for the agent runtime.** Terminal, file, code-execution, browser and delegation toolsets are disabled on Telegram; the database key is mounted read-only for the MCP server alone and never stored in the agent's config. | An agent that can read files can read its own credentials. |

## Repository

| Path | What |
|---|---|
| `guido_mcp/server.py` | MCP server (FastMCP, stdio) — the 7 tools Hermes calls |
| `guido_mcp/stock.py` | Pure logic: variant search (accent/gender-insensitive), adjustment proposals, confirmation tokens |
| `guido_mcp/supabase_rest.py` | Supabase access over PostgREST (`httpx`, no extra SDK) |
| `tests/` | `pytest` — runs in CI on every push |
| `deploy/` | Dockerfile (on top of the official Hermes image), compose, MCP launcher, agent identity (`SOUL.md`, `AGENTS.md`) and the runbook |
| `docs/ROADMAP.md` | Where this is going: evals, RAG, observability, the customer-facing assistant |

The store itself (Next.js + Supabase + Vercel) lives in [`naza89/gu.idocapuzzi.com`](https://github.com/naza89/gu.idocapuzzi.com):
the database migration behind `ajustar_stock` and the purchase-alert code are there.

> Operational docs (runbook, agent identity, tool descriptions) are in Spanish — they're written
> for the team that runs the brand, and the agent speaks Argentine Spanish.

## Run it

```bash
pip install -r requirements.txt
python -m pytest

# MCP server over stdio (needs a Supabase service_role key)
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python -m guido_mcp.server
```

Production deploy (Docker on a VPS, next to another Hermes agent): [`deploy/README.md`](deploy/README.md).

## Roadmap

| | Milestone | Status |
|---|---|---|
| M0 | Ops agent in production + standalone repo | ✅ |
| M0.5 | The agent knows the catalog — category search, product sheets, brand glossary | next |
| M1 | **Agent evals** — deterministic: right tool, right args, never writes without a "yes"; picks the model with data | |
| M2 | Knowledge corpus (brand, *intervenciones*, denim, product copy, sizes & measurements, policies) + golden dataset of real customer questions | |
| M3 | Retrieval as an MCP tool — pgvector, citations, hit-rate@k / MRR as a CI gate | |
| M3b | Meta Ads, read-only — campaign insights as a tool (live numbers never go to the vector store) | |
| M4 | Observability — Langfuse, one parent span per conversation, fail-open | |
| M5 | Customer-facing assistant on the store — rate-limited endpoint, LLM-as-judge for groundedness | |
| M6 | Prompt management where it pays off | |

Details and the reasoning behind the order: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Lineage

WIDO reuses the patterns of **El Mercedino**, a pricing agent built for a meat-packing business
(same stack: Hermes + MCP + a deterministic engine, the same dry-run → confirm rule). Where the two
differ is the interesting part: Mercedino's outputs are **actions**, so its evals are deterministic;
WIDO adds a customer-facing assistant whose output is **free text**, which is where an LLM judge
earns its place.
