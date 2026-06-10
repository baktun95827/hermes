# Signal Radar Database

Postgres is the product source of truth for jobs, queue state, collector input, provider artifacts, memory versions, diffs, and audit events.

Run migrations:

```bash
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
```

Queue and process one manual job:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --provider fixture

npm run signal-radar -- db-work-once
```

The worker claims jobs with `FOR UPDATE SKIP LOCKED`. Memory writes are stored as current records plus append-only versions with JSON diffs.
