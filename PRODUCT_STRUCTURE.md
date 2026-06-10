# Signal Radar Product Structure

Signal Radar is now a TypeScript-first Next.js product. The former Python MVP has been migrated into a Next.js 16.2 application plus shared TypeScript runtime modules.

## Current Layout

```text
app/
  Next.js App Router pages and API routes.
components/
  Product UI components for ingest, status, and job inspection.
packages/signal-radar-core/src/
  Runtime-neutral contracts, ingestion, analysis-input, MEMORY_UPDATE, memory, and audit logic.
services/signal-radar-worker/
  TypeScript worker CLI and provider execution layer.
scripts/
  TypeScript smoke tests.
integrations/hermes/
  Optional Hermes integration notes.
skills/signal-radar/
  Skill metadata, config, collector contracts, memory files, and references.
data/
  Local runtime data for development. Do not commit real runtime job output.
```

## Runtime Boundary

The product mainline is:

```text
Next.js UI/API
-> services/signal-radar-worker/worker.ts
-> packages/signal-radar-core/src
-> fixture provider or Codex CLI provider
-> TypeScript MEMORY_UPDATE apply/audit path
```

Durable contracts:

- `collector_batch/v1`
- `collector_item/v1`
- `analysis_input/v1`
- strict `MEMORY_UPDATE`
- file-backed memory artifacts
- memory audit records
- `signal-radar-job/v1`

New product code should depend on these JSON contracts, not on Hermes sessions, browser crawler internals, or Python compatibility modules.

## Commands

Install dependencies:

```bash
npm install
```

Run the product UI:

```bash
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

Run a manual text job with the fixture provider:

```bash
npm run signal-radar -- ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --config signal-radar.config.json \
  --run \
  --provider fixture
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

By default, product runtime state writes under ignored `data/signal-radar/`.

## Deployment Shape

Keep runtime credentials and product code separate:

```text
/opt/xradar/              # product code
/opt/hermes/ or ~/.hermes # optional Hermes runtime, sessions, auth, gateway state
```

The Next.js app must not store Hermes/Codex OAuth state. If Codex CLI is used, it is invoked server-side by the worker provider and returns structured artifacts.
