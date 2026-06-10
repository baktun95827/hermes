CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS signal_radar_schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_targets (
  target_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  namespace text NOT NULL DEFAULT 'public_market',
  symbol text NOT NULL,
  exchange text,
  display_name text NOT NULL,
  asset_type text NOT NULL DEFAULT 'equity',
  country text,
  status text NOT NULL DEFAULT 'active',
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_jobs (
  job_id text PRIMARY KEY,
  schema_version text NOT NULL DEFAULT 'signal-radar-job/v1',
  kind text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed', 'canceled')),
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  title text,
  url text,
  user_label text,
  input_channel text NOT NULL DEFAULT 'web',
  content_type text NOT NULL DEFAULT 'note',
  requires_verification boolean NOT NULL DEFAULT false,
  provider text,
  model text,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  queued_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  failed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (job_id ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$')
);

CREATE TABLE IF NOT EXISTS signal_radar_job_queue (
  queue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text NOT NULL REFERENCES signal_radar_jobs(job_id) ON DELETE CASCADE,
  queue_name text NOT NULL DEFAULT 'analysis',
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'claimed', 'done', 'failed', 'dead', 'canceled')),
  priority integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  locked_by text,
  locked_until timestamptz,
  last_error text,
  enqueued_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, queue_name)
);

CREATE TABLE IF NOT EXISTS signal_radar_collector_batches (
  batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text NOT NULL REFERENCES signal_radar_jobs(job_id) ON DELETE CASCADE,
  schema_version text NOT NULL,
  item_schema_version text NOT NULL,
  source text NOT NULL,
  collector_run_id text NOT NULL,
  collected_at timestamptz NOT NULL,
  target jsonb NOT NULL DEFAULT '{}'::jsonb,
  collector jsonb NOT NULL DEFAULT '{}'::jsonb,
  item_count integer NOT NULL DEFAULT 0,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  raw_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (collector_run_id)
);

CREATE TABLE IF NOT EXISTS signal_radar_collector_items (
  canonical_id text PRIMARY KEY,
  batch_id uuid NOT NULL REFERENCES signal_radar_collector_batches(batch_id) ON DELETE CASCADE,
  source text NOT NULL,
  item_id text NOT NULL,
  content_type text NOT NULL,
  published_at timestamptz,
  collected_at timestamptz NOT NULL,
  url text,
  title text,
  text text NOT NULL,
  language text,
  author jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  media jsonb NOT NULL DEFAULT '[]'::jsonb,
  relations jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_analysis_artifacts (
  artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text NOT NULL REFERENCES signal_radar_jobs(job_id) ON DELETE CASCADE,
  provider text NOT NULL,
  model text NOT NULL,
  run_id text NOT NULL,
  status text NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'running', 'done', 'failed')),
  analysis_input jsonb NOT NULL DEFAULT '{}'::jsonb,
  memory_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_report text NOT NULL DEFAULT '',
  prompt text NOT NULL DEFAULT '',
  report text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  run_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  generated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_provider_runs (
  provider_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text NOT NULL REFERENCES signal_radar_jobs(job_id) ON DELETE CASCADE,
  artifact_id uuid REFERENCES signal_radar_analysis_artifacts(artifact_id) ON DELETE SET NULL,
  provider text NOT NULL,
  model text NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
  prompt_hash text,
  output_hash text,
  input_tokens integer,
  output_tokens integer,
  cost_usd numeric(12, 6),
  error text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  raw_meta jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS signal_radar_job_logs (
  log_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text NOT NULL REFERENCES signal_radar_jobs(job_id) ON DELETE CASCADE,
  action text NOT NULL,
  level text NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warn', 'error')),
  message text NOT NULL DEFAULT '',
  stdout text NOT NULL DEFAULT '',
  stderr text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_memory_updates (
  update_id text PRIMARY KEY,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  artifact_id uuid REFERENCES signal_radar_analysis_artifacts(artifact_id) ON DELETE SET NULL,
  provider_run_id uuid REFERENCES signal_radar_provider_runs(provider_run_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  run_id text,
  status text NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'failed', 'skipped')),
  summary_hash text NOT NULL,
  parsed jsonb NOT NULL DEFAULT '{}'::jsonb,
  information_unit_count integer NOT NULL DEFAULT 0,
  event_cluster_count integer NOT NULL DEFAULT 0,
  entity_updates_applied integer NOT NULL DEFAULT 0,
  event_updates_applied integer NOT NULL DEFAULT 0,
  macro_updates_applied integer NOT NULL DEFAULT 0,
  source_updates_applied integer NOT NULL DEFAULT 0,
  memory_versions_created integer NOT NULL DEFAULT 0,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  applied_at timestamptz
);

CREATE TABLE IF NOT EXISTS signal_radar_memory_records (
  memory_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  collection text NOT NULL,
  record_key text NOT NULL,
  title text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  current_version integer NOT NULL DEFAULT 0,
  last_update_id text REFERENCES signal_radar_memory_updates(update_id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (target_id, collection, record_key),
  UNIQUE (collection, record_key)
);

CREATE TABLE IF NOT EXISTS signal_radar_memory_versions (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  memory_id uuid NOT NULL REFERENCES signal_radar_memory_records(memory_id) ON DELETE CASCADE,
  version_number integer NOT NULL,
  update_id text NOT NULL REFERENCES signal_radar_memory_updates(update_id) ON DELETE CASCADE,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  artifact_id uuid REFERENCES signal_radar_analysis_artifacts(artifact_id) ON DELETE SET NULL,
  provider_run_id uuid REFERENCES signal_radar_provider_runs(provider_run_id) ON DELETE SET NULL,
  operation text NOT NULL CHECK (operation IN ('create', 'update', 'delete', 'noop')),
  before_payload jsonb,
  after_payload jsonb,
  diff jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (memory_id, version_number)
);

CREATE TABLE IF NOT EXISTS signal_radar_memory_audit_events (
  audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  update_id text REFERENCES signal_radar_memory_updates(update_id) ON DELETE CASCADE,
  memory_id uuid REFERENCES signal_radar_memory_records(memory_id) ON DELETE SET NULL,
  version_id uuid REFERENCES signal_radar_memory_versions(version_id) ON DELETE SET NULL,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  event_type text NOT NULL,
  severity text NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'warn', 'error')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_information_units (
  information_unit_id text PRIMARY KEY,
  update_id text NOT NULL REFERENCES signal_radar_memory_updates(update_id) ON DELETE CASCADE,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  subject text NOT NULL DEFAULT '',
  claim text NOT NULL DEFAULT '',
  verification_status text,
  signal_type text,
  novelty_level text,
  evidence_strength text,
  memory_action text,
  alert_level text,
  confidence numeric(5, 4),
  evidence_item_ids text[] NOT NULL DEFAULT '{}',
  source_ids text[] NOT NULL DEFAULT '{}',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_event_clusters (
  cluster_id text PRIMARY KEY,
  update_id text NOT NULL REFERENCES signal_radar_memory_updates(update_id) ON DELETE CASCADE,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  title text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  theme text,
  signal_type text,
  novelty_level text,
  evidence_strength text,
  memory_action text,
  alert_level text,
  confidence numeric(5, 4),
  evidence_item_ids text[] NOT NULL DEFAULT '{}',
  source_ids text[] NOT NULL DEFAULT '{}',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_alert_candidates (
  alert_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  update_id text NOT NULL REFERENCES signal_radar_memory_updates(update_id) ON DELETE CASCADE,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  subject text NOT NULL DEFAULT '',
  alert_level text,
  confidence numeric(5, 4),
  evidence_item_ids text[] NOT NULL DEFAULT '{}',
  source_ids text[] NOT NULL DEFAULT '{}',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS signal_radar_jobs_status_created_idx ON signal_radar_jobs (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS signal_radar_targets_identity_idx
  ON signal_radar_targets (namespace, symbol, COALESCE(exchange, ''));
CREATE INDEX IF NOT EXISTS signal_radar_job_queue_claim_idx
  ON signal_radar_job_queue (queue_name, status, available_at, priority DESC, enqueued_at)
  WHERE status IN ('queued', 'failed');
CREATE INDEX IF NOT EXISTS signal_radar_collector_batches_job_idx ON signal_radar_collector_batches (job_id);
CREATE INDEX IF NOT EXISTS signal_radar_collector_items_batch_idx ON signal_radar_collector_items (batch_id);
CREATE INDEX IF NOT EXISTS signal_radar_analysis_artifacts_job_idx ON signal_radar_analysis_artifacts (job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS signal_radar_memory_updates_job_idx ON signal_radar_memory_updates (job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS signal_radar_memory_records_collection_idx ON signal_radar_memory_records (collection, updated_at DESC);
CREATE INDEX IF NOT EXISTS signal_radar_memory_versions_memory_idx ON signal_radar_memory_versions (memory_id, version_number DESC);
CREATE INDEX IF NOT EXISTS signal_radar_memory_versions_update_idx ON signal_radar_memory_versions (update_id);
CREATE INDEX IF NOT EXISTS signal_radar_information_units_subject_idx ON signal_radar_information_units (subject);
CREATE INDEX IF NOT EXISTS signal_radar_event_clusters_theme_idx ON signal_radar_event_clusters (theme);

CREATE OR REPLACE FUNCTION signal_radar_touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS signal_radar_targets_touch_updated_at ON signal_radar_targets;
CREATE TRIGGER signal_radar_targets_touch_updated_at
BEFORE UPDATE ON signal_radar_targets
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();

DROP TRIGGER IF EXISTS signal_radar_jobs_touch_updated_at ON signal_radar_jobs;
CREATE TRIGGER signal_radar_jobs_touch_updated_at
BEFORE UPDATE ON signal_radar_jobs
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();

DROP TRIGGER IF EXISTS signal_radar_job_queue_touch_updated_at ON signal_radar_job_queue;
CREATE TRIGGER signal_radar_job_queue_touch_updated_at
BEFORE UPDATE ON signal_radar_job_queue
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();

DROP TRIGGER IF EXISTS signal_radar_analysis_artifacts_touch_updated_at ON signal_radar_analysis_artifacts;
CREATE TRIGGER signal_radar_analysis_artifacts_touch_updated_at
BEFORE UPDATE ON signal_radar_analysis_artifacts
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();

DROP TRIGGER IF EXISTS signal_radar_memory_records_touch_updated_at ON signal_radar_memory_records;
CREATE TRIGGER signal_radar_memory_records_touch_updated_at
BEFORE UPDATE ON signal_radar_memory_records
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();
