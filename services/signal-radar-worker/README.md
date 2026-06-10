# Signal Radar Worker

The worker is now TypeScript and runs through `tsx`.

Responsibilities:

- create Postgres-backed ingestion jobs
- claim queued jobs with `FOR UPDATE SKIP LOCKED`
- build `analysis_input/v1`
- invoke analyzer providers
- validate and apply strict `MEMORY_UPDATE`
- write Postgres memory versions, diffs, audit records, logs, and job status

Queue with fixture provider:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --provider fixture
```

Process one queued job:

```bash
npm run worker:once
```

Run continuously:

```bash
npm run worker
```

Run with Codex CLI:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --text-file /path/to/input.txt \
  --provider codex-cli \
  --model gpt-5.4
```

For regression tests that should not call external Codex services, set `XRADAR_CODEX_BIN` to a local shim that implements:

```text
codex exec --output-last-message <path>
```

Run local smoke checks:

```bash
npm run smoke
npm run smoke:db
```
