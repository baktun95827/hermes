---
name: signal-radar
description: Submit manual market intelligence notes to the Signal Radar TypeScript product and inspect generated job artifacts.
metadata:
  adapter:
    product: signal-radar
    runtime: nextjs-typescript
---

# Signal Radar Hermes Adapter

This is a thin adapter for an external Hermes runtime. Signal Radar itself is a Next.js and TypeScript product; Hermes should not own product state, memory, credentials, jobs, or scheduling inside this repository.

## Boundary

- Use the product CLI from the Signal Radar repository root.
- Keep Hermes sessions, OAuth state, gateway state, logs, and cron metadata outside the product repo.
- Do not write into a root `skills/` directory in this repo.
- Do not call legacy script commands. The product runtime is TypeScript.

## Commands

Run a fixture job:

```bash
npm run signal-radar -- ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --config signal-radar.config.json \
  --run \
  --provider fixture
```

Run with Codex CLI:

```bash
npm run signal-radar -- ingest-text \
  --text-file /path/to/input.txt \
  --config signal-radar.config.json \
  --run \
  --provider codex-cli \
  --model gpt-5.4
```

Validate the product:

```bash
npm run smoke
npm run typecheck
npm run build
```

## Artifact Contract

The adapter should inspect product artifacts only through these contracts:

- `signal-radar-job/v1`
- `collector_batch/v1`
- `collector_item/v1`
- `analysis_input/v1`
- strict JSON `MEMORY_UPDATE`
- memory audit records
