# WIDO — Roadmap

This is the working plan. It continues the "FASE 2 — RAG en GÜIDO" plan (written 2026-08-20,
before the store went live) and adapts it to what exists now: the store is selling, its CI and
catalog checks are in place, and an operations agent is already in production. From here on this
file is the source of truth; the vault note points here.

## Where we start (2026-10-06)

| Piece | State | Where |
|---|---|---|
| Ops agent (Hermes + Telegram + MCP `guido`, 7 tools) | ✅ in production since 2026-10-05 | this repo |
| Purchase alerts to Telegram (idempotent, retried) | ✅ live, verified with a real order | store repo |
| Audited stock adjustments (`ajustar_stock`, `movimientos_stock`) | ✅ migration 24 applied | store repo |
| Store CI (Lint → Test → Build on Actions + Azure DevOps, ~100 tests) | ✅ | store repo |
| Catalog verifier (front ↔ Supabase diff, fails CI) | ✅ — it is also the future ingest loader | store repo |
| pgvector table `documentos_chunks` + HNSW + `match_documentos` RPC | 🟡 written (migration 21), **not applied** | store repo |
| Knowledge corpus as Markdown | ❌ policies still live inside the store's HTML; size charts inside `start.js` | |
| Golden dataset | ❌ | |
| Langfuse project | ❌ | |

## Decisions already taken

| Decision | Why |
|---|---|
| **One tool layer, two surfaces.** RAG ships as an MCP tool (`buscar_conocimiento`) before any web widget. | It can be exercised from Telegram with zero risk to the store, and the customer assistant inherits the same price/stock guardrails. |
| **Embeddings: `openai/text-embedding-3-small` through OpenRouter** (1536 dims). | Same API key as the chat model; migration 21 already uses `vector(1536)`. With ~25 products the ingest cost is negligible — the chat is what needs sizing. |
| **The agent's model is chosen by evals (M1), not by taste.** Currently `openai/gpt-6-luna-pro` via OpenRouter; candidate: a Claude Sonnet. | The comparison table goes into the README. |
| **Price and stock never live in the vector store.** | They change; retrieved text goes stale. Numbers come from tools. |
| **Retrieval gates CI from day one; the LLM judge starts as a report.** | A flaky judge that blocks merges ends up disabled, and the discipline goes with it. |
| **The thesis sets the calendar.** Milestones are sized for short sessions. | |

---

## M0.5 — Quick win: the agent knows the catalog (from real use, 2026-10-06)

First real question that failed: *"¿qué intervenciones quedan disponibles?"* → the agent answered
with its capability list. Cause: `INTERVENCIONES` is `productos.categoria`, and the variant search
only looks at name / colorway / size / SKU. Not a RAG problem — the data is structured.

- Search also matches `categoria` (and `subcategoria`).
- `ficha_producto(sku | busqueda)` — deterministic product sheet from the catalog: category,
  description, care, whether it's a 1/1, available sizes with stock.
- A short **brand glossary** in `AGENTS.md` (what an *intervención* is, 1/1, the two selvedge denims)
  so the agent maps the brand's vocabulary to tool calls. The long-form knowledge goes to M2/M3.
- The failing conversation becomes the **first eval case** of M1.

---

## M1 — Agent evals (deterministic)

**Goal:** prove the ops agent behaves, and pick its model with data.

The agent's outputs are **actions**, so the eval is deterministic: given a conversation, did it call
the right tool with the right arguments — and did it *not* call the tools it mustn't?

- `evals/agente/casos.yaml` — 30–40 cases, each a short conversation plus expectations:
  - *routing:* "how many baby tees in white?" → `consultar_stock` with a query that resolves to the right SKUs
  - *ambiguity:* "sold a logo tee red M" → asks which product; **no** `preparar_ajuste_stock`
  - *golden rule:* never `confirmar_ajuste` in the same turn as the proposal; never without a "yes"
  - *refusals:* "how much stock is there?" answered **only** after a tool call; out-of-scope requests declined
  - *args:* motive/operation mapping (sale → `descontar`/`venta_manual`, return → `sumar`/`devolucion`)
- Harness: runs the real tool schemas against the candidate model with a **fake** tool backend
  (fixtures of the real catalog — no database writes, no credentials in CI).
- Metrics: tool-selection accuracy, argument accuracy, golden-rule violations (must be 0), cost and
  latency per case.
- CI: the golden-rule cases gate merges; the rest report.

**Done when:** a results table for ≥2 models is in the README and the agent runs the winner.
**CV evidence:** "deterministic tool-use evals gating CI; model chosen on measured accuracy/cost".

## M2 — Corpus + golden dataset

**Goal:** the content the assistant will answer from, in one place.

- `corpus/*.md` with frontmatter (`titulo`, `url_publica`, `seccion`, `actualizado`):
  - **brand**: what GÜIDO CAPUZZI is, the *intervenciones* line (Levi's 517 reworked by hand, 1/1,
    the exclusive leather patch), the denim (Japanese vs. Italian selvedge, regular vs. loose fit),
    hand finishes (distressing, wax, strass, screen print);
  - **products**: descriptions and care instructions (today inside `start.js`);
  - **sizes and measurements**: the 9 fits from `SIZE_CHARTS`, with how to measure;
  - **policies**: terms & conditions, shipping (OCA, retiro coordinado), exchanges & returns.
  One source, two consumers: the store renders it, the ingest chunks it.
- `evals/rag/preguntas.jsonl` — 30–50 **real** questions from Instagram DMs / WhatsApp:
  `{pregunta, respuesta_esperada, fuente_esperada, tipo}`.
  **Owner: Naza** (write them down while answering — this is the task that degrades if postponed).

**Done when:** every policy the store shows exists as Markdown, and the dataset has ≥30 questions with a source each.

## M3 — Retrieval as an MCP tool

- Apply migration 21 (pgvector, HNSW, closed RLS, `match_documentos`).
- `ingest/` — chunk `corpus/` + catalog (reusing the store's catalog extractor), embed via
  OpenRouter, upsert with metadata (`url`, `seccion`, `sku`). Idempotent by content hash.
- `buscar_conocimiento(pregunta)` in the MCP server → top-k chunks **with their public URL**, so
  every answer can cite.
- Retrieval eval on the golden dataset: **hit-rate@k and MRR**, gating CI with a threshold.

**Done when:** WIDO answers "how does the regular-fit Japanese jean fit?" on Telegram with a link
to the source, and the retrieval gate is green.

## M3b — Meta Ads, read-only (requested 2026-10-06)

*"¿Cómo vienen las campañas?"* — campaign numbers are **live data**, so they get a tool, not
embeddings (same rule as stock: text in a vector store goes stale).

- `campanias_meta(periodo)` → spend, impressions, reach, CTR, CPC, purchases (pixel `Purchase`),
  ROAS, per campaign/ad set, from the Marketing API Insights endpoint.
- Read-only by construction: a Business Manager **system-user token with `ads_read` only**, stored
  like the Supabase key (mounted for the MCP server, never in the agent's config). No tool can edit
  or launch a campaign.
- The agent compares and explains; every number comes from the tool.
- Feeds the **morning brief** (yesterday's sales + spend + ROAS in one message).
- Owner action: create the system user and token in Business Manager.

## M4 — Observability

- Langfuse project for WIDO (separate from Mercedino's).
- One **parent span per conversation** (tokens, cost, latency per session) and child spans per
  tool call; for retrieval, the question/chunks pair — what lets you debug a bad answer.
- **Fail-open:** if Langfuse is down, the agent answers anyway.

## M5 — Customer-facing assistant

- `/api/asistente` in the store: server-side only (the LLM key never reaches the browser), streaming,
  **rate-limited from day one** with a monthly spend cap — a public endpoint that spends money per
  request is the site's most obvious abuse vector.
- Isolated React widget, mounted in its own container; it doesn't touch `start.js`, the cart or checkout.
- Answers cite (link to the PDP or policy section); "I don't know" + contact email when the corpus
  has no support; price/stock only through tools.
- LLM-as-judge for **groundedness** on the golden dataset — reporting first, gating later.

## M6 — Prompt management

Version the two prompts that get iterated (assistant + judge) in Langfuse, where a redeploy hurts.
Deliberately **not** adopted in Mercedino, where prompts are vault files — same tool, adopted in one
project and rejected in the other, with the reason written down.

---

## Next small step for the ops agent (not a milestone)

**Morning brief** — the original WIDO idea: a scheduled daily message with yesterday's sales, low
stock, pending shipments and (after M3b) yesterday's ad spend and ROAS. It reuses existing tools;
a candidate after M1.

## Risks

| Risk | Mitigation |
|---|---|
| Thesis time | Milestones are independent and short; M2's dataset can grow in the background |
| Chat cost once public | Rate limiting + monthly cap before M5 ships |
| The storefront doesn't read stock from Supabase (`soldOut` is hand-set in `start.js`) | Alerts and the agent flag zero stock; the real fix lives in the store repo and is pending a decision |
