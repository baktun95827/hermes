import { createHash } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import { qualityGateFromMemoryRow } from "./evidence";
import { buildMemoryUpdateId, hasParseableMemoryUpdate, parseMemoryUpdate } from "./memory-update";
import { buildMemoryRecordCandidates, buildMemoryVersionChange } from "./memory-version";
import { cleanText } from "./schemas";
import { getSharedPostgresPool, jsonb, withPostgresTransaction } from "./postgres";
import { insertPostgresQualityGate } from "./postgres-store";
import type { JsonValue, MemoryApplicationResult, MemoryUpdate } from "./types";

export type ApplyMemoryUpdatePostgresOptions = {
  jobId?: string | null;
  artifactId?: string | null;
  providerRunId?: string | null;
  targetId?: string | null;
  runId?: string | null;
  summaryText: string;
  summaryPath?: string | null;
};

export async function applyMemoryUpdateToPostgres(
  options: ApplyMemoryUpdatePostgresOptions,
  poolOrClient: Pool | PoolClient = getSharedPostgresPool()
): Promise<MemoryApplicationResult> {
  const parsed = parseMemoryUpdate(options.summaryText);
  if (!hasParseableMemoryUpdate(parsed)) throw new Error("no parseable MEMORY_UPDATE found in summary");

  const updateId = buildMemoryUpdateId({
    summaryText: options.summaryText,
    summaryPath: options.summaryPath ?? options.jobId ?? "postgres-summary",
    runId: options.runId ?? options.jobId ?? "postgres-run"
  });
  const appliedAt = new Date().toISOString();
  const summaryHash = createHash("sha256").update(options.summaryText).digest("hex");

  return withPostgresTransaction(poolOrClient, async (client) => {
    await client.query(
      `
      INSERT INTO signal_radar_memory_updates (
        update_id, job_id, artifact_id, provider_run_id, target_id, run_id, status,
        summary_hash, parsed, information_unit_count, event_cluster_count,
        entity_updates_applied, event_updates_applied, macro_updates_applied,
        source_updates_applied, applied_at
      )
      VALUES (
        $1, $2, $3, $4, $5, $6, 'applied',
        $7, $8::jsonb, $9, $10, $11, $12, $13, $14, $15
      )
      ON CONFLICT (update_id) DO UPDATE SET
        status = EXCLUDED.status,
        parsed = EXCLUDED.parsed,
        applied_at = EXCLUDED.applied_at,
        error = NULL
      `,
      [
        updateId,
        options.jobId ?? null,
        options.artifactId ?? null,
        options.providerRunId ?? null,
        options.targetId ?? null,
        options.runId ?? null,
        summaryHash,
        jsonb(parsed),
        parsed.information_units.length,
        parsed.event_clusters.length,
        parsed.entity_updates.length,
        parsed.event_updates.length,
        parsed.macro_updates.length,
        parsed.source_assessments.length,
        appliedAt
      ]
    );

    const versionCount = await applyMemoryRecords(client, {
      parsed,
      updateId,
      jobId: options.jobId ?? null,
      artifactId: options.artifactId ?? null,
      providerRunId: options.providerRunId ?? null,
      targetId: options.targetId ?? null
    });
    await insertQueryableUpdateRows(client, parsed, {
      updateId,
      jobId: options.jobId ?? null,
      targetId: options.targetId ?? null
    });
    const qualityGateCount = await insertMemoryQualityGates(client, parsed, {
      updateId,
      jobId: options.jobId ?? null,
      targetId: options.targetId ?? null
    });
    await client.query(
      `
      UPDATE signal_radar_memory_updates
      SET memory_versions_created = $2
      WHERE update_id = $1
      `,
      [updateId, versionCount]
    );
    await client.query(
      `
      INSERT INTO signal_radar_memory_audit_events (update_id, job_id, event_type, severity, payload)
      VALUES ($1, $2, 'memory_update.applied', 'info', $3::jsonb)
      `,
      [
        updateId,
        options.jobId ?? null,
        jsonb({
          memory_versions_created: versionCount,
          information_unit_count: parsed.information_units.length,
          event_cluster_count: parsed.event_clusters.length,
          quality_gate_count: qualityGateCount
        })
      ]
    );

    return {
      update_id: updateId,
      applied_at: appliedAt,
      summary_path: options.summaryPath ?? "",
      memory_update_path: `postgres://signal_radar_memory_updates/${updateId}`,
      run_metrics_path: "",
      memory_audit_path: `postgres://signal_radar_memory_audit_events?update_id=${updateId}`,
      memory_updates: versionCount,
      already_applied: false
    };
  });
}

async function insertMemoryQualityGates(
  client: PoolClient,
  parsed: MemoryUpdate,
  ids: { updateId: string; jobId: string | null; targetId: string | null }
): Promise<number> {
  let count = 0;
  for (const row of parsed.information_units) {
    await insertMemoryQualityGate(client, row, "memory.information_unit", ids);
    count += 1;
  }
  for (const row of parsed.event_clusters) {
    await insertMemoryQualityGate(client, row, "memory.event_cluster", ids);
    count += 1;
  }
  for (const row of parsed.alert_candidates) {
    await insertMemoryQualityGate(client, row, "memory.alert_candidate", ids);
    count += 1;
  }
  for (const row of parsed.contradictions) {
    await insertMemoryQualityGate(client, row, "memory.contradiction", ids);
    count += 1;
  }
  return count;
}

async function insertMemoryQualityGate(
  client: PoolClient,
  row: Record<string, JsonValue>,
  gateType: string,
  ids: { updateId: string; jobId: string | null; targetId: string | null }
): Promise<void> {
  await insertPostgresQualityGate(
    {
      jobId: ids.jobId,
      targetId: ids.targetId,
      updateId: ids.updateId,
      evidenceId: stringList(row.evidence_item_ids)[0] ?? null,
      gateType,
      subject: cleanText(row.subject ?? row.title ?? row.claim ?? row.summary),
      decision: qualityGateFromMemoryRow(row, gateType),
      payload: row
    },
    client
  );
}

async function applyMemoryRecords(
  client: PoolClient,
  options: {
    parsed: MemoryUpdate;
    updateId: string;
    jobId: string | null;
    artifactId: string | null;
    providerRunId: string | null;
    targetId: string | null;
  }
): Promise<number> {
  let versionCount = 0;
  const candidates = buildMemoryRecordCandidates(options.parsed);
  for (const candidate of candidates) {
    const current = await client.query<{
      memory_id: string;
      payload: Record<string, JsonValue>;
      current_version: number;
    }>(
      `
      SELECT memory_id, payload, current_version
      FROM signal_radar_memory_records
      WHERE collection = $1 AND record_key = $2
      FOR UPDATE
      `,
      [candidate.collection, candidate.recordKey]
    );

    const before = current.rows[0]?.payload ?? null;
    const change = buildMemoryVersionChange(candidate, before);
    if (change.operation === "noop") continue;

    const memoryId = current.rows[0]?.memory_id ?? (await insertMemoryRecord(client, candidate, options));
    const nextVersion = Number(current.rows[0]?.current_version ?? 0) + 1;
    const insertedVersion = await client.query<{ version_id: string }>(
      `
      INSERT INTO signal_radar_memory_versions (
        memory_id, version_number, update_id, job_id, artifact_id, provider_run_id,
        operation, before_payload, after_payload, diff
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb)
      RETURNING version_id
      `,
      [
        memoryId,
        nextVersion,
        options.updateId,
        options.jobId,
        options.artifactId,
        options.providerRunId,
        change.operation,
        before ? jsonb(before) : null,
        jsonb(change.after),
        jsonb(change.diff)
      ]
    );
    await client.query(
      `
      UPDATE signal_radar_memory_records
      SET title = $2, payload = $3::jsonb, current_version = $4, last_update_id = $5
      WHERE memory_id = $1
      `,
      [memoryId, candidate.title, jsonb(change.after), nextVersion, options.updateId]
    );
    await client.query(
      `
      INSERT INTO signal_radar_memory_audit_events (
        update_id, memory_id, version_id, job_id, event_type, severity, payload
      )
      VALUES ($1, $2, $3, $4, 'memory_record.versioned', 'info', $5::jsonb)
      `,
      [
        options.updateId,
        memoryId,
        insertedVersion.rows[0]?.version_id ?? null,
        options.jobId,
        jsonb({
          collection: candidate.collection,
          record_key: candidate.recordKey,
          operation: change.operation,
          diff_count: change.diff.length
        })
      ]
    );
    versionCount += 1;
  }
  return versionCount;
}

async function insertMemoryRecord(
  client: PoolClient,
  candidate: ReturnType<typeof buildMemoryRecordCandidates>[number],
  options: { targetId: string | null; updateId: string }
): Promise<string> {
  const inserted = await client.query<{ memory_id: string }>(
    `
    INSERT INTO signal_radar_memory_records (
      target_id, collection, record_key, title, payload, current_version, last_update_id
    )
    VALUES ($1, $2, $3, $4, '{}'::jsonb, 0, $5)
    ON CONFLICT (collection, record_key) DO UPDATE SET title = EXCLUDED.title
    RETURNING memory_id
    `,
    [options.targetId, candidate.collection, candidate.recordKey, candidate.title, options.updateId]
  );
  return inserted.rows[0].memory_id;
}

async function insertQueryableUpdateRows(
  client: PoolClient,
  parsed: MemoryUpdate,
  ids: { updateId: string; jobId: string | null; targetId: string | null }
): Promise<void> {
  for (const row of parsed.information_units) {
    const informationUnitId = cleanText(row.information_unit_id);
    if (!informationUnitId) continue;
    await client.query(
      `
      INSERT INTO signal_radar_information_units (
        information_unit_id, update_id, job_id, target_id, subject, claim,
        verification_status, signal_type, novelty_level, evidence_strength,
        memory_action, alert_level, confidence, evidence_item_ids, source_ids, payload
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::jsonb)
      ON CONFLICT (information_unit_id) DO UPDATE SET payload = EXCLUDED.payload
      `,
      [
        informationUnitId,
        ids.updateId,
        ids.jobId,
        ids.targetId,
        cleanText(row.subject),
        cleanText(row.claim),
        cleanText(row.verification_status),
        signalField(row, "signal_type"),
        signalField(row, "novelty_level"),
        signalField(row, "evidence_strength"),
        signalField(row, "memory_action"),
        signalField(row, "alert_level"),
        numberOrNull(signalField(row, "confidence")),
        stringList(row.evidence_item_ids),
        stringList(row.source_ids),
        jsonb(row)
      ]
    );
  }

  for (const row of parsed.event_clusters) {
    const clusterId = cleanText(row.cluster_id);
    if (!clusterId) continue;
    await client.query(
      `
      INSERT INTO signal_radar_event_clusters (
        cluster_id, update_id, job_id, target_id, title, summary, theme,
        signal_type, novelty_level, evidence_strength, memory_action, alert_level,
        confidence, evidence_item_ids, source_ids, payload
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16::jsonb)
      ON CONFLICT (cluster_id) DO UPDATE SET payload = EXCLUDED.payload
      `,
      [
        clusterId,
        ids.updateId,
        ids.jobId,
        ids.targetId,
        cleanText(row.title),
        cleanText(row.summary),
        cleanText(row.theme),
        signalField(row, "signal_type"),
        signalField(row, "novelty_level"),
        signalField(row, "evidence_strength"),
        signalField(row, "memory_action"),
        signalField(row, "alert_level"),
        numberOrNull(signalField(row, "confidence")),
        stringList(row.evidence_item_ids),
        stringList(row.source_ids),
        jsonb(row)
      ]
    );
  }

  for (const row of parsed.alert_candidates) {
    await client.query(
      `
      INSERT INTO signal_radar_alert_candidates (
        update_id, job_id, target_id, subject, alert_level, confidence,
        evidence_item_ids, source_ids, payload
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
      `,
      [
        ids.updateId,
        ids.jobId,
        ids.targetId,
        cleanText(row.subject ?? row.claim ?? row.title),
        signalField(row, "alert_level"),
        numberOrNull(signalField(row, "confidence")),
        stringList(row.evidence_item_ids),
        stringList(row.source_ids),
        jsonb(row)
      ]
    );
  }
}

function signalField(row: Record<string, JsonValue>, field: string): string {
  const direct = cleanText(row[field]);
  if (direct) return direct;
  const evaluation = row.signal_evaluation;
  if (evaluation && typeof evaluation === "object" && !Array.isArray(evaluation)) {
    return cleanText((evaluation as Record<string, JsonValue>)[field]);
  }
  return "";
}

function stringList(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.map(cleanText).filter(Boolean) : [];
}

function numberOrNull(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
