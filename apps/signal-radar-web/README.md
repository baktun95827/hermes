# Signal Radar Web

This directory is reserved for the product Web UI and API.

Initial responsibility:

- accept manual text, URL, or research note input
- create a source-agnostic ingestion job or `collector_batch/v1`
- show job status, summary, `MEMORY_UPDATE`, and memory audit result

Boundary rules:

- Web/API must not directly edit memory files or database rows.
- Web/API must not hold Hermes/Codex OAuth state.
- Web/API should submit work to `services/signal-radar-worker`.
- Manual input is a normal source, not a side channel.

The first useful endpoint should be:

```text
POST /ingest-text
```

Expected flow:

```text
manual text
-> collector_batch/v1
-> analysis input
-> analyzer worker
-> MEMORY_UPDATE proposal
-> MemoryBackend commit
-> audit/result shown in Web
```

## Current MVP

Run locally:

```bash
python3 apps/signal-radar-web/server.py
```

Then open:

```text
http://127.0.0.1:8765
```

JSON API:

```bash
curl -sS http://127.0.0.1:8765/api/healthz

curl -sS -X POST http://127.0.0.1:8765/api/ingest-text \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "英维克液冷讨论",
    "text": "英维克液冷业务被市场重新讨论，但需要公告或订单验证。",
    "user_label": "user_note",
    "requires_verification": true
  }'

curl -sS http://127.0.0.1:8765/api/jobs/<job_id>
```

Environment variables:

- `XRADAR_CONFIG`: config path, defaults to `skills/signal-radar/config.yaml`
- `XRADAR_JOBS_DIR`: jobs directory, defaults to `data/jobs`
- `XRADAR_ANALYZER_PROVIDER`: `fixture` or `codex-cli`, defaults to `fixture`
- `XRADAR_CODEX_MODEL`: Codex model, defaults to `gpt-5.4`

Use `fixture` for smoke tests. Use `codex-cli` only when you intend to call Codex:

```bash
XRADAR_ANALYZER_PROVIDER=codex-cli python3 apps/signal-radar-web/server.py
```

`GET /api/jobs/<job_id>` returns the job status, summary, parsed
`memory_update`, and memory audit metadata. Invalid job IDs return `400`
instead of resolving arbitrary paths under the jobs directory.
