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
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
npm run dev
```

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
    "title": "英维克液冷讨论",
    "text": "英维克液冷业务被市场重新讨论，但需要公告或订单验证。",
    "user_label": "user_note",
    "requires_verification": true
  }'

curl -sS http://127.0.0.1:3000/api/jobs/<job_id>
```

Environment variables:

- `XRADAR_CONFIG`: config path, defaults to `signal-radar.config.json`
- `DATABASE_URL`: Postgres connection string. Required for the product runtime.
- `XRADAR_ANALYZER_PROVIDER`: `fixture` or `codex-cli`, defaults to `fixture`
- `XRADAR_CODEX_MODEL`: Codex model, defaults to `gpt-5.4`
