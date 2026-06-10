import { desc, eq, or, sql } from "drizzle-orm";
import type { Pool, PoolClient } from "pg";
import { createSignalRadarDrizzle, signalRadarSchema } from "./drizzle";
import type { JsonValue } from "./types";

export type TargetReadMemoryRecord = {
  memory_id: string;
  collection: string;
  record_key: string;
  title: string | null;
  current_version: number;
  updated_at: string;
  last_update_id: string | null;
  preview: string;
  payload: JsonValue;
};

export type TargetReadEvidenceItem = {
  evidence_id: string;
  job_id: string | null;
  source_id: string | null;
  usefulness_status: string;
  evidence_kind: string;
  source_quality: string;
  confidence: number | null;
  filter_reasons: string[];
  url: string | null;
  title: string | null;
  published_at: string | null;
  collected_at: string;
  text_excerpt: string;
  duplicate_of: string | null;
  created_at: string;
};

export type TargetReadQualityGate = {
  gate_id: string;
  job_id: string | null;
  update_id: string | null;
  memory_id: string | null;
  evidence_id: string | null;
  gate_type: string;
  subject: string;
  status: string;
  evidence_kind: string;
  evidence_strength: string;
  verification_status: string;
  source_quality: string;
  severity: string;
  reason: string;
  created_at: string;
};

export type TargetReadLatestChange = {
  version_id: string;
  memory_id: string;
  collection: string;
  record_key: string;
  title: string | null;
  version_number: number;
  operation: string;
  diff: JsonValue;
  update_id: string;
  created_at: string;
};

export type TargetReadModelV1 = {
  schema_version: "target_read_model/v1";
  code: string;
  generated_at: string;
  overview: {
    exists: boolean;
    target: {
      target_id: string;
      namespace: string;
      symbol: string;
      exchange: string | null;
      display_name: string;
      asset_type: string;
      country: string | null;
      status: string;
      profile: JsonValue;
      updated_at: string;
    } | null;
    counts: {
      memory_records: number;
      latest_changes: number;
      evidence_items: number;
      quality_gates: number;
    };
  };
  fundamentals: {
    records: TargetReadMemoryRecord[];
  };
  segments: {
    records: TargetReadMemoryRecord[];
  };
  concepts: {
    records: TargetReadMemoryRecord[];
  };
  timeline: {
    records: TargetReadMemoryRecord[];
    latest_changes: TargetReadLatestChange[];
  };
  evidence: TargetReadEvidenceItem[];
  quality_gates: TargetReadQualityGate[];
  latest_changes: TargetReadLatestChange[];
};

type QueryTarget = Pool | PoolClient;

export async function getPostgresTargetReadModelV1(
  code: string,
  queryable?: QueryTarget
): Promise<TargetReadModelV1> {
  const normalizedCode = normalizeTargetCode(code);
  if (!normalizedCode) throw new Error("target code is required");
  const generatedAt = new Date().toISOString();
  const db = createSignalRadarDrizzle(queryable);
  const schema = signalRadarSchema;

  const [targetRow] = await db
    .select({
      targetId: schema.signalRadarTargets.targetId,
      namespace: schema.signalRadarTargets.namespace,
      symbol: schema.signalRadarTargets.symbol,
      exchange: schema.signalRadarTargets.exchange,
      displayName: schema.signalRadarTargets.displayName,
      assetType: schema.signalRadarTargets.assetType,
      country: schema.signalRadarTargets.country,
      status: schema.signalRadarTargets.status,
      profile: schema.signalRadarTargets.profile,
      updatedAt: schema.signalRadarTargets.updatedAt
    })
    .from(schema.signalRadarTargets)
    .where(
      or(
        sql`lower(${schema.signalRadarTargets.symbol}) = lower(${normalizedCode})`,
        sql`${schema.signalRadarTargets.targetId}::text = ${normalizedCode}`
      )
    )
    .orderBy(desc(schema.signalRadarTargets.updatedAt))
    .limit(1);

  if (!targetRow) {
    return emptyTargetReadModel(normalizedCode, generatedAt);
  }

  const targetId = targetRow.targetId;
  const memoryRows = await db
    .select({
      memoryId: schema.signalRadarMemoryRecords.memoryId,
      collection: schema.signalRadarMemoryRecords.collection,
      recordKey: schema.signalRadarMemoryRecords.recordKey,
      title: schema.signalRadarMemoryRecords.title,
      payload: schema.signalRadarMemoryRecords.payload,
      currentVersion: schema.signalRadarMemoryRecords.currentVersion,
      updatedAt: schema.signalRadarMemoryRecords.updatedAt,
      lastUpdateId: schema.signalRadarMemoryRecords.lastUpdateId
    })
    .from(schema.signalRadarMemoryRecords)
    .where(eq(schema.signalRadarMemoryRecords.targetId, targetId))
    .orderBy(desc(schema.signalRadarMemoryRecords.updatedAt))
    .limit(120);

  const latestChangeRows = await db
    .select({
      versionId: schema.signalRadarMemoryVersions.versionId,
      memoryId: schema.signalRadarMemoryRecords.memoryId,
      collection: schema.signalRadarMemoryRecords.collection,
      recordKey: schema.signalRadarMemoryRecords.recordKey,
      title: schema.signalRadarMemoryRecords.title,
      versionNumber: schema.signalRadarMemoryVersions.versionNumber,
      operation: schema.signalRadarMemoryVersions.operation,
      diff: schema.signalRadarMemoryVersions.diff,
      updateId: schema.signalRadarMemoryVersions.updateId,
      createdAt: schema.signalRadarMemoryVersions.createdAt
    })
    .from(schema.signalRadarMemoryVersions)
    .innerJoin(
      schema.signalRadarMemoryRecords,
      eq(schema.signalRadarMemoryRecords.memoryId, schema.signalRadarMemoryVersions.memoryId)
    )
    .where(eq(schema.signalRadarMemoryRecords.targetId, targetId))
    .orderBy(desc(schema.signalRadarMemoryVersions.createdAt))
    .limit(60);

  const evidenceRows = await db
    .select({
      evidenceId: schema.signalRadarEvidenceItems.evidenceId,
      jobId: schema.signalRadarEvidenceItems.jobId,
      sourceId: schema.signalRadarEvidenceItems.sourceId,
      usefulnessStatus: schema.signalRadarEvidenceItems.usefulnessStatus,
      evidenceKind: schema.signalRadarEvidenceItems.evidenceKind,
      sourceQuality: schema.signalRadarEvidenceItems.sourceQuality,
      confidence: schema.signalRadarEvidenceItems.confidence,
      filterReasons: schema.signalRadarEvidenceItems.filterReasons,
      url: schema.signalRadarEvidenceItems.url,
      title: schema.signalRadarEvidenceItems.title,
      publishedAt: schema.signalRadarEvidenceItems.publishedAt,
      collectedAt: schema.signalRadarEvidenceItems.collectedAt,
      textExcerpt: schema.signalRadarEvidenceItems.textExcerpt,
      duplicateOf: schema.signalRadarEvidenceItems.duplicateOf,
      createdAt: schema.signalRadarEvidenceItems.createdAt
    })
    .from(schema.signalRadarEvidenceItems)
    .where(eq(schema.signalRadarEvidenceItems.targetId, targetId))
    .orderBy(desc(schema.signalRadarEvidenceItems.createdAt))
    .limit(120);

  const gateRows = await db
    .select({
      gateId: schema.signalRadarQualityGates.gateId,
      jobId: schema.signalRadarQualityGates.jobId,
      updateId: schema.signalRadarQualityGates.updateId,
      memoryId: schema.signalRadarQualityGates.memoryId,
      evidenceId: schema.signalRadarQualityGates.evidenceId,
      gateType: schema.signalRadarQualityGates.gateType,
      subject: schema.signalRadarQualityGates.subject,
      status: schema.signalRadarQualityGates.status,
      evidenceKind: schema.signalRadarQualityGates.evidenceKind,
      evidenceStrength: schema.signalRadarQualityGates.evidenceStrength,
      verificationStatus: schema.signalRadarQualityGates.verificationStatus,
      sourceQuality: schema.signalRadarQualityGates.sourceQuality,
      severity: schema.signalRadarQualityGates.severity,
      reason: schema.signalRadarQualityGates.reason,
      createdAt: schema.signalRadarQualityGates.createdAt
    })
    .from(schema.signalRadarQualityGates)
    .where(eq(schema.signalRadarQualityGates.targetId, targetId))
    .orderBy(desc(schema.signalRadarQualityGates.createdAt))
    .limit(120);

  const memory = memoryRows.map((row) => ({
    memory_id: row.memoryId,
    collection: row.collection,
    record_key: row.recordKey,
    title: row.title,
    current_version: row.currentVersion,
    updated_at: toIso(row.updatedAt),
    last_update_id: row.lastUpdateId,
    preview: memoryPreview(row.payload as JsonValue),
    payload: row.payload as JsonValue
  }));
  const latestChanges = latestChangeRows.map((row) => ({
    version_id: row.versionId,
    memory_id: row.memoryId,
    collection: row.collection,
    record_key: row.recordKey,
    title: row.title,
    version_number: row.versionNumber,
    operation: row.operation,
    diff: row.diff as JsonValue,
    update_id: row.updateId,
    created_at: toIso(row.createdAt)
  }));
  const evidence = evidenceRows.map((row) => ({
    evidence_id: row.evidenceId,
    job_id: row.jobId,
    source_id: row.sourceId,
    usefulness_status: row.usefulnessStatus,
    evidence_kind: row.evidenceKind,
    source_quality: row.sourceQuality,
    confidence: row.confidence === null ? null : Number(row.confidence),
    filter_reasons: Array.isArray(row.filterReasons) ? row.filterReasons.map(String) : [],
    url: row.url,
    title: row.title,
    published_at: row.publishedAt ? toIso(row.publishedAt) : null,
    collected_at: toIso(row.collectedAt),
    text_excerpt: row.textExcerpt,
    duplicate_of: row.duplicateOf,
    created_at: toIso(row.createdAt)
  }));
  const qualityGates = gateRows.map((row) => ({
    gate_id: row.gateId,
    job_id: row.jobId,
    update_id: row.updateId,
    memory_id: row.memoryId,
    evidence_id: row.evidenceId,
    gate_type: row.gateType,
    subject: row.subject,
    status: row.status,
    evidence_kind: row.evidenceKind,
    evidence_strength: row.evidenceStrength,
    verification_status: row.verificationStatus,
    source_quality: row.sourceQuality,
    severity: row.severity,
    reason: row.reason,
    created_at: toIso(row.createdAt)
  }));

  return {
    schema_version: "target_read_model/v1",
    code: targetRow.symbol,
    generated_at: generatedAt,
    overview: {
      exists: true,
      target: {
        target_id: targetRow.targetId,
        namespace: targetRow.namespace,
        symbol: targetRow.symbol,
        exchange: targetRow.exchange,
        display_name: targetRow.displayName,
        asset_type: targetRow.assetType,
        country: targetRow.country,
        status: targetRow.status,
        profile: targetRow.profile as JsonValue,
        updated_at: toIso(targetRow.updatedAt)
      },
      counts: {
        memory_records: memory.length,
        latest_changes: latestChanges.length,
        evidence_items: evidence.length,
        quality_gates: qualityGates.length
      }
    },
    fundamentals: {
      records: memory.filter((row) => ["entities", "accounts", "macro", "sources"].includes(row.collection))
    },
    segments: {
      records: memory.filter((row) => isSegmentRecord(row))
    },
    concepts: {
      records: memory.filter((row) => ["themes", "information_units"].includes(row.collection))
    },
    timeline: {
      records: memory.filter((row) => ["events", "event_clusters"].includes(row.collection)),
      latest_changes: latestChanges
    },
    evidence,
    quality_gates: qualityGates,
    latest_changes: latestChanges
  };
}

function emptyTargetReadModel(code: string, generatedAt: string): TargetReadModelV1 {
  return {
    schema_version: "target_read_model/v1",
    code,
    generated_at: generatedAt,
    overview: {
      exists: false,
      target: null,
      counts: {
        memory_records: 0,
        latest_changes: 0,
        evidence_items: 0,
        quality_gates: 0
      }
    },
    fundamentals: { records: [] },
    segments: { records: [] },
    concepts: { records: [] },
    timeline: { records: [], latest_changes: [] },
    evidence: [],
    quality_gates: [],
    latest_changes: []
  };
}

function isSegmentRecord(row: TargetReadMemoryRecord): boolean {
  const text = `${row.collection} ${row.record_key} ${row.title ?? ""}`.toLowerCase();
  if (text.includes("segment") || text.includes("business") || text.includes("业务")) return true;
  const payload = row.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  return Boolean(
    (payload as Record<string, JsonValue>).segment ||
      (payload as Record<string, JsonValue>).business_segment ||
      (payload as Record<string, JsonValue>).business_composition
  );
}

function normalizeTargetCode(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

function toIso(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : String(value);
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
  ).slice(0, 220);
}
