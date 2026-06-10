# Signal Radar Database

Postgres is the product source of truth for jobs, queue state, collector input, useful evidence snapshots, source quality, quality gates, provider artifacts, memory versions, diffs, and audit events.

Schema and migrations are managed by Drizzle:

- `db/schema.ts`: Drizzle source schema
- `drizzle/`: Drizzle-generated migrations and metadata
- `drizzle.config.ts`: Drizzle Kit config

The previous raw SQL migration runner has been removed. If a local database was created before the Drizzle switch, reset the development volume once:

```bash
docker compose down -v
```

Run migrations:

```bash
docker compose up -d postgres
export DATABASE_URL=postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar
npm run db:migrate
```

Generate a new migration after editing `db/schema.ts`:

```bash
npm run db:generate
npm run db:check
```

Queue and process one manual job:

```bash
npm run signal-radar -- enqueue-ingest-text \
  --target-code 300750 \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --provider fixture

npm run worker:once
```

The worker claims jobs with `FOR UPDATE SKIP LOCKED`. Memory writes are agent-owned and stored as current records plus append-only versions with JSON diffs. Evidence snapshots and quality gates preserve why a memory update was allowed, skipped, treated as rumor/speculation, or marked as weak.

Run a persistent worker:

```bash
npm run worker
```

Run the DB integration smoke:

```bash
npm run smoke:db
```
