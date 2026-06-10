---
name: signal-radar
description: Submit manual market intelligence notes, build replayable analysis inputs, generate Chinese briefs, and apply strict MEMORY_UPDATE records through the TypeScript Signal Radar runtime.
metadata:
  hermes:
    tags: [monitoring, memory, nextjs, typescript, codex-cli]
---

# Signal Radar

Signal Radar is now a Next.js 16.2 TypeScript product. This skill directory keeps configuration, memory files, collector contracts, and references. Runtime code lives in:

```text
app/
packages/signal-radar-core/src/
services/signal-radar-worker/worker.ts
```

## Commands

Install and validate:

```bash
npm install
npm run smoke
npm run typecheck
npm run build
```

Run the Web UI:

```bash
npm run dev
```

Manual fixture job:

```bash
npm run signal-radar -- ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --config signal-radar.config.json \
  --run \
  --provider fixture
```

Manual Codex CLI job:

```bash
npm run signal-radar -- ingest-text \
  --text-file /path/to/input.txt \
  --config signal-radar.config.json \
  --run \
  --provider codex-cli \
  --model gpt-5.4
```

## Contracts

Stable artifact contracts:

- `collector_batch/v1`
- `collector_item/v1`
- `analysis_input/v1`
- `signal-radar-job/v1`
- strict JSON `MEMORY_UPDATE`
- memory audit records

The analyzer must produce a Telegram-ready Chinese brief followed by:

````markdown
### MEMORY_UPDATE
```json
{
  "primary_themes": [],
  "secondary_themes": {},
  "account_notes": {},
  "information_units": [],
  "event_clusters": [],
  "signal_evaluations": [],
  "entity_updates": [],
  "event_updates": [],
  "macro_updates": [],
  "source_assessments": [],
  "alert_candidates": [],
  "contradictions": []
}
```
````

## Boundary Rules

- The collector/input layer only standardizes material.
- The analyzer judges signal value and emits strict memory updates.
- The memory apply layer is the only layer that mutates memory files.
- The Next.js app must not store Hermes/Codex OAuth state.
- Codex CLI is invoked server-side by the worker provider when explicitly selected.
