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
  Runtime-neutral contracts, ingestion, analysis-input, Drizzle read models, Postgres store, evidence ledger, quality gates, MEMORY_UPDATE, memory versioning, queue reliability, and diff logic.
services/signal-radar-worker/
  TypeScript worker CLI, Postgres queue claim loop, and provider execution layer.
scripts/
  TypeScript smoke and database integration checks.
db/schema.ts
  Drizzle source schema for jobs, queue, collector data, evidence, quality gates, artifacts, memory versions, and audit events.
drizzle/
  Drizzle-generated SQL migrations and metadata.
drizzle.config.ts
  Drizzle Kit configuration for Postgres migrations.
compose.yaml
  Local Postgres service for development.
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
- useful evidence snapshots, source identity, duplicate markers, and filtering decisions
- quality gates that distinguish hard evidence, weak evidence, rumors, speculation, and contradictions
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
- useful evidence snapshots derived from collector items
- source quality and evidence quality classifications
- strict `MEMORY_UPDATE`
- `agent_output_contract/v1` fields inside agent claims: claim, evidence links, memory action, confidence, and risk reason
- `target_read_model/v1` API projection: overview, fundamentals, segments, concepts, timeline, evidence, quality gates, and latest changes
- Postgres-backed memory snapshots and patches for product runtime
- memory audit records
- `signal-radar-job/v1`

Runtime database boundary:

- Drizzle Kit owns schema and migrations through `db/schema.ts` and `drizzle/`.
- New read-side product code should use the typed Drizzle runtime helper in `packages/signal-radar-core/src/drizzle.ts`.
- Existing worker write paths may keep focused `pg` SQL while they remain transactional and covered by DB smoke tests.

Product code should depend on these JSON contracts, not on agent sessions, browser crawler internals, or compatibility modules.

Provider code should stay behind narrow adapters. Codex CLI is acceptable as the first analyzer provider; Claude and GPT API providers should fit the same worker contract.

Current scope:

- Keep crawler scheduling out of the runtime foundation for now.
- Do not build manual memory editing or rollback workflows. Memory is agent-written; operators inspect evidence, quality gates, versions, and failures.
- Keep targets simple at first: a public-market code plus optional exchange/country metadata. Concepts, themes, segments, and industry-chain facts are agent-managed memory.
- Save useful or potentially useful evidence snapshots, not every low-value crawled fragment as product memory.

## Commands

Install dependencies:

```bash
npm install
```

Run the product UI:

```bash
cp .env.example .env
docker compose up -d postgres
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
npm run dev
```

After the Drizzle migration switch, reset any old local development database that was created by the previous raw SQL runner:

```bash
docker compose down -v
docker compose up -d postgres
npm run db:migrate
```

Open:

```text
http://127.0.0.1:3000
```

Queue a manual text job with the fixture provider:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --target-code 300750 \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --provider fixture
```

Process one queued job:

```bash
npm run worker:once
```

Run a persistent local worker:

```bash
npm run worker
```

Run smoke validation:

```bash
npm run smoke
DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar npm run smoke:db
npm run typecheck
npm run build
```

Admin surfaces:

- `/` manual ingest
- `/jobs` queue and job operations
- `/queue` dead letters, failed retries, stale leases, and failure aggregation
- `/jobs/<job_id>` job artifacts, logs, memory update, and memory versions
- `/memory` current memory records
- `/memory/<memory_id>` current payload and version diff history
- `/evidence` evidence ledger for useful, duplicate, weak, rumor, speculation, and hard-evidence snapshots
- `/quality` quality gate queue for watch, block, skip, and agent recheck signals
- `/targets/<code>` basic target read-model skeleton for memory, changes, evidence, and quality signals
- `/api/targets/<code>` `target_read_model/v1` JSON for future consumer pages

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
