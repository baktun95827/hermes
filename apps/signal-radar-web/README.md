# Signal Radar Web

The Web surface has moved to the root Next.js App Router:

```text
app/
components/
app/api/ingest-text/route.ts
app/api/jobs/[jobId]/route.ts
```

Run locally:

```bash
npm install
docker compose up -d postgres
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
npm run dev
npm run worker
```

If this local database was created before the Drizzle migration switch, reset the development volume once with `docker compose down -v` before running `npm run db:migrate`.

Then open:

```text
http://127.0.0.1:3000
```

JSON API:

```bash
curl -sS http://127.0.0.1:3000/api/healthz

curl -sS -X POST http://127.0.0.1:3000/api/ingest-text \
  -H 'Content-Type: application/json' \
  -d '{
    "target_code": "300750",
    "title": "英维克液冷讨论",
    "text": "英维克液冷业务被市场重新讨论，但需要公告或订单验证。",
    "user_label": "user_note",
    "requires_verification": true
  }'

curl -sS http://127.0.0.1:3000/api/jobs/<job_id>

curl -sS http://127.0.0.1:3000/api/targets/<code>
```

`/api/targets/<code>` returns `target_read_model/v1`:

```text
overview
fundamentals
segments
concepts
timeline
evidence
quality_gates
latest_changes
```

Admin pages:

- `/`: manual ingest
- `/jobs`: job and queue operations
- `/queue`: dead letters, failed retries, stale leases, and failure groups
- `/memory`: current memory records
- `/memory/<memory_id>`: Git-like JSON diff history
- `/evidence`: evidence ledger
- `/quality`: quality gate queue
- `/targets/<code>`: target read-model skeleton

Current product API scope:

- target read projection for future consumer pages
- evidence and quality gate inspection
- no crawler scheduling UI yet
- no manual memory editor

Environment variables:

- `XRADAR_CONFIG`: config path, defaults to `signal-radar.config.json`
- `DATABASE_URL`: Postgres connection string. Required for the product runtime.
- `XRADAR_ANALYZER_PROVIDER`: `fixture` or `codex-cli`, defaults to `fixture`
- `XRADAR_CODEX_MODEL`: Codex model, defaults to `gpt-5.4`
