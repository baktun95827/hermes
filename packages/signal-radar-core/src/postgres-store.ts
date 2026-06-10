import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import { buildManualCollectorBatch, timestampSlug } from "./manual-ingest";
import { getSharedPostgresPool, jsonb, withPostgresTransaction } from "./postgres";
import type { CollectorBatch, CollectorItem, JobStatus, JsonValue } from "./types";

export type EnqueueManualTextJobOptions = {
  text: string;
  title?: string | null;
  url?: string | null;
  userLabel?: string | null;
  inputChannel?: string;
  contentType?: string;
  requiresVerification?: boolean;
  provider?: string;
  model?: string;
  priority?: number;
  queueName?: string;
  targetId?: string | null;
};

export type EnqueueManualTextJobResult = {
  job_id: string;
  queue_id: string;
  status: "queued";
  provider: string;
  model: string;
};

export type ClaimedPostgresJob = {
  queue_id: string;
  job_id: string;
  attempts: number;
};

export type PostgresJobForRun = {
  job_id: string;
  provider: string;
  model: string;
  target_id: string | null;
  collector_batch: CollectorBatch;
};

type QueryTarget = Pool | PoolClient;

export function uniquePostgresJobId(now = new Date()): string {
  return `manual_${timestampSlug(now)}_${randomUUID().replace(/-/g, "").slice(0, 10)}`;
}

export async function enqueueManualTextJob(
  options: EnqueueManualTextJobOptions,
  poolOrClient: QueryTarget = getSharedPostgresPool()
): Promise<EnqueueManualTextJobResult> {
  const provider = options.provider ?? process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture";
  const model = options.model ?? process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4";
  const jobId = uniquePostgresJobId();
  const collectedAt = new Date().toISOString();
  const batch = buildManualCollectorBatch({
    text: options.text,
    runId: jobId,
    collectedAt,
    title: options.title,
    url: options.url,
    userLabel: options.userLabel,
    inputChannel: options.inputChannel ?? "web",
    contentType: options.contentType ?? "note",
    requiresVerification: Boolean(options.requiresVerification)
  });

  return withPostgresTransaction(poolOrClient, async (client) => {
    await client.query(
      `
      INSERT INTO signal_radar_jobs (
        job_id, kind, status, target_id, title, url, user_label, input_channel,
        content_type, requires_verification, provider, model, input
      )
      VALUES ($1, 'manual_text', 'queued', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
      `,
      [
        jobId,
        options.targetId ?? null,
        options.title ?? null,
        options.url ?? null,
        options.userLabel ?? null,
        options.inputChannel ?? "web",
        options.contentType ?? "note",
        Boolean(options.requiresVerification),
        provider,
        model,
        jsonb({
          text: options.text,
          title: options.title ?? null,
          url: options.url ?? null,
          user_label: options.userLabel ?? null
        })
      ]
    );

    const insertedBatch = await client.query<{ batch_id: string }>(
      `
      INSERT INTO signal_radar_collector_batches (
        job_id, schema_version, item_schema_version, source, collector_run_id,
        collected_at, target, collector, item_count, warnings, raw_meta
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10::jsonb, $11::jsonb)
      RETURNING batch_id
      `,
      [
        jobId,
        batch.schema_version,
        batch.item_schema_version,
        batch.source,
        batch.collector_run_id,
        batch.collected_at,
        jsonb(batch.target),
        jsonb(batch.collector),
        batch.item_count,
        jsonb(batch.warnings),
        jsonb(batch.raw_meta)
      ]
    );
    const batchId = insertedBatch.rows[0].batch_id;
    for (const item of batch.items) await insertCollectorItem(client, batchId, item);

    const queued = await client.query<{ queue_id: string }>(
      `
      INSERT INTO signal_radar_job_queue (job_id, queue_name, priority)
      VALUES ($1, $2, $3)
      RETURNING queue_id
      `,
      [jobId, options.queueName ?? "analysis", options.priority ?? 0]
    );
    await appendPostgresJobLog(
      jobId,
      {
        action: "job.enqueue",
        message: "manual text job queued",
        stdout: JSON.stringify({ provider, model, queue_name: options.queueName ?? "analysis" })
      },
      client
    );
    return {
      job_id: jobId,
      queue_id: queued.rows[0].queue_id,
      status: "queued",
      provider,
      model
    };
  });
}

export async function claimNextPostgresJob(
  options: { queueName?: string; workerId?: string; lockSeconds?: number } = {},
  poolOrClient: QueryTarget = getSharedPostgresPool()
): Promise<ClaimedPostgresJob | null> {
  return withPostgresTransaction(poolOrClient, async (client) => {
    const claimed = await client.query<ClaimedPostgresJob>(
      `
      WITH candidate AS (
        SELECT queue_id
        FROM signal_radar_job_queue
        WHERE queue_name = $1
          AND status IN ('queued', 'failed')
          AND available_at <= now()
          AND attempts < max_attempts
        ORDER BY priority DESC, enqueued_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
      )
      UPDATE signal_radar_job_queue q
      SET status = 'claimed',
          attempts = attempts + 1,
          locked_by = $2,
          locked_until = now() + ($3::text || ' seconds')::interval
      FROM candidate
      WHERE q.queue_id = candidate.queue_id
      RETURNING q.queue_id::text, q.job_id, q.attempts
      `,
      [
        options.queueName ?? "analysis",
        options.workerId ?? `worker:${process.pid}`,
        options.lockSeconds ?? 300
      ]
    );
    const row = claimed.rows[0];
    if (!row) return null;
    await client.query(
      `
      UPDATE signal_radar_jobs
      SET status = 'running', started_at = COALESCE(started_at, now()), error = NULL
      WHERE job_id = $1
      `,
      [row.job_id]
    );
    return row;
  });
}

export async function loadPostgresJobForRun(
  jobId: string,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<PostgresJobForRun | null> {
  const job = await queryable.query<{
    job_id: string;
    provider: string | null;
    model: string | null;
    target_id: string | null;
  }>(
    `
    SELECT job_id, provider, model, target_id
    FROM signal_radar_jobs
    WHERE job_id = $1
    `,
    [jobId]
  );
  if (!job.rows[0]) return null;

  const batch = await queryable.query<{
    batch_id: string;
    schema_version: "collector-batch/v1";
    item_schema_version: "collector-item/v1";
    source: string;
    collector_run_id: string;
    collected_at: Date | string;
    target: Record<string, JsonValue>;
    collector: Record<string, JsonValue>;
    item_count: number;
    warnings: JsonValue[];
    raw_meta: Record<string, JsonValue>;
  }>(
    `
    SELECT *
    FROM signal_radar_collector_batches
    WHERE job_id = $1
    ORDER BY created_at DESC
    LIMIT 1
    `,
    [jobId]
  );
  const batchRow = batch.rows[0];
  if (!batchRow) throw new Error(`collector batch not found for job: ${jobId}`);

  const items = await queryable.query<CollectorItem & { collected_at: Date | string; published_at: Date | string | null }>(
    `
    SELECT canonical_id, source, item_id, content_type, published_at, collected_at, url, title,
           text, language, author, metrics, media, relations, source_meta
    FROM signal_radar_collector_items
    WHERE batch_id = $1
    ORDER BY created_at ASC
    `,
    [batchRow.batch_id]
  );

  return {
    job_id: job.rows[0].job_id,
    provider: job.rows[0].provider ?? "fixture",
    model: job.rows[0].model ?? "gpt-5.4",
    target_id: job.rows[0].target_id,
    collector_batch: {
      schema_version: batchRow.schema_version,
      item_schema_version: batchRow.item_schema_version,
      source: batchRow.source,
      collector_run_id: batchRow.collector_run_id,
      collected_at: toIso(batchRow.collected_at),
      target: batchRow.target,
      collector: batchRow.collector,
      item_count: batchRow.item_count,
      items: items.rows.map((item) => ({
        ...item,
        schema_version: "collector-item/v1",
        published_at: item.published_at ? toIso(item.published_at) : "",
        collected_at: toIso(item.collected_at)
      })),
      warnings: Array.isArray(batchRow.warnings) ? batchRow.warnings.map(String) : [],
      raw_meta: batchRow.raw_meta
    }
  };
}

export async function insertPostgresAnalysisArtifact(
  payload: {
    jobId: string;
    provider: string;
    model: string;
    runId: string;
    status?: "created" | "running" | "done" | "failed";
    analysisInput: Record<string, JsonValue>;
    memoryContext: Record<string, JsonValue>;
    rawReport: string;
    prompt: string;
    report: string;
    summary?: string;
    runMetrics?: Record<string, JsonValue>;
    generatedAt?: string;
  },
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<string> {
  const inserted = await queryable.query<{ artifact_id: string }>(
    `
    INSERT INTO signal_radar_analysis_artifacts (
      job_id, provider, model, run_id, status, analysis_input, memory_context,
      raw_report, prompt, report, summary, run_metrics, generated_at
    )
    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12::jsonb, $13)
    RETURNING artifact_id::text
    `,
    [
      payload.jobId,
      payload.provider,
      payload.model,
      payload.runId,
      payload.status ?? "created",
      jsonb(payload.analysisInput),
      jsonb(payload.memoryContext),
      payload.rawReport,
      payload.prompt,
      payload.report,
      payload.summary ?? "",
      jsonb(payload.runMetrics ?? {}),
      payload.generatedAt ?? new Date().toISOString()
    ]
  );
  return inserted.rows[0].artifact_id;
}

export async function updatePostgresAnalysisSummary(
  artifactId: string,
  summary: string,
  status: "done" | "failed",
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<void> {
  await queryable.query(
    `
    UPDATE signal_radar_analysis_artifacts
    SET summary = $2, status = $3
    WHERE artifact_id = $1
    `,
    [artifactId, summary, status]
  );
}

export async function appendPostgresJobLog(
  jobId: string,
  payload: { action: string; level?: "debug" | "info" | "warn" | "error"; message?: string; stdout?: string; stderr?: string },
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<void> {
  await queryable.query(
    `
    INSERT INTO signal_radar_job_logs (job_id, action, level, message, stdout, stderr)
    VALUES ($1, $2, $3, $4, $5, $6)
    `,
    [jobId, payload.action, payload.level ?? "info", payload.message ?? "", payload.stdout ?? "", payload.stderr ?? ""]
  );
}

export async function completePostgresJob(
  jobId: string,
  result: Record<string, JsonValue> = {},
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<void> {
  await queryable.query(
    `
    UPDATE signal_radar_jobs
    SET status = 'done', finished_at = now(), result = $2::jsonb, error = NULL
    WHERE job_id = $1
    `,
    [jobId, jsonb(result)]
  );
  await queryable.query(
    `
    UPDATE signal_radar_job_queue
    SET status = 'done', locked_until = NULL
    WHERE job_id = $1 AND status = 'claimed'
    `,
    [jobId]
  );
}

export async function failPostgresJob(
  jobId: string,
  error: string,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<void> {
  await queryable.query(
    `
    WITH updated_queue AS (
      UPDATE signal_radar_job_queue
      SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'failed' END,
          available_at = CASE WHEN attempts >= max_attempts THEN available_at ELSE now() + interval '60 seconds' END,
          locked_until = NULL,
          last_error = $2
      WHERE job_id = $1 AND status = 'claimed'
      RETURNING status
    )
    UPDATE signal_radar_jobs
    SET status = CASE WHEN EXISTS (SELECT 1 FROM updated_queue WHERE status = 'dead') THEN 'failed' ELSE 'queued' END,
        failed_at = CASE WHEN EXISTS (SELECT 1 FROM updated_queue WHERE status = 'dead') THEN now() ELSE failed_at END,
        error = $2
    WHERE job_id = $1
    `,
    [jobId, error]
  );
  await appendPostgresJobLog(jobId, { action: "job.failed", level: "error", message: error }, queryable);
}

export async function listRecentPostgresJobs(
  limit = 12,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<JobStatus[]> {
  const rows = await queryable.query<{
    job_id: string;
    status: JobStatus["status"] | "queued" | "canceled";
    created_at: Date | string | null;
    started_at: Date | string | null;
    finished_at: Date | string | null;
    failed_at: Date | string | null;
    updated_at: Date | string;
    provider: string | null;
    model: string | null;
    error: string | null;
  }>(
    `
    SELECT job_id, status, created_at, started_at, finished_at, failed_at, updated_at, provider, model, error
    FROM signal_radar_jobs
    ORDER BY updated_at DESC
    LIMIT $1
    `,
    [limit]
  );
  return rows.rows.map((row) => ({
    job_id: row.job_id,
    status: normalizeJobStatus(row.status),
    created_at: row.created_at ? toIso(row.created_at) : undefined,
    started_at: row.started_at ? toIso(row.started_at) : undefined,
    finished_at: row.finished_at ? toIso(row.finished_at) : undefined,
    failed_at: row.failed_at ? toIso(row.failed_at) : undefined,
    updated_at: toIso(row.updated_at),
    provider: row.provider ?? undefined,
    model: row.model ?? undefined,
    error: row.error ?? undefined
  }));
}

export async function getPostgresJobPayload(
  jobId: string,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<Record<string, JsonValue> | null> {
  const job = await queryable.query<Record<string, JsonValue> & { updated_at: Date | string }>(
    `
    SELECT *
    FROM signal_radar_jobs
    WHERE job_id = $1
    `,
    [jobId]
  );
  const jobRow = job.rows[0];
  if (!jobRow) return null;

  const artifact = await queryable.query<Record<string, JsonValue>>(
    `
    SELECT artifact_id::text, provider, model, run_id, status, summary, analysis_input,
           memory_context, raw_report, prompt, report, run_metrics, generated_at
    FROM signal_radar_analysis_artifacts
    WHERE job_id = $1
    ORDER BY created_at DESC
    LIMIT 1
    `,
    [jobId]
  );
  const memoryUpdate = await queryable.query<Record<string, JsonValue>>(
    `
    SELECT update_id, status, parsed, information_unit_count, event_cluster_count,
           entity_updates_applied, event_updates_applied, macro_updates_applied,
           source_updates_applied, memory_versions_created, applied_at
    FROM signal_radar_memory_updates
    WHERE job_id = $1
    ORDER BY created_at DESC
    LIMIT 1
    `,
    [jobId]
  );
  const versions = await queryable.query<Record<string, JsonValue>>(
    `
    SELECT v.version_id::text, r.collection, r.record_key, v.version_number,
           v.operation, v.diff, v.created_at
    FROM signal_radar_memory_versions v
    JOIN signal_radar_memory_records r ON r.memory_id = v.memory_id
    WHERE v.job_id = $1
    ORDER BY v.created_at DESC
    LIMIT 40
    `,
    [jobId]
  );
  const logs = await queryable.query<{ action: string; level: string; message: string; stdout: string; stderr: string; created_at: Date | string }>(
    `
    SELECT action, level, message, stdout, stderr, created_at
    FROM signal_radar_job_logs
    WHERE job_id = $1
    ORDER BY created_at DESC
    LIMIT 80
    `,
    [jobId]
  );

  return {
    job_id: jobId,
    status: normalizeStatusPayload(jobRow),
    summary: String(artifact.rows[0]?.summary ?? ""),
    memory_update: (memoryUpdate.rows[0] ?? {}) as JsonValue,
    memory_audit: {
      memory_versions: versions.rows
    } as JsonValue,
    log_tail: logs.rows
      .reverse()
      .map((row) => {
        const body = [row.message, row.stdout, row.stderr].filter(Boolean).join("\n");
        return `[${toIso(row.created_at)}] ${row.level} ${row.action}${body ? `\n${body}` : ""}`;
      })
      .join("\n")
  };
}

export async function loadPostgresMemoryContext(
  limit = 40,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<Record<string, JsonValue>> {
  const rows = await queryable.query<{ collection: string; record_key: string; payload: JsonValue }>(
    `
    SELECT collection, record_key, payload
    FROM signal_radar_memory_records
    ORDER BY updated_at DESC
    LIMIT $1
    `,
    [limit]
  );
  const grouped: Record<string, JsonValue[]> = {};
  for (const row of rows.rows) {
    const key = `recent_${row.collection}`;
    grouped[key] = grouped[key] ?? [];
    grouped[key].push({ record_key: row.record_key, payload: row.payload });
  }
  return grouped as Record<string, JsonValue>;
}

async function insertCollectorItem(client: PoolClient, batchId: string, item: CollectorItem): Promise<void> {
  await client.query(
    `
    INSERT INTO signal_radar_collector_items (
      canonical_id, batch_id, source, item_id, content_type, published_at, collected_at,
      url, title, text, language, author, metrics, media, relations, source_meta
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb)
    ON CONFLICT (canonical_id) DO UPDATE SET batch_id = EXCLUDED.batch_id
    `,
    [
      item.canonical_id,
      batchId,
      item.source,
      item.item_id,
      item.content_type,
      item.published_at || null,
      item.collected_at,
      item.url,
      item.title,
      item.text,
      item.language,
      jsonb(item.author),
      jsonb(item.metrics),
      jsonb(item.media),
      jsonb(item.relations),
      jsonb(item.source_meta)
    ]
  );
}

function normalizeStatusPayload(row: Record<string, JsonValue> & { updated_at?: Date | string }): JsonValue {
  return {
    job_id: row.job_id,
    status: normalizeJobStatus(String(row.status)),
    created_at: row.created_at ? toIso(row.created_at as Date | string) : undefined,
    started_at: row.started_at ? toIso(row.started_at as Date | string) : undefined,
    finished_at: row.finished_at ? toIso(row.finished_at as Date | string) : undefined,
    failed_at: row.failed_at ? toIso(row.failed_at as Date | string) : undefined,
    updated_at: row.updated_at ? toIso(row.updated_at) : new Date().toISOString(),
    provider: row.provider ?? undefined,
    model: row.model ?? undefined,
    error: row.error ?? undefined
  } as JsonValue;
}

function normalizeJobStatus(status: string): JobStatus["status"] {
  if (status === "done" || status === "failed" || status === "running") return status;
  return "created";
}

function toIso(value: Date | string | JsonValue): string {
  return value instanceof Date ? value.toISOString() : String(value);
}
