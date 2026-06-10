import { sql } from "drizzle-orm";
import {
  boolean,
  check,
  index,
  integer,
  jsonb,
  numeric,
  pgTable,
  text,
  timestamp,
  unique,
  uniqueIndex,
  uuid,
  type AnyPgColumn
} from "drizzle-orm/pg-core";

const jsonbObject = sql`'{}'::jsonb`;
const jsonbArray = sql`'[]'::jsonb`;
const textArray = sql`'{}'::text[]`;

export const signalRadarTargets = pgTable(
  "signal_radar_targets",
  {
    targetId: uuid("target_id").defaultRandom().primaryKey(),
    namespace: text("namespace").notNull().default("public_market"),
    symbol: text("symbol").notNull(),
    exchange: text("exchange"),
    displayName: text("display_name").notNull(),
    assetType: text("asset_type").notNull().default("equity"),
    country: text("country"),
    status: text("status").notNull().default("active"),
    profile: jsonb("profile").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    uniqueIndex("signal_radar_targets_identity_idx").on(
      table.namespace,
      table.symbol,
      sql`COALESCE(${table.exchange}, '')`
    )
  ]
);

export const signalRadarSources = pgTable(
  "signal_radar_sources",
  {
    sourceId: text("source_id").primaryKey(),
    sourceType: text("source_type").notNull().default("unknown"),
    displayName: text("display_name").notNull().default(""),
    canonicalUrl: text("canonical_url"),
    credibilityTier: text("credibility_tier").notNull().default("unknown"),
    qualityScore: numeric("quality_score", { precision: 5, scale: 4, mode: "number" }),
    profile: jsonb("profile").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_sources_credibility_tier_check",
      sql`${table.credibilityTier} IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')`
    ),
    index("signal_radar_sources_credibility_idx").on(table.credibilityTier, table.updatedAt)
  ]
);

export const signalRadarJobs = pgTable(
  "signal_radar_jobs",
  {
    jobId: text("job_id").primaryKey(),
    schemaVersion: text("schema_version").notNull().default("signal-radar-job/v1"),
    kind: text("kind").notNull(),
    status: text("status").notNull().default("queued"),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    title: text("title"),
    url: text("url"),
    userLabel: text("user_label"),
    inputChannel: text("input_channel").notNull().default("web"),
    contentType: text("content_type").notNull().default("note"),
    requiresVerification: boolean("requires_verification").notNull().default(false),
    provider: text("provider"),
    model: text("model"),
    config: jsonb("config").notNull().default(jsonbObject),
    input: jsonb("input").notNull().default(jsonbObject),
    result: jsonb("result").notNull().default(jsonbObject),
    error: text("error"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    queuedAt: timestamp("queued_at", { withTimezone: true }).notNull().defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    failedAt: timestamp("failed_at", { withTimezone: true }),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_jobs_status_check",
      sql`${table.status} IN ('queued', 'running', 'done', 'failed', 'canceled')`
    ),
    check(
      "signal_radar_jobs_job_id_check",
      sql`${table.jobId} ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$'`
    ),
    index("signal_radar_jobs_status_created_idx").on(table.status, table.createdAt)
  ]
);

export const signalRadarJobQueue = pgTable(
  "signal_radar_job_queue",
  {
    queueId: uuid("queue_id").defaultRandom().primaryKey(),
    jobId: text("job_id").notNull().references(() => signalRadarJobs.jobId, { onDelete: "cascade" }),
    queueName: text("queue_name").notNull().default("analysis"),
    status: text("status").notNull().default("queued"),
    priority: integer("priority").notNull().default(0),
    availableAt: timestamp("available_at", { withTimezone: true }).notNull().defaultNow(),
    attempts: integer("attempts").notNull().default(0),
    maxAttempts: integer("max_attempts").notNull().default(3),
    lockedBy: text("locked_by"),
    lockedUntil: timestamp("locked_until", { withTimezone: true }),
    lastError: text("last_error"),
    enqueuedAt: timestamp("enqueued_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_job_queue_status_check",
      sql`${table.status} IN ('queued', 'claimed', 'done', 'failed', 'dead', 'canceled')`
    ),
    unique("signal_radar_job_queue_job_queue_unique").on(table.jobId, table.queueName),
    index("signal_radar_job_queue_claim_idx")
      .on(table.queueName, table.status, table.availableAt, table.priority, table.enqueuedAt)
      .where(sql`${table.status} IN ('queued', 'failed')`)
  ]
);

export const signalRadarCollectorBatches = pgTable(
  "signal_radar_collector_batches",
  {
    batchId: uuid("batch_id").defaultRandom().primaryKey(),
    jobId: text("job_id").notNull().references(() => signalRadarJobs.jobId, { onDelete: "cascade" }),
    schemaVersion: text("schema_version").notNull(),
    itemSchemaVersion: text("item_schema_version").notNull(),
    source: text("source").notNull(),
    collectorRunId: text("collector_run_id").notNull(),
    collectedAt: timestamp("collected_at", { withTimezone: true }).notNull(),
    target: jsonb("target").notNull().default(jsonbObject),
    collector: jsonb("collector").notNull().default(jsonbObject),
    itemCount: integer("item_count").notNull().default(0),
    warnings: jsonb("warnings").notNull().default(jsonbArray),
    rawMeta: jsonb("raw_meta").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    unique("signal_radar_collector_batches_collector_run_unique").on(table.collectorRunId),
    index("signal_radar_collector_batches_job_idx").on(table.jobId)
  ]
);

export const signalRadarCollectorItems = pgTable(
  "signal_radar_collector_items",
  {
    canonicalId: text("canonical_id").primaryKey(),
    batchId: uuid("batch_id").notNull().references(() => signalRadarCollectorBatches.batchId, { onDelete: "cascade" }),
    source: text("source").notNull(),
    itemId: text("item_id").notNull(),
    contentType: text("content_type").notNull(),
    publishedAt: timestamp("published_at", { withTimezone: true }),
    collectedAt: timestamp("collected_at", { withTimezone: true }).notNull(),
    url: text("url"),
    title: text("title"),
    text: text("text").notNull(),
    language: text("language"),
    author: jsonb("author").notNull().default(jsonbObject),
    metrics: jsonb("metrics").notNull().default(jsonbObject),
    media: jsonb("media").notNull().default(jsonbArray),
    relations: jsonb("relations").notNull().default(jsonbObject),
    sourceMeta: jsonb("source_meta").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    index("signal_radar_collector_items_batch_idx").on(table.batchId)
  ]
);

export const signalRadarEvidenceItems = pgTable(
  "signal_radar_evidence_items",
  {
    evidenceId: text("evidence_id").primaryKey(),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    collectorItemId: text("collector_item_id").references(() => signalRadarCollectorItems.canonicalId, { onDelete: "set null" }),
    sourceId: text("source_id").references(() => signalRadarSources.sourceId, { onDelete: "set null" }),
    contentHash: text("content_hash").notNull(),
    duplicateOf: text("duplicate_of").references((): AnyPgColumn => signalRadarEvidenceItems.evidenceId, { onDelete: "set null" }),
    usefulnessStatus: text("usefulness_status").notNull().default("potential"),
    evidenceKind: text("evidence_kind").notNull().default("unknown"),
    sourceQuality: text("source_quality").notNull().default("unknown"),
    confidence: numeric("confidence", { precision: 5, scale: 4, mode: "number" }),
    filterReasons: text("filter_reasons").array().notNull().default(textArray),
    url: text("url"),
    title: text("title"),
    publishedAt: timestamp("published_at", { withTimezone: true }),
    collectedAt: timestamp("collected_at", { withTimezone: true }).notNull(),
    textExcerpt: text("text_excerpt").notNull().default(""),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_evidence_items_usefulness_status_check",
      sql`${table.usefulnessStatus} IN ('useful', 'potential', 'duplicate', 'low_value', 'rejected')`
    ),
    check(
      "signal_radar_evidence_items_evidence_kind_check",
      sql`${table.evidenceKind} IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')`
    ),
    check(
      "signal_radar_evidence_items_source_quality_check",
      sql`${table.sourceQuality} IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')`
    ),
    index("signal_radar_evidence_items_target_idx").on(table.targetId, table.createdAt),
    index("signal_radar_evidence_items_job_idx").on(table.jobId, table.createdAt),
    index("signal_radar_evidence_items_content_hash_idx").on(table.contentHash, table.createdAt),
    index("signal_radar_evidence_items_quality_idx").on(table.usefulnessStatus, table.evidenceKind, table.sourceQuality)
  ]
);

export const signalRadarAnalysisArtifacts = pgTable(
  "signal_radar_analysis_artifacts",
  {
    artifactId: uuid("artifact_id").defaultRandom().primaryKey(),
    jobId: text("job_id").notNull().references(() => signalRadarJobs.jobId, { onDelete: "cascade" }),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    runId: text("run_id").notNull(),
    status: text("status").notNull().default("created"),
    analysisInput: jsonb("analysis_input").notNull().default(jsonbObject),
    memoryContext: jsonb("memory_context").notNull().default(jsonbObject),
    rawReport: text("raw_report").notNull().default(""),
    prompt: text("prompt").notNull().default(""),
    report: text("report").notNull().default(""),
    summary: text("summary").notNull().default(""),
    runMetrics: jsonb("run_metrics").notNull().default(jsonbObject),
    generatedAt: timestamp("generated_at", { withTimezone: true }).notNull().defaultNow(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_analysis_artifacts_status_check",
      sql`${table.status} IN ('created', 'running', 'done', 'failed')`
    ),
    index("signal_radar_analysis_artifacts_job_idx").on(table.jobId, table.createdAt)
  ]
);

export const signalRadarProviderRuns = pgTable(
  "signal_radar_provider_runs",
  {
    providerRunId: uuid("provider_run_id").defaultRandom().primaryKey(),
    jobId: text("job_id").notNull().references(() => signalRadarJobs.jobId, { onDelete: "cascade" }),
    artifactId: uuid("artifact_id").references(() => signalRadarAnalysisArtifacts.artifactId, { onDelete: "set null" }),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    status: text("status").notNull().default("running"),
    promptHash: text("prompt_hash"),
    outputHash: text("output_hash"),
    inputTokens: integer("input_tokens"),
    outputTokens: integer("output_tokens"),
    costUsd: numeric("cost_usd", { precision: 12, scale: 6, mode: "number" }),
    error: text("error"),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    rawMeta: jsonb("raw_meta").notNull().default(jsonbObject)
  },
  (table) => [
    check(
      "signal_radar_provider_runs_status_check",
      sql`${table.status} IN ('running', 'done', 'failed')`
    )
  ]
);

export const signalRadarJobLogs = pgTable(
  "signal_radar_job_logs",
  {
    logId: uuid("log_id").defaultRandom().primaryKey(),
    jobId: text("job_id").notNull().references(() => signalRadarJobs.jobId, { onDelete: "cascade" }),
    action: text("action").notNull(),
    level: text("level").notNull().default("info"),
    message: text("message").notNull().default(""),
    stdout: text("stdout").notNull().default(""),
    stderr: text("stderr").notNull().default(""),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check("signal_radar_job_logs_level_check", sql`${table.level} IN ('debug', 'info', 'warn', 'error')`)
  ]
);

export const signalRadarMemoryUpdates = pgTable(
  "signal_radar_memory_updates",
  {
    updateId: text("update_id").primaryKey(),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    artifactId: uuid("artifact_id").references(() => signalRadarAnalysisArtifacts.artifactId, { onDelete: "set null" }),
    providerRunId: uuid("provider_run_id").references(() => signalRadarProviderRuns.providerRunId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    runId: text("run_id"),
    status: text("status").notNull().default("applied"),
    summaryHash: text("summary_hash").notNull(),
    parsed: jsonb("parsed").notNull().default(jsonbObject),
    informationUnitCount: integer("information_unit_count").notNull().default(0),
    eventClusterCount: integer("event_cluster_count").notNull().default(0),
    entityUpdatesApplied: integer("entity_updates_applied").notNull().default(0),
    eventUpdatesApplied: integer("event_updates_applied").notNull().default(0),
    macroUpdatesApplied: integer("macro_updates_applied").notNull().default(0),
    sourceUpdatesApplied: integer("source_updates_applied").notNull().default(0),
    memoryVersionsCreated: integer("memory_versions_created").notNull().default(0),
    error: text("error"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    appliedAt: timestamp("applied_at", { withTimezone: true })
  },
  (table) => [
    check(
      "signal_radar_memory_updates_status_check",
      sql`${table.status} IN ('applied', 'failed', 'skipped')`
    ),
    index("signal_radar_memory_updates_job_idx").on(table.jobId, table.createdAt)
  ]
);

export const signalRadarMemoryRecords = pgTable(
  "signal_radar_memory_records",
  {
    memoryId: uuid("memory_id").defaultRandom().primaryKey(),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    collection: text("collection").notNull(),
    recordKey: text("record_key").notNull(),
    title: text("title"),
    payload: jsonb("payload").notNull().default(jsonbObject),
    currentVersion: integer("current_version").notNull().default(0),
    lastUpdateId: text("last_update_id").references(() => signalRadarMemoryUpdates.updateId, { onDelete: "set null" }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    unique("signal_radar_memory_records_target_collection_key_unique").on(table.targetId, table.collection, table.recordKey),
    unique("signal_radar_memory_records_collection_key_unique").on(table.collection, table.recordKey),
    index("signal_radar_memory_records_collection_idx").on(table.collection, table.updatedAt)
  ]
);

export const signalRadarMemoryVersions = pgTable(
  "signal_radar_memory_versions",
  {
    versionId: uuid("version_id").defaultRandom().primaryKey(),
    memoryId: uuid("memory_id").notNull().references(() => signalRadarMemoryRecords.memoryId, { onDelete: "cascade" }),
    versionNumber: integer("version_number").notNull(),
    updateId: text("update_id").notNull().references(() => signalRadarMemoryUpdates.updateId, { onDelete: "cascade" }),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    artifactId: uuid("artifact_id").references(() => signalRadarAnalysisArtifacts.artifactId, { onDelete: "set null" }),
    providerRunId: uuid("provider_run_id").references(() => signalRadarProviderRuns.providerRunId, { onDelete: "set null" }),
    operation: text("operation").notNull(),
    beforePayload: jsonb("before_payload"),
    afterPayload: jsonb("after_payload"),
    diff: jsonb("diff").notNull().default(jsonbArray),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check("signal_radar_memory_versions_operation_check", sql`${table.operation} IN ('create', 'update', 'delete', 'noop')`),
    unique("signal_radar_memory_versions_memory_version_unique").on(table.memoryId, table.versionNumber),
    index("signal_radar_memory_versions_memory_idx").on(table.memoryId, table.versionNumber),
    index("signal_radar_memory_versions_update_idx").on(table.updateId)
  ]
);

export const signalRadarMemoryAuditEvents = pgTable(
  "signal_radar_memory_audit_events",
  {
    auditId: uuid("audit_id").defaultRandom().primaryKey(),
    updateId: text("update_id").references(() => signalRadarMemoryUpdates.updateId, { onDelete: "cascade" }),
    memoryId: uuid("memory_id").references(() => signalRadarMemoryRecords.memoryId, { onDelete: "set null" }),
    versionId: uuid("version_id").references(() => signalRadarMemoryVersions.versionId, { onDelete: "set null" }),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    eventType: text("event_type").notNull(),
    severity: text("severity").notNull().default("info"),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check("signal_radar_memory_audit_events_severity_check", sql`${table.severity} IN ('info', 'warn', 'error')`)
  ]
);

export const signalRadarInformationUnits = pgTable(
  "signal_radar_information_units",
  {
    informationUnitId: text("information_unit_id").primaryKey(),
    updateId: text("update_id").notNull().references(() => signalRadarMemoryUpdates.updateId, { onDelete: "cascade" }),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    subject: text("subject").notNull().default(""),
    claim: text("claim").notNull().default(""),
    verificationStatus: text("verification_status"),
    signalType: text("signal_type"),
    noveltyLevel: text("novelty_level"),
    evidenceStrength: text("evidence_strength"),
    memoryAction: text("memory_action"),
    alertLevel: text("alert_level"),
    confidence: numeric("confidence", { precision: 5, scale: 4, mode: "number" }),
    evidenceItemIds: text("evidence_item_ids").array().notNull().default(textArray),
    sourceIds: text("source_ids").array().notNull().default(textArray),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    index("signal_radar_information_units_subject_idx").on(table.subject)
  ]
);

export const signalRadarEventClusters = pgTable(
  "signal_radar_event_clusters",
  {
    clusterId: text("cluster_id").primaryKey(),
    updateId: text("update_id").notNull().references(() => signalRadarMemoryUpdates.updateId, { onDelete: "cascade" }),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    title: text("title").notNull().default(""),
    summary: text("summary").notNull().default(""),
    theme: text("theme"),
    signalType: text("signal_type"),
    noveltyLevel: text("novelty_level"),
    evidenceStrength: text("evidence_strength"),
    memoryAction: text("memory_action"),
    alertLevel: text("alert_level"),
    confidence: numeric("confidence", { precision: 5, scale: 4, mode: "number" }),
    evidenceItemIds: text("evidence_item_ids").array().notNull().default(textArray),
    sourceIds: text("source_ids").array().notNull().default(textArray),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    index("signal_radar_event_clusters_theme_idx").on(table.theme)
  ]
);

export const signalRadarAlertCandidates = pgTable(
  "signal_radar_alert_candidates",
  {
    alertId: uuid("alert_id").defaultRandom().primaryKey(),
    updateId: text("update_id").notNull().references(() => signalRadarMemoryUpdates.updateId, { onDelete: "cascade" }),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    subject: text("subject").notNull().default(""),
    alertLevel: text("alert_level"),
    confidence: numeric("confidence", { precision: 5, scale: 4, mode: "number" }),
    evidenceItemIds: text("evidence_item_ids").array().notNull().default(textArray),
    sourceIds: text("source_ids").array().notNull().default(textArray),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  }
);

export const signalRadarQualityGates = pgTable(
  "signal_radar_quality_gates",
  {
    gateId: uuid("gate_id").defaultRandom().primaryKey(),
    jobId: text("job_id").references(() => signalRadarJobs.jobId, { onDelete: "set null" }),
    targetId: uuid("target_id").references(() => signalRadarTargets.targetId, { onDelete: "set null" }),
    updateId: text("update_id").references(() => signalRadarMemoryUpdates.updateId, { onDelete: "set null" }),
    memoryId: uuid("memory_id").references(() => signalRadarMemoryRecords.memoryId, { onDelete: "set null" }),
    evidenceId: text("evidence_id").references(() => signalRadarEvidenceItems.evidenceId, { onDelete: "set null" }),
    gateType: text("gate_type").notNull(),
    subject: text("subject").notNull().default(""),
    status: text("status").notNull().default("watch"),
    evidenceKind: text("evidence_kind").notNull().default("unknown"),
    evidenceStrength: text("evidence_strength").notNull().default("unknown"),
    verificationStatus: text("verification_status").notNull().default("unverified"),
    sourceQuality: text("source_quality").notNull().default("unknown"),
    severity: text("severity").notNull().default("info"),
    reason: text("reason").notNull().default(""),
    payload: jsonb("payload").notNull().default(jsonbObject),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow()
  },
  (table) => [
    check(
      "signal_radar_quality_gates_status_check",
      sql`${table.status} IN ('allow', 'watch', 'skip', 'block', 'needs_agent_recheck')`
    ),
    check(
      "signal_radar_quality_gates_evidence_kind_check",
      sql`${table.evidenceKind} IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')`
    ),
    check(
      "signal_radar_quality_gates_source_quality_check",
      sql`${table.sourceQuality} IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')`
    ),
    check(
      "signal_radar_quality_gates_severity_check",
      sql`${table.severity} IN ('info', 'watch', 'warning', 'critical')`
    ),
    index("signal_radar_quality_gates_target_idx").on(table.targetId, table.createdAt),
    index("signal_radar_quality_gates_job_idx").on(table.jobId, table.createdAt),
    index("signal_radar_quality_gates_status_idx").on(table.status, table.severity, table.createdAt)
  ]
);
