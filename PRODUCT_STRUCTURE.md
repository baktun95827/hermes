# Signal Radar Product Structure

Signal Radar is a TypeScript-first Next.js product. The product runtime lives in the root app, worker, and shared TypeScript package.

The current repository is the early admin and runtime foundation for a larger consumer-facing market intelligence product. The long-term system maintains real-time fundamental memory for thousands of public-market targets through automated agents, not manual operator review.

## Current Layout

```text
app/
  Next.js App Router pages and API routes.
components/
  Product UI components for ingest, status, and job inspection.
packages/signal-radar-core/src/
  Runtime-neutral contracts, ingestion, analysis-input, Postgres store, MEMORY_UPDATE, memory versioning, and diff logic.
services/signal-radar-worker/
  TypeScript worker CLI, Postgres queue claim loop, and provider execution layer.
scripts/
  TypeScript smoke tests and database migration runner.
db/migrations/
  Postgres schema for jobs, queue, collector data, artifacts, memory versions, and audit events.
integrations/hermes/
  Optional external adapter. It is not part of the product runtime.
data/
  Local runtime data for development. Do not commit real runtime job output.
```

## Product Architecture Direction

Near-term runtime:

```text
Admin UI
-> API routes
-> job queue / worker
-> collector contracts
-> analyzer provider adapter
-> strict MEMORY_UPDATE
-> memory version store
-> audit and diff views
```

Target production runtime:

```text
Consumer target UI
-> target, concept, industry, timeline, macro, and source APIs
-> Postgres-backed memory snapshots and patches
-> automated collector and analyzer workers
-> provider adapters for Codex, Claude, GPT APIs, and future analyzers
```

Postgres should become the durable product store for:

- targets and identifiers
- source items and normalized collector batches
- jobs, provider runs, queue state, and logs
- memory snapshots, memory patches, and memory audit events
- diffable memory version history
- target concepts, business segments, industry-chain relations, timelines, and macro/policy context

The local file artifact path is no longer a product constraint. It can remain as a temporary provider/debug bridge, but the durable runtime state should be Postgres-first.

## Runtime Boundary

The product mainline is:

```text
Next.js UI/API
-> Postgres job queue
-> services/signal-radar-worker/worker.ts db-work-once
-> packages/signal-radar-core/src
-> fixture provider or Codex CLI provider
-> Postgres MEMORY_UPDATE version/diff/audit path
```

Durable contracts:

- `collector_batch/v1`
- `collector_item/v1`
- `analysis_input/v1`
- strict `MEMORY_UPDATE`
- Postgres-backed memory snapshots and patches for product runtime
- memory audit records
- `signal-radar-job/v1`

Product code should depend on these JSON contracts, not on agent sessions, browser crawler internals, or compatibility modules.

Provider code should stay behind narrow adapters. Codex CLI is acceptable as the first analyzer provider; Claude and GPT API providers should fit the same worker contract.

## Commands

Install dependencies:

```bash
npm install
```

Run the product UI:

```bash
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

Queue a manual text job with the fixture provider:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --provider fixture
```

Process one queued job:

```bash
npm run signal-radar -- db-work-once
```

Run smoke validation:

```bash
npm run smoke
npm run typecheck
npm run build
```

Use Codex CLI intentionally:

```bash
XRADAR_ANALYZER_PROVIDER=codex-cli npm run dev
```

By default, product runtime state expects `DATABASE_URL`. Ignored `data/` artifacts are only a temporary compatibility/debug path.

## Deployment Shape

Keep runtime credentials and product code separate:

```text
/opt/xradar/ # product code
```

The repository root intentionally does not carry agent persona files, gateway state, cron locks, bundled skill catalogs, or OAuth state. If an external agent runtime is used, install the thin adapter from `integrations/hermes/skills/signal-radar/` into that runtime and keep its sessions, credentials, logs, and caches outside this repo.

If Codex CLI is used, it is invoked server-side by the worker provider and returns structured artifacts.
