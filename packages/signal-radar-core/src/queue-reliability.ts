import { sql } from "drizzle-orm";
import type { Pool, PoolClient } from "pg";
import { createSignalRadarDrizzle } from "./drizzle";

export type QueueRecoveryResult = {
  recovered_count: number;
  failed_count: number;
  dead_count: number;
};

export type PostgresQueueEntry = {
  queue_id: string;
  job_id: string;
  queue_name: string;
  queue_status: string;
  job_status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  available_at: string;
  locked_by: string | null;
  locked_until: string | null;
  last_error: string | null;
  enqueued_at: string;
  updated_at: string;
  provider: string | null;
  model: string | null;
  target_code: string | null;
};

export type QueueFailureGroup = {
  status: string;
  last_error: string;
  count: number;
  latest_at: string;
};

export type QueueReliabilityStats = {
  by_status: { status: string; count: number }[];
  stale_claimed: number;
  failure_groups: QueueFailureGroup[];
};

type QueryTarget = Pool | PoolClient;

export function queueBackoffSeconds(attempts: number): number {
  const normalized = Math.max(1, Math.floor(attempts));
  return Math.min(3600, Math.max(60, normalized * normalized * 60));
}

export async function recoverExpiredPostgresJobLeases(
  options: { queueName?: string | null } = {},
  queryable?: QueryTarget
): Promise<QueueRecoveryResult> {
  const db = createSignalRadarDrizzle(queryable);
  const result = await db.execute<{
    recovered_count: number | string;
    failed_count: number | string;
    dead_count: number | string;
  }>(sql`
    WITH recovered AS (
      UPDATE signal_radar_job_queue
      SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'failed' END,
          locked_by = NULL,
          locked_until = NULL,
          last_error = COALESCE(last_error, 'worker lease expired'),
          available_at = CASE
            WHEN attempts >= max_attempts THEN available_at
            ELSE now() + (LEAST(3600, GREATEST(60, attempts * attempts * 60))::text || ' seconds')::interval
          END,
          updated_at = now()
      WHERE queue_name = ${options.queueName ?? "analysis"}
        AND status = 'claimed'
        AND locked_until IS NOT NULL
        AND locked_until < now()
      RETURNING job_id, status
    ),
    updated_jobs AS (
      UPDATE signal_radar_jobs j
      SET status = CASE WHEN r.status = 'dead' THEN 'failed' ELSE 'queued' END,
          failed_at = CASE WHEN r.status = 'dead' THEN COALESCE(j.failed_at, now()) ELSE j.failed_at END,
          error = CASE WHEN r.status = 'dead' THEN COALESCE(j.error, 'worker lease expired') ELSE j.error END,
          updated_at = now()
      FROM recovered r
      WHERE j.job_id = r.job_id
      RETURNING j.job_id
    )
    SELECT count(*)::int AS recovered_count,
           count(*) FILTER (WHERE status = 'failed')::int AS failed_count,
           count(*) FILTER (WHERE status = 'dead')::int AS dead_count
    FROM recovered
  `);
  const row = result.rows[0];
  return {
    recovered_count: Number(row?.recovered_count ?? 0),
    failed_count: Number(row?.failed_count ?? 0),
    dead_count: Number(row?.dead_count ?? 0)
  };
}

export async function listPostgresQueueEntries(
  options: { status?: string | null; queueName?: string | null; limit?: number } = {},
  queryable?: QueryTarget
): Promise<PostgresQueueEntry[]> {
  const db = createSignalRadarDrizzle(queryable);
  const result = await db.execute<Record<string, unknown>>(sql`
    SELECT q.queue_id::text,
           q.job_id,
           q.queue_name,
           q.status AS queue_status,
           j.status AS job_status,
           q.priority,
           q.attempts,
           q.max_attempts,
           q.available_at,
           q.locked_by,
           q.locked_until,
           q.last_error,
           q.enqueued_at,
           q.updated_at,
           j.provider,
           j.model,
           t.symbol AS target_code
    FROM signal_radar_job_queue q
    JOIN signal_radar_jobs j ON j.job_id = q.job_id
    LEFT JOIN signal_radar_targets t ON t.target_id = j.target_id
    WHERE (${options.status ?? null}::text IS NULL OR q.status = ${options.status ?? null})
      AND q.queue_name = ${options.queueName ?? "analysis"}
    ORDER BY
      CASE q.status WHEN 'dead' THEN 0 WHEN 'failed' THEN 1 WHEN 'claimed' THEN 2 WHEN 'queued' THEN 3 ELSE 4 END,
      q.updated_at DESC
    LIMIT ${boundedLimit(options.limit ?? 160)}
  `);
  return result.rows.map((row) => ({
    queue_id: String(row.queue_id),
    job_id: String(row.job_id),
    queue_name: String(row.queue_name),
    queue_status: String(row.queue_status),
    job_status: String(row.job_status),
    priority: Number(row.priority),
    attempts: Number(row.attempts),
    max_attempts: Number(row.max_attempts),
    available_at: toIso(row.available_at),
    locked_by: row.locked_by ? String(row.locked_by) : null,
    locked_until: row.locked_until ? toIso(row.locked_until) : null,
    last_error: row.last_error ? String(row.last_error) : null,
    enqueued_at: toIso(row.enqueued_at),
    updated_at: toIso(row.updated_at),
    provider: row.provider ? String(row.provider) : null,
    model: row.model ? String(row.model) : null,
    target_code: row.target_code ? String(row.target_code) : null
  }));
}

export async function getPostgresQueueReliabilityStats(
  options: { queueName?: string | null } = {},
  queryable?: QueryTarget
): Promise<QueueReliabilityStats> {
  const db = createSignalRadarDrizzle(queryable);
  const [byStatus, stale, failures] = await Promise.all([
    db.execute<{ status: string; count: number | string }>(sql`
      SELECT status, count(*)::int AS count
      FROM signal_radar_job_queue
      WHERE queue_name = ${options.queueName ?? "analysis"}
      GROUP BY status
      ORDER BY status
    `),
    db.execute<{ count: number | string }>(sql`
      SELECT count(*)::int AS count
      FROM signal_radar_job_queue
      WHERE queue_name = ${options.queueName ?? "analysis"}
        AND status = 'claimed'
        AND locked_until IS NOT NULL
        AND locked_until < now()
    `),
    db.execute<{ status: string; last_error: string; count: number | string; latest_at: Date | string }>(sql`
      SELECT status,
             COALESCE(NULLIF(last_error, ''), 'unknown') AS last_error,
             count(*)::int AS count,
             max(updated_at) AS latest_at
      FROM signal_radar_job_queue
      WHERE queue_name = ${options.queueName ?? "analysis"}
        AND status IN ('failed', 'dead')
      GROUP BY status, COALESCE(NULLIF(last_error, ''), 'unknown')
      ORDER BY count(*) DESC, max(updated_at) DESC
      LIMIT 12
    `)
  ]);
  return {
    by_status: byStatus.rows.map((row) => ({ status: row.status, count: Number(row.count) })),
    stale_claimed: Number(stale.rows[0]?.count ?? 0),
    failure_groups: failures.rows.map((row) => ({
      status: row.status,
      last_error: row.last_error,
      count: Number(row.count),
      latest_at: toIso(row.latest_at)
    }))
  };
}

function boundedLimit(value: number): number {
  return Math.min(Math.max(Math.floor(value), 1), 500);
}

function toIso(value: unknown): string {
  return value instanceof Date ? value.toISOString() : String(value ?? "");
}
