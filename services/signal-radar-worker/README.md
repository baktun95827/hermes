# Signal Radar Worker

The worker is now TypeScript and runs through `tsx`.

Responsibilities:

- create ingestion jobs
- build `analysis_input/v1`
- invoke analyzer providers
- validate and apply strict `MEMORY_UPDATE`
- write audit records and job status

Run with fixture provider:

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

For regression tests that should not call external Codex services, set `XRADAR_CODEX_BIN` to a local shim that implements:

```text
codex exec --output-last-message <path>
```

Run local smoke checks:

```bash
npm run smoke
```
