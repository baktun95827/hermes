CREATE TABLE "signal_radar_alert_candidates" (
	"alert_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"update_id" text NOT NULL,
	"job_id" text,
	"target_id" uuid,
	"subject" text DEFAULT '' NOT NULL,
	"alert_level" text,
	"confidence" numeric(5, 4),
	"evidence_item_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"source_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "signal_radar_analysis_artifacts" (
	"artifact_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"run_id" text NOT NULL,
	"status" text DEFAULT 'created' NOT NULL,
	"analysis_input" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"memory_context" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"raw_report" text DEFAULT '' NOT NULL,
	"prompt" text DEFAULT '' NOT NULL,
	"report" text DEFAULT '' NOT NULL,
	"summary" text DEFAULT '' NOT NULL,
	"run_metrics" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"generated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_analysis_artifacts_status_check" CHECK ("signal_radar_analysis_artifacts"."status" IN ('created', 'running', 'done', 'failed'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_collector_batches" (
	"batch_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text NOT NULL,
	"schema_version" text NOT NULL,
	"item_schema_version" text NOT NULL,
	"source" text NOT NULL,
	"collector_run_id" text NOT NULL,
	"collected_at" timestamp with time zone NOT NULL,
	"target" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"collector" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"item_count" integer DEFAULT 0 NOT NULL,
	"warnings" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"raw_meta" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_collector_batches_collector_run_unique" UNIQUE("collector_run_id")
);
--> statement-breakpoint
CREATE TABLE "signal_radar_collector_items" (
	"canonical_id" text PRIMARY KEY NOT NULL,
	"batch_id" uuid NOT NULL,
	"source" text NOT NULL,
	"item_id" text NOT NULL,
	"content_type" text NOT NULL,
	"published_at" timestamp with time zone,
	"collected_at" timestamp with time zone NOT NULL,
	"url" text,
	"title" text,
	"text" text NOT NULL,
	"language" text,
	"author" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"metrics" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"media" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"relations" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"source_meta" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "signal_radar_event_clusters" (
	"cluster_id" text PRIMARY KEY NOT NULL,
	"update_id" text NOT NULL,
	"job_id" text,
	"target_id" uuid,
	"title" text DEFAULT '' NOT NULL,
	"summary" text DEFAULT '' NOT NULL,
	"theme" text,
	"signal_type" text,
	"novelty_level" text,
	"evidence_strength" text,
	"memory_action" text,
	"alert_level" text,
	"confidence" numeric(5, 4),
	"evidence_item_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"source_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "signal_radar_evidence_items" (
	"evidence_id" text PRIMARY KEY NOT NULL,
	"job_id" text,
	"target_id" uuid,
	"collector_item_id" text,
	"source_id" text,
	"content_hash" text NOT NULL,
	"duplicate_of" text,
	"usefulness_status" text DEFAULT 'potential' NOT NULL,
	"evidence_kind" text DEFAULT 'unknown' NOT NULL,
	"source_quality" text DEFAULT 'unknown' NOT NULL,
	"confidence" numeric(5, 4),
	"filter_reasons" text[] DEFAULT '{}'::text[] NOT NULL,
	"url" text,
	"title" text,
	"published_at" timestamp with time zone,
	"collected_at" timestamp with time zone NOT NULL,
	"text_excerpt" text DEFAULT '' NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_evidence_items_usefulness_status_check" CHECK ("signal_radar_evidence_items"."usefulness_status" IN ('useful', 'potential', 'duplicate', 'low_value', 'rejected')),
	CONSTRAINT "signal_radar_evidence_items_evidence_kind_check" CHECK ("signal_radar_evidence_items"."evidence_kind" IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')),
	CONSTRAINT "signal_radar_evidence_items_source_quality_check" CHECK ("signal_radar_evidence_items"."source_quality" IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_information_units" (
	"information_unit_id" text PRIMARY KEY NOT NULL,
	"update_id" text NOT NULL,
	"job_id" text,
	"target_id" uuid,
	"subject" text DEFAULT '' NOT NULL,
	"claim" text DEFAULT '' NOT NULL,
	"verification_status" text,
	"signal_type" text,
	"novelty_level" text,
	"evidence_strength" text,
	"memory_action" text,
	"alert_level" text,
	"confidence" numeric(5, 4),
	"evidence_item_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"source_ids" text[] DEFAULT '{}'::text[] NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "signal_radar_job_logs" (
	"log_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text NOT NULL,
	"action" text NOT NULL,
	"level" text DEFAULT 'info' NOT NULL,
	"message" text DEFAULT '' NOT NULL,
	"stdout" text DEFAULT '' NOT NULL,
	"stderr" text DEFAULT '' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_job_logs_level_check" CHECK ("signal_radar_job_logs"."level" IN ('debug', 'info', 'warn', 'error'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_job_queue" (
	"queue_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text NOT NULL,
	"queue_name" text DEFAULT 'analysis' NOT NULL,
	"status" text DEFAULT 'queued' NOT NULL,
	"priority" integer DEFAULT 0 NOT NULL,
	"available_at" timestamp with time zone DEFAULT now() NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 3 NOT NULL,
	"locked_by" text,
	"locked_until" timestamp with time zone,
	"last_error" text,
	"enqueued_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_job_queue_job_queue_unique" UNIQUE("job_id","queue_name"),
	CONSTRAINT "signal_radar_job_queue_status_check" CHECK ("signal_radar_job_queue"."status" IN ('queued', 'claimed', 'done', 'failed', 'dead', 'canceled'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"schema_version" text DEFAULT 'signal-radar-job/v1' NOT NULL,
	"kind" text NOT NULL,
	"status" text DEFAULT 'queued' NOT NULL,
	"target_id" uuid,
	"title" text,
	"url" text,
	"user_label" text,
	"input_channel" text DEFAULT 'web' NOT NULL,
	"content_type" text DEFAULT 'note' NOT NULL,
	"requires_verification" boolean DEFAULT false NOT NULL,
	"provider" text,
	"model" text,
	"config" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"input" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"result" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"queued_at" timestamp with time zone DEFAULT now() NOT NULL,
	"started_at" timestamp with time zone,
	"finished_at" timestamp with time zone,
	"failed_at" timestamp with time zone,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_jobs_status_check" CHECK ("signal_radar_jobs"."status" IN ('queued', 'running', 'done', 'failed', 'canceled')),
	CONSTRAINT "signal_radar_jobs_job_id_check" CHECK ("signal_radar_jobs"."job_id" ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$')
);
--> statement-breakpoint
CREATE TABLE "signal_radar_memory_audit_events" (
	"audit_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"update_id" text,
	"memory_id" uuid,
	"version_id" uuid,
	"job_id" text,
	"event_type" text NOT NULL,
	"severity" text DEFAULT 'info' NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_memory_audit_events_severity_check" CHECK ("signal_radar_memory_audit_events"."severity" IN ('info', 'warn', 'error'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_memory_records" (
	"memory_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"target_id" uuid,
	"collection" text NOT NULL,
	"record_key" text NOT NULL,
	"title" text,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"current_version" integer DEFAULT 0 NOT NULL,
	"last_update_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_memory_records_target_collection_key_unique" UNIQUE("target_id","collection","record_key"),
	CONSTRAINT "signal_radar_memory_records_collection_key_unique" UNIQUE("collection","record_key")
);
--> statement-breakpoint
CREATE TABLE "signal_radar_memory_updates" (
	"update_id" text PRIMARY KEY NOT NULL,
	"job_id" text,
	"artifact_id" uuid,
	"provider_run_id" uuid,
	"target_id" uuid,
	"run_id" text,
	"status" text DEFAULT 'applied' NOT NULL,
	"summary_hash" text NOT NULL,
	"parsed" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"information_unit_count" integer DEFAULT 0 NOT NULL,
	"event_cluster_count" integer DEFAULT 0 NOT NULL,
	"entity_updates_applied" integer DEFAULT 0 NOT NULL,
	"event_updates_applied" integer DEFAULT 0 NOT NULL,
	"macro_updates_applied" integer DEFAULT 0 NOT NULL,
	"source_updates_applied" integer DEFAULT 0 NOT NULL,
	"memory_versions_created" integer DEFAULT 0 NOT NULL,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"applied_at" timestamp with time zone,
	CONSTRAINT "signal_radar_memory_updates_status_check" CHECK ("signal_radar_memory_updates"."status" IN ('applied', 'failed', 'skipped'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_memory_versions" (
	"version_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"memory_id" uuid NOT NULL,
	"version_number" integer NOT NULL,
	"update_id" text NOT NULL,
	"job_id" text,
	"artifact_id" uuid,
	"provider_run_id" uuid,
	"operation" text NOT NULL,
	"before_payload" jsonb,
	"after_payload" jsonb,
	"diff" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_memory_versions_memory_version_unique" UNIQUE("memory_id","version_number"),
	CONSTRAINT "signal_radar_memory_versions_operation_check" CHECK ("signal_radar_memory_versions"."operation" IN ('create', 'update', 'delete', 'noop'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_provider_runs" (
	"provider_run_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text NOT NULL,
	"artifact_id" uuid,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"status" text DEFAULT 'running' NOT NULL,
	"prompt_hash" text,
	"output_hash" text,
	"input_tokens" integer,
	"output_tokens" integer,
	"cost_usd" numeric(12, 6),
	"error" text,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"finished_at" timestamp with time zone,
	"raw_meta" jsonb DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT "signal_radar_provider_runs_status_check" CHECK ("signal_radar_provider_runs"."status" IN ('running', 'done', 'failed'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_quality_gates" (
	"gate_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" text,
	"target_id" uuid,
	"update_id" text,
	"memory_id" uuid,
	"evidence_id" text,
	"gate_type" text NOT NULL,
	"subject" text DEFAULT '' NOT NULL,
	"status" text DEFAULT 'watch' NOT NULL,
	"evidence_kind" text DEFAULT 'unknown' NOT NULL,
	"evidence_strength" text DEFAULT 'unknown' NOT NULL,
	"verification_status" text DEFAULT 'unverified' NOT NULL,
	"source_quality" text DEFAULT 'unknown' NOT NULL,
	"severity" text DEFAULT 'info' NOT NULL,
	"reason" text DEFAULT '' NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_quality_gates_status_check" CHECK ("signal_radar_quality_gates"."status" IN ('allow', 'watch', 'skip', 'block', 'needs_agent_recheck')),
	CONSTRAINT "signal_radar_quality_gates_evidence_kind_check" CHECK ("signal_radar_quality_gates"."evidence_kind" IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')),
	CONSTRAINT "signal_radar_quality_gates_source_quality_check" CHECK ("signal_radar_quality_gates"."source_quality" IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')),
	CONSTRAINT "signal_radar_quality_gates_severity_check" CHECK ("signal_radar_quality_gates"."severity" IN ('info', 'watch', 'warning', 'critical'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_sources" (
	"source_id" text PRIMARY KEY NOT NULL,
	"source_type" text DEFAULT 'unknown' NOT NULL,
	"display_name" text DEFAULT '' NOT NULL,
	"canonical_url" text,
	"credibility_tier" text DEFAULT 'unknown' NOT NULL,
	"quality_score" numeric(5, 4),
	"profile" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "signal_radar_sources_credibility_tier_check" CHECK ("signal_radar_sources"."credibility_tier" IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown'))
);
--> statement-breakpoint
CREATE TABLE "signal_radar_targets" (
	"target_id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"namespace" text DEFAULT 'public_market' NOT NULL,
	"symbol" text NOT NULL,
	"exchange" text,
	"display_name" text NOT NULL,
	"asset_type" text DEFAULT 'equity' NOT NULL,
	"country" text,
	"status" text DEFAULT 'active' NOT NULL,
	"profile" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "signal_radar_alert_candidates" ADD CONSTRAINT "signal_radar_alert_candidates_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_alert_candidates" ADD CONSTRAINT "signal_radar_alert_candidates_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_alert_candidates" ADD CONSTRAINT "signal_radar_alert_candidates_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_analysis_artifacts" ADD CONSTRAINT "signal_radar_analysis_artifacts_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_collector_batches" ADD CONSTRAINT "signal_radar_collector_batches_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_collector_items" ADD CONSTRAINT "signal_radar_collector_items_batch_id_signal_radar_collector_batches_batch_id_fk" FOREIGN KEY ("batch_id") REFERENCES "public"."signal_radar_collector_batches"("batch_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_event_clusters" ADD CONSTRAINT "signal_radar_event_clusters_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_event_clusters" ADD CONSTRAINT "signal_radar_event_clusters_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_event_clusters" ADD CONSTRAINT "signal_radar_event_clusters_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_evidence_items" ADD CONSTRAINT "signal_radar_evidence_items_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_evidence_items" ADD CONSTRAINT "signal_radar_evidence_items_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_evidence_items" ADD CONSTRAINT "signal_radar_evidence_items_collector_item_id_signal_radar_collector_items_canonical_id_fk" FOREIGN KEY ("collector_item_id") REFERENCES "public"."signal_radar_collector_items"("canonical_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_evidence_items" ADD CONSTRAINT "signal_radar_evidence_items_source_id_signal_radar_sources_source_id_fk" FOREIGN KEY ("source_id") REFERENCES "public"."signal_radar_sources"("source_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_evidence_items" ADD CONSTRAINT "signal_radar_evidence_items_duplicate_of_signal_radar_evidence_items_evidence_id_fk" FOREIGN KEY ("duplicate_of") REFERENCES "public"."signal_radar_evidence_items"("evidence_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_information_units" ADD CONSTRAINT "signal_radar_information_units_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_information_units" ADD CONSTRAINT "signal_radar_information_units_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_information_units" ADD CONSTRAINT "signal_radar_information_units_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_job_logs" ADD CONSTRAINT "signal_radar_job_logs_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_job_queue" ADD CONSTRAINT "signal_radar_job_queue_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_jobs" ADD CONSTRAINT "signal_radar_jobs_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_audit_events" ADD CONSTRAINT "signal_radar_memory_audit_events_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_audit_events" ADD CONSTRAINT "signal_radar_memory_audit_events_memory_id_signal_radar_memory_records_memory_id_fk" FOREIGN KEY ("memory_id") REFERENCES "public"."signal_radar_memory_records"("memory_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_audit_events" ADD CONSTRAINT "signal_radar_memory_audit_events_version_id_signal_radar_memory_versions_version_id_fk" FOREIGN KEY ("version_id") REFERENCES "public"."signal_radar_memory_versions"("version_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_audit_events" ADD CONSTRAINT "signal_radar_memory_audit_events_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_records" ADD CONSTRAINT "signal_radar_memory_records_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_records" ADD CONSTRAINT "signal_radar_memory_records_last_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("last_update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_updates" ADD CONSTRAINT "signal_radar_memory_updates_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_updates" ADD CONSTRAINT "signal_radar_memory_updates_artifact_id_signal_radar_analysis_artifacts_artifact_id_fk" FOREIGN KEY ("artifact_id") REFERENCES "public"."signal_radar_analysis_artifacts"("artifact_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_updates" ADD CONSTRAINT "signal_radar_memory_updates_provider_run_id_signal_radar_provider_runs_provider_run_id_fk" FOREIGN KEY ("provider_run_id") REFERENCES "public"."signal_radar_provider_runs"("provider_run_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_updates" ADD CONSTRAINT "signal_radar_memory_updates_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_versions" ADD CONSTRAINT "signal_radar_memory_versions_memory_id_signal_radar_memory_records_memory_id_fk" FOREIGN KEY ("memory_id") REFERENCES "public"."signal_radar_memory_records"("memory_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_versions" ADD CONSTRAINT "signal_radar_memory_versions_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_versions" ADD CONSTRAINT "signal_radar_memory_versions_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_versions" ADD CONSTRAINT "signal_radar_memory_versions_artifact_id_signal_radar_analysis_artifacts_artifact_id_fk" FOREIGN KEY ("artifact_id") REFERENCES "public"."signal_radar_analysis_artifacts"("artifact_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_memory_versions" ADD CONSTRAINT "signal_radar_memory_versions_provider_run_id_signal_radar_provider_runs_provider_run_id_fk" FOREIGN KEY ("provider_run_id") REFERENCES "public"."signal_radar_provider_runs"("provider_run_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_provider_runs" ADD CONSTRAINT "signal_radar_provider_runs_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_provider_runs" ADD CONSTRAINT "signal_radar_provider_runs_artifact_id_signal_radar_analysis_artifacts_artifact_id_fk" FOREIGN KEY ("artifact_id") REFERENCES "public"."signal_radar_analysis_artifacts"("artifact_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_quality_gates" ADD CONSTRAINT "signal_radar_quality_gates_job_id_signal_radar_jobs_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."signal_radar_jobs"("job_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_quality_gates" ADD CONSTRAINT "signal_radar_quality_gates_target_id_signal_radar_targets_target_id_fk" FOREIGN KEY ("target_id") REFERENCES "public"."signal_radar_targets"("target_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_quality_gates" ADD CONSTRAINT "signal_radar_quality_gates_update_id_signal_radar_memory_updates_update_id_fk" FOREIGN KEY ("update_id") REFERENCES "public"."signal_radar_memory_updates"("update_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_quality_gates" ADD CONSTRAINT "signal_radar_quality_gates_memory_id_signal_radar_memory_records_memory_id_fk" FOREIGN KEY ("memory_id") REFERENCES "public"."signal_radar_memory_records"("memory_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "signal_radar_quality_gates" ADD CONSTRAINT "signal_radar_quality_gates_evidence_id_signal_radar_evidence_items_evidence_id_fk" FOREIGN KEY ("evidence_id") REFERENCES "public"."signal_radar_evidence_items"("evidence_id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "signal_radar_analysis_artifacts_job_idx" ON "signal_radar_analysis_artifacts" USING btree ("job_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_collector_batches_job_idx" ON "signal_radar_collector_batches" USING btree ("job_id");--> statement-breakpoint
CREATE INDEX "signal_radar_collector_items_batch_idx" ON "signal_radar_collector_items" USING btree ("batch_id");--> statement-breakpoint
CREATE INDEX "signal_radar_event_clusters_theme_idx" ON "signal_radar_event_clusters" USING btree ("theme");--> statement-breakpoint
CREATE INDEX "signal_radar_evidence_items_target_idx" ON "signal_radar_evidence_items" USING btree ("target_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_evidence_items_job_idx" ON "signal_radar_evidence_items" USING btree ("job_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_evidence_items_content_hash_idx" ON "signal_radar_evidence_items" USING btree ("content_hash","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_evidence_items_quality_idx" ON "signal_radar_evidence_items" USING btree ("usefulness_status","evidence_kind","source_quality");--> statement-breakpoint
CREATE INDEX "signal_radar_information_units_subject_idx" ON "signal_radar_information_units" USING btree ("subject");--> statement-breakpoint
CREATE INDEX "signal_radar_job_queue_claim_idx" ON "signal_radar_job_queue" USING btree ("queue_name","status","available_at","priority","enqueued_at") WHERE "signal_radar_job_queue"."status" IN ('queued', 'failed');--> statement-breakpoint
CREATE INDEX "signal_radar_jobs_status_created_idx" ON "signal_radar_jobs" USING btree ("status","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_memory_records_collection_idx" ON "signal_radar_memory_records" USING btree ("collection","updated_at");--> statement-breakpoint
CREATE INDEX "signal_radar_memory_updates_job_idx" ON "signal_radar_memory_updates" USING btree ("job_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_memory_versions_memory_idx" ON "signal_radar_memory_versions" USING btree ("memory_id","version_number");--> statement-breakpoint
CREATE INDEX "signal_radar_memory_versions_update_idx" ON "signal_radar_memory_versions" USING btree ("update_id");--> statement-breakpoint
CREATE INDEX "signal_radar_quality_gates_target_idx" ON "signal_radar_quality_gates" USING btree ("target_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_quality_gates_job_idx" ON "signal_radar_quality_gates" USING btree ("job_id","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_quality_gates_status_idx" ON "signal_radar_quality_gates" USING btree ("status","severity","created_at");--> statement-breakpoint
CREATE INDEX "signal_radar_sources_credibility_idx" ON "signal_radar_sources" USING btree ("credibility_tier","updated_at");--> statement-breakpoint
CREATE UNIQUE INDEX "signal_radar_targets_identity_idx" ON "signal_radar_targets" USING btree ("namespace","symbol",COALESCE("exchange", ''));