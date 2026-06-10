CREATE TABLE IF NOT EXISTS signal_radar_sources (
  source_id text PRIMARY KEY,
  source_type text NOT NULL DEFAULT 'unknown',
  display_name text NOT NULL DEFAULT '',
  canonical_url text,
  credibility_tier text NOT NULL DEFAULT 'unknown'
    CHECK (credibility_tier IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')),
  quality_score numeric(5, 4),
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_evidence_items (
  evidence_id text PRIMARY KEY,
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  collector_item_id text REFERENCES signal_radar_collector_items(canonical_id) ON DELETE SET NULL,
  source_id text REFERENCES signal_radar_sources(source_id) ON DELETE SET NULL,
  content_hash text NOT NULL,
  duplicate_of text REFERENCES signal_radar_evidence_items(evidence_id) ON DELETE SET NULL,
  usefulness_status text NOT NULL DEFAULT 'potential'
    CHECK (usefulness_status IN ('useful', 'potential', 'duplicate', 'low_value', 'rejected')),
  evidence_kind text NOT NULL DEFAULT 'unknown'
    CHECK (evidence_kind IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')),
  source_quality text NOT NULL DEFAULT 'unknown'
    CHECK (source_quality IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')),
  confidence numeric(5, 4),
  filter_reasons text[] NOT NULL DEFAULT '{}',
  url text,
  title text,
  published_at timestamptz,
  collected_at timestamptz NOT NULL,
  text_excerpt text NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_radar_quality_gates (
  gate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id text REFERENCES signal_radar_jobs(job_id) ON DELETE SET NULL,
  target_id uuid REFERENCES signal_radar_targets(target_id) ON DELETE SET NULL,
  update_id text REFERENCES signal_radar_memory_updates(update_id) ON DELETE SET NULL,
  memory_id uuid REFERENCES signal_radar_memory_records(memory_id) ON DELETE SET NULL,
  evidence_id text REFERENCES signal_radar_evidence_items(evidence_id) ON DELETE SET NULL,
  gate_type text NOT NULL,
  subject text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'watch'
    CHECK (status IN ('allow', 'watch', 'skip', 'block', 'needs_agent_recheck')),
  evidence_kind text NOT NULL DEFAULT 'unknown'
    CHECK (evidence_kind IN ('hard_evidence', 'weak_evidence', 'rumor', 'speculation', 'contradiction', 'unknown')),
  evidence_strength text NOT NULL DEFAULT 'unknown',
  verification_status text NOT NULL DEFAULT 'unverified',
  source_quality text NOT NULL DEFAULT 'unknown'
    CHECK (source_quality IN ('official', 'primary', 'reputable', 'secondary', 'social', 'manual', 'promotional', 'unknown')),
  severity text NOT NULL DEFAULT 'info'
    CHECK (severity IN ('info', 'watch', 'warning', 'critical')),
  reason text NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS signal_radar_sources_credibility_idx
  ON signal_radar_sources (credibility_tier, updated_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_evidence_items_target_idx
  ON signal_radar_evidence_items (target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_evidence_items_job_idx
  ON signal_radar_evidence_items (job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_evidence_items_content_hash_idx
  ON signal_radar_evidence_items (content_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_evidence_items_quality_idx
  ON signal_radar_evidence_items (usefulness_status, evidence_kind, source_quality);

CREATE INDEX IF NOT EXISTS signal_radar_quality_gates_target_idx
  ON signal_radar_quality_gates (target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_quality_gates_job_idx
  ON signal_radar_quality_gates (job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_radar_quality_gates_status_idx
  ON signal_radar_quality_gates (status, severity, created_at DESC);

DROP TRIGGER IF EXISTS signal_radar_sources_touch_updated_at ON signal_radar_sources;
CREATE TRIGGER signal_radar_sources_touch_updated_at
BEFORE UPDATE ON signal_radar_sources
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();

DROP TRIGGER IF EXISTS signal_radar_evidence_items_touch_updated_at ON signal_radar_evidence_items;
CREATE TRIGGER signal_radar_evidence_items_touch_updated_at
BEFORE UPDATE ON signal_radar_evidence_items
FOR EACH ROW EXECUTE FUNCTION signal_radar_touch_updated_at();
