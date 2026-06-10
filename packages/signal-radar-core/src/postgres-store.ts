import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import {
  classifyCollectorItem,
  evidenceContentHash,
  qualityGateFromEvidence,
  sourceProfileFromCollectorItem,
  textExcerpt,
  type QualityGateDecision
} from "./evidence";
import { buildManualCollectorBatch, timestampSlug } from "./manual-ingest";
import { getSharedPostgresPool, jsonb, withPostgresTransaction } from "./postgres";
import { cleanText } from "./schemas";
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
  targetCode?: string | null;
  targetDisplayName?: string | null;
  targetExchange?: string | null;
  targetCountry?: string | null;
};

export type EnqueueManualTextJobResult = {
  job_id: string;
  queue_id: string;
  status: "queued";
  provider: string;
  model: string;
  target_id: string | null;
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

export type PostgresQueueStats = {
  status: string;
  count: number;
};

export type PostgresMemoryRecordListItem = {
  memory_id: string;
  collection: string;
  record_key: string;
  title: string | null;
  current_version: number;
  updated_at: string;
  last_update_id: string | null;
  preview: string;
};

export type PostgresMemoryVersionListItem = {
  version_id: string;
  version_number: number;
  update_id: string;
  job_id: string | null;
  operation: string;
  before_payload: JsonValue | null;
  after_payload: JsonValue | null;
  diff: JsonValue;
  created_at: string;
};

export type PostgresMemoryRecordPayload = {
  memory_id: string;
  collection: string;
  record_key: string;
  title: string | null;
  payload: JsonValue;
  current_version: number;
  updated_at: string;
  last_update_id: string | null;
  versions: PostgresMemoryVersionListItem[];
};

export type PostgresTargetReadProjection = {
  code: string;
  target: {
    target_id: string;
    namespace: string;
    symbol: string;
    exchange: string | null;
    display_name: string;
    asset_type: string;
    country: string | null;
    profile: JsonValue;
    updated_at: string;
  } | null;
  memory: PostgresMemoryRecordListItem[];
  latest_changes: JsonValue[];
  evidence: JsonValue[];
  quality_gates: JsonValue[];
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
    targetCode: options.targetCode,
    inputChannel: options.inputChannel ?? "web",
    contentType: options.contentType ?? "note",
    requiresVerification: Boolean(options.requiresVerification)
  });

  return withPostgresTransaction(poolOrClient, async (client) => {
    const targetId = options.targetId ?? (options.targetCode
      ? await upsertPostgresTargetByCode(
          {
            code: options.targetCode,
            displayName: options.targetDisplayName,
            exchange: options.targetExchange,
            country: options.targetCountry
          },
          client
        )
      : null);
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
        targetId,
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
          user_label: options.userLabel ?? null,
          target_code: options.targetCode ?? null
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
    for (const item of batch.items) await insertCollectorItem(client, batchId, item, { jobId, targetId });

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
      model,
      target_id: targetId
    };
  });
}

export async function upsertPostgresTargetByCode(
  options: {
    code: string;
    namespace?: string;
    displayName?: string | null;
    exchange?: string | null;
    assetType?: string | null;
    country?: string | null;
    profile?: Record<string, JsonValue>;
  },
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<string> {
  const symbol = normalizeTargetCode(options.code);
  if (!symbol) throw new Error("target code is required");
  const namespace = cleanText(options.namespace) || "public_market";
  const exchange = cleanOptional(options.exchange);
  const displayName = cleanOptional(options.displayName) ?? symbol;
  const assetType = cleanOptional(options.assetType) ?? "equity";

  const existing = await queryable.query<{ target_id: string }>(
    `
    SELECT target_id::text
    FROM signal_radar_targets
    WHERE namespace = $1
      AND symbol = $2
      AND COALESCE(exchange, '') = COALESCE($3, '')
    LIMIT 1
    `,
    [namespace, symbol, exchange]
  );
  if (existing.rows[0]) {
    await queryable.query(
      `
      UPDATE signal_radar_targets
      SET display_name = $2,
          asset_type = $3,
          country = COALESCE($4, country),
          profile = profile || $5::jsonb
      WHERE target_id = $1
      `,
      [
        existing.rows[0].target_id,
        displayName,
        assetType,
        cleanOptional(options.country),
        jsonb(options.profile ?? {})
      ]
    );
    return existing.rows[0].target_id;
  }

  const inserted = await queryable.query<{ target_id: string }>(
    `
    INSERT INTO signal_radar_targets (
      namespace, symbol, exchange, display_name, asset_type, country, profile
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
    RETURNING target_id::text
    `,
    [
      namespace,
      symbol,
      exchange,
      displayName,
      assetType,
      cleanOptional(options.country),
      jsonb(options.profile ?? {})
    ]
  );
  return inserted.rows[0].target_id;
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
  filters: { status?: string | null } = {},
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
    WHERE ($2::text IS NULL OR status = $2)
    ORDER BY updated_at DESC
    LIMIT $1
    `,
    [limit, filters.status ?? null]
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

export async function getPostgresQueueStats(
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<PostgresQueueStats[]> {
  const rows = await queryable.query<{ status: string; count: string }>(
    `
    SELECT status, count(*)::text AS count
    FROM signal_radar_job_queue
    GROUP BY status
    ORDER BY status
    `
  );
  return rows.rows.map((row) => ({ status: row.status, count: Number(row.count) }));
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
  const evidence = await queryable.query<Record<string, JsonValue> & { created_at: Date | string; collected_at: Date | string; published_at: Date | string | null }>(
    `
    SELECT evidence_id, source_id, usefulness_status, evidence_kind, source_quality,
           confidence, filter_reasons, url, title, published_at, collected_at,
           text_excerpt, duplicate_of, created_at
    FROM signal_radar_evidence_items
    WHERE job_id = $1
    ORDER BY created_at DESC
    LIMIT 80
    `,
    [jobId]
  );
  const gates = await queryable.query<Record<string, JsonValue> & { created_at: Date | string }>(
    `
    SELECT gate_id::text, gate_type, subject, status, evidence_kind, evidence_strength,
           verification_status, source_quality, severity, reason, evidence_id, update_id, created_at
    FROM signal_radar_quality_gates
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
      memory_versions: versions.rows,
      evidence_items: evidence.rows.map(normalizeDateRow),
      quality_gates: gates.rows.map(normalizeDateRow)
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

export async function getPostgresTargetReadProjection(
  code: string,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<PostgresTargetReadProjection> {
  const normalizedCode = normalizeTargetCode(code);
  if (!normalizedCode) throw new Error("target code is required");

  const target = await queryable.query<{
    target_id: string;
    namespace: string;
    symbol: string;
    exchange: string | null;
    display_name: string;
    asset_type: string;
    country: string | null;
    profile: JsonValue;
    updated_at: Date | string;
  }>(
    `
    SELECT target_id::text, namespace, symbol, exchange, display_name,
           asset_type, country, profile, updated_at
    FROM signal_radar_targets
    WHERE lower(symbol) = lower($1) OR target_id::text = $1
    ORDER BY updated_at DESC
    LIMIT 1
    `,
    [normalizedCode]
  );
  const targetRow = target.rows[0];
  if (!targetRow) {
    return {
      code: normalizedCode,
      target: null,
      memory: [],
      latest_changes: [],
      evidence: [],
      quality_gates: []
    };
  }

  const memory = await queryable.query<{
    memory_id: string;
    collection: string;
    record_key: string;
    title: string | null;
    payload: JsonValue;
    current_version: number;
    updated_at: Date | string;
    last_update_id: string | null;
  }>(
    `
    SELECT memory_id::text, collection, record_key, title, payload,
           current_version, updated_at, last_update_id
    FROM signal_radar_memory_records
    WHERE target_id = $1
    ORDER BY updated_at DESC
    LIMIT 80
    `,
    [targetRow.target_id]
  );

  const latestChanges = await queryable.query<Record<string, JsonValue> & { created_at: Date | string }>(
    `
    SELECT v.version_id::text, r.collection, r.record_key, r.title,
           v.version_number, v.operation, v.diff, v.update_id, v.created_at
    FROM signal_radar_memory_versions v
    JOIN signal_radar_memory_records r ON r.memory_id = v.memory_id
    WHERE r.target_id = $1
    ORDER BY v.created_at DESC
    LIMIT 40
    `,
    [targetRow.target_id]
  );

  const evidence = await queryable.query<Record<string, JsonValue> & { created_at: Date | string; collected_at: Date | string; published_at: Date | string | null }>(
    `
    SELECT evidence_id, source_id, usefulness_status, evidence_kind, source_quality,
           confidence, filter_reasons, url, title, published_at, collected_at,
           text_excerpt, duplicate_of, created_at
    FROM signal_radar_evidence_items
    WHERE target_id = $1
    ORDER BY created_at DESC
    LIMIT 80
    `,
    [targetRow.target_id]
  );

  const gates = await queryable.query<Record<string, JsonValue> & { created_at: Date | string }>(
    `
    SELECT gate_id::text, gate_type, subject, status, evidence_kind, evidence_strength,
           verification_status, source_quality, severity, reason, evidence_id, update_id, created_at
    FROM signal_radar_quality_gates
    WHERE target_id = $1
    ORDER BY created_at DESC
    LIMIT 80
    `,
    [targetRow.target_id]
  );

  return {
    code: targetRow.symbol,
    target: {
      ...targetRow,
      updated_at: toIso(targetRow.updated_at)
    },
    memory: memory.rows.map((row) => ({
      memory_id: row.memory_id,
      collection: row.collection,
      record_key: row.record_key,
      title: row.title,
      current_version: row.current_version,
      updated_at: toIso(row.updated_at),
      last_update_id: row.last_update_id,
      preview: memoryPreview(row.payload)
    })),
    latest_changes: latestChanges.rows.map(normalizeDateRow),
    evidence: evidence.rows.map(normalizeDateRow),
    quality_gates: gates.rows.map(normalizeDateRow)
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

export async function listPostgresMemoryRecords(
  options: { collection?: string | null; limit?: number } = {},
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<PostgresMemoryRecordListItem[]> {
  const rows = await queryable.query<{
    memory_id: string;
    collection: string;
    record_key: string;
    title: string | null;
    payload: JsonValue;
    current_version: number;
    updated_at: Date | string;
    last_update_id: string | null;
  }>(
    `
    SELECT memory_id::text, collection, record_key, title, payload, current_version, updated_at, last_update_id
    FROM signal_radar_memory_records
    WHERE ($1::text IS NULL OR collection = $1)
    ORDER BY updated_at DESC
    LIMIT $2
    `,
    [options.collection ?? null, options.limit ?? 80]
  );
  return rows.rows.map((row) => ({
    memory_id: row.memory_id,
    collection: row.collection,
    record_key: row.record_key,
    title: row.title,
    current_version: row.current_version,
    updated_at: toIso(row.updated_at),
    last_update_id: row.last_update_id,
    preview: memoryPreview(row.payload)
  }));
}

export async function getPostgresMemoryRecord(
  memoryId: string,
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<PostgresMemoryRecordPayload | null> {
  const record = await queryable.query<{
    memory_id: string;
    collection: string;
    record_key: string;
    title: string | null;
    payload: JsonValue;
    current_version: number;
    updated_at: Date | string;
    last_update_id: string | null;
  }>(
    `
    SELECT memory_id::text, collection, record_key, title, payload, current_version, updated_at, last_update_id
    FROM signal_radar_memory_records
    WHERE memory_id = $1
    `,
    [memoryId]
  );
  const row = record.rows[0];
  if (!row) return null;
  const versions = await queryable.query<{
    version_id: string;
    version_number: number;
    update_id: string;
    job_id: string | null;
    operation: string;
    before_payload: JsonValue | null;
    after_payload: JsonValue | null;
    diff: JsonValue;
    created_at: Date | string;
  }>(
    `
    SELECT version_id::text, version_number, update_id, job_id, operation,
           before_payload, after_payload, diff, created_at
    FROM signal_radar_memory_versions
    WHERE memory_id = $1
    ORDER BY version_number DESC
    LIMIT 80
    `,
    [memoryId]
  );
  return {
    memory_id: row.memory_id,
    collection: row.collection,
    record_key: row.record_key,
    title: row.title,
    payload: row.payload,
    current_version: row.current_version,
    updated_at: toIso(row.updated_at),
    last_update_id: row.last_update_id,
    versions: versions.rows.map((version) => ({
      ...version,
      created_at: toIso(version.created_at)
    }))
  };
}

async function insertCollectorItem(
  client: PoolClient,
  batchId: string,
  item: CollectorItem,
  context: { jobId: string; targetId: string | null }
): Promise<void> {
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
  await insertEvidenceSnapshot(client, item, context);
}

async function insertEvidenceSnapshot(
  client: PoolClient,
  item: CollectorItem,
  context: { jobId: string; targetId: string | null }
): Promise<void> {
  const contentHash = evidenceContentHash(item);
  const duplicate = await client.query<{ evidence_id: string }>(
    `
    SELECT evidence_id
    FROM signal_radar_evidence_items
    WHERE content_hash = $1 AND evidence_id <> $2
    ORDER BY created_at ASC
    LIMIT 1
    `,
    [contentHash, item.canonical_id]
  );
  const duplicateOf = duplicate.rows[0]?.evidence_id ?? null;
  const classification = classifyCollectorItem(item, { duplicateOf });
  const sourceProfile = sourceProfileFromCollectorItem(item, classification);

  await client.query(
    `
    INSERT INTO signal_radar_sources (
      source_id, source_type, display_name, canonical_url, credibility_tier,
      quality_score, profile
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
    ON CONFLICT (source_id) DO UPDATE SET
      source_type = EXCLUDED.source_type,
      display_name = EXCLUDED.display_name,
      canonical_url = COALESCE(EXCLUDED.canonical_url, signal_radar_sources.canonical_url),
      credibility_tier = EXCLUDED.credibility_tier,
      quality_score = EXCLUDED.quality_score,
      profile = signal_radar_sources.profile || EXCLUDED.profile
    `,
    [
      classification.source_id,
      cleanText(item.author?.entity_type) || cleanText(item.source) || "unknown",
      cleanText(item.author?.display_name) || cleanText(item.source) || classification.source_id,
      cleanOptional(item.author?.url) ?? cleanOptional(item.url),
      classification.source_quality,
      classification.confidence,
      jsonb(sourceProfile)
    ]
  );

  await client.query(
    `
    INSERT INTO signal_radar_evidence_items (
      evidence_id, job_id, target_id, collector_item_id, source_id, content_hash,
      duplicate_of, usefulness_status, evidence_kind, source_quality, confidence,
      filter_reasons, url, title, published_at, collected_at, text_excerpt, payload
    )
    VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
      $12, $13, $14, $15, $16, $17, $18::jsonb
    )
    ON CONFLICT (evidence_id) DO UPDATE SET
      job_id = EXCLUDED.job_id,
      target_id = COALESCE(EXCLUDED.target_id, signal_radar_evidence_items.target_id),
      source_id = EXCLUDED.source_id,
      duplicate_of = EXCLUDED.duplicate_of,
      usefulness_status = EXCLUDED.usefulness_status,
      evidence_kind = EXCLUDED.evidence_kind,
      source_quality = EXCLUDED.source_quality,
      confidence = EXCLUDED.confidence,
      filter_reasons = EXCLUDED.filter_reasons,
      url = EXCLUDED.url,
      title = EXCLUDED.title,
      published_at = EXCLUDED.published_at,
      collected_at = EXCLUDED.collected_at,
      text_excerpt = EXCLUDED.text_excerpt,
      payload = EXCLUDED.payload
    `,
    [
      item.canonical_id,
      context.jobId,
      context.targetId,
      item.canonical_id,
      classification.source_id,
      contentHash,
      duplicateOf,
      classification.usefulness_status,
      classification.evidence_kind,
      classification.source_quality,
      classification.confidence,
      classification.filter_reasons,
      item.url,
      item.title,
      item.published_at || null,
      item.collected_at,
      textExcerpt(item.text),
      jsonb({
        collector_item: item as unknown as JsonValue,
        classification: classification as unknown as JsonValue
      })
    ]
  );

  await insertQualityGate(client, {
    jobId: context.jobId,
    targetId: context.targetId,
    evidenceId: item.canonical_id,
    gateType: "evidence.filter",
    subject: cleanText(item.title) || textExcerpt(item.text, 160),
    decision: qualityGateFromEvidence(classification),
    payload: {
      content_hash: contentHash,
      duplicate_of: duplicateOf,
      filter_reasons: classification.filter_reasons
    }
  });
}

export async function insertPostgresQualityGate(
  payload: {
    jobId?: string | null;
    targetId?: string | null;
    updateId?: string | null;
    memoryId?: string | null;
    evidenceId?: string | null;
    gateType: string;
    subject?: string | null;
    decision: QualityGateDecision;
    payload?: Record<string, JsonValue>;
  },
  queryable: QueryTarget = getSharedPostgresPool()
): Promise<string> {
  return insertQualityGate(queryable, payload);
}

async function insertQualityGate(
  queryable: QueryTarget,
  payload: {
    jobId?: string | null;
    targetId?: string | null;
    updateId?: string | null;
    memoryId?: string | null;
    evidenceId?: string | null;
    gateType: string;
    subject?: string | null;
    decision: QualityGateDecision;
    payload?: Record<string, JsonValue>;
  }
): Promise<string> {
  const inserted = await queryable.query<{ gate_id: string }>(
    `
    INSERT INTO signal_radar_quality_gates (
      job_id, target_id, update_id, memory_id, evidence_id, gate_type, subject,
      status, evidence_kind, evidence_strength, verification_status, source_quality,
      severity, reason, payload
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb)
    RETURNING gate_id::text
    `,
    [
      payload.jobId ?? null,
      payload.targetId ?? null,
      payload.updateId ?? null,
      payload.memoryId ?? null,
      payload.evidenceId ?? null,
      payload.gateType,
      cleanText(payload.subject),
      payload.decision.status,
      payload.decision.evidence_kind,
      payload.decision.evidence_strength,
      payload.decision.verification_status,
      payload.decision.source_quality,
      payload.decision.severity,
      payload.decision.reason,
      jsonb(payload.payload ?? {})
    ]
  );
  return inserted.rows[0].gate_id;
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
  if (status === "queued" || status === "done" || status === "failed" || status === "running" || status === "canceled") {
    return status;
  }
  return "created";
}

function toIso(value: Date | string | JsonValue): string {
  return value instanceof Date ? value.toISOString() : String(value);
}

function normalizeDateRow<T extends Record<string, JsonValue> & { created_at?: Date | string; collected_at?: Date | string; published_at?: Date | string | null }>(
  row: T
): JsonValue {
  return {
    ...row,
    created_at: row.created_at ? toIso(row.created_at) : undefined,
    collected_at: row.collected_at ? toIso(row.collected_at) : undefined,
    published_at: row.published_at ? toIso(row.published_at) : null
  } as JsonValue;
}

function normalizeTargetCode(value: unknown): string {
  return cleanText(value).toUpperCase();
}

function cleanOptional(value: unknown): string | null {
  const text = cleanText(value);
  return text || null;
}

function memoryPreview(payload: JsonValue): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return String(payload ?? "");
  const row = payload as Record<string, JsonValue>;
  return String(
    row.claim ??
      row.summary ??
      row.note ??
      row.title ??
      row.subject ??
      row.primary_theme ??
      row.name ??
      JSON.stringify(payload)
  ).slice(0, 180);
}
