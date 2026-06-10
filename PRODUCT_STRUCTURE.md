# Signal Radar Product Structure

Signal Radar is a TypeScript-first Next.js product. The product runtime lives in the root app, worker, and shared TypeScript package.

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
  Optional external adapter. It is not part of the product runtime.
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

Product code should depend on these JSON contracts, not on agent sessions, browser crawler internals, or compatibility modules.

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
/opt/xradar/ # product code
```

The repository root intentionally does not carry agent persona files, gateway state, cron locks, bundled skill catalogs, or OAuth state. If an external agent runtime is used, install the thin adapter from `integrations/hermes/skills/signal-radar/` into that runtime and keep its sessions, credentials, logs, and caches outside this repo.

If Codex CLI is used, it is invoked server-side by the worker provider and returns structured artifacts.
