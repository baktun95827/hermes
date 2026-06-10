export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type SignalRadarConfig = {
  config_path: string;
  base_dir: string;
  accounts: string[];
  tweets_per_account: number;
  auth: { cookies_file?: string };
  discovery: { enabled: boolean; min_interactions: number };
  scroll_count: number;
  delay_between_accounts: number;
  memory_backend: "postgres" | "file";
  state_file: string;
  memory_dir: string;
  output_dir: string;
  latest_run_file: string;
  themes: string[];
  theme_aliases: Record<string, string[]>;
  secondary_theme_aliases: Record<string, Record<string, string[]>>;
};

export type ArtifactPaths = {
  data: string;
  collector_batch: string;
  analysis_input: string;
  prompt: string;
  report: string;
  summary: string;
  memory_update: string;
  run_metrics: string;
  warning: string;
  memory_audit: string;
};

export type CollectorAuthor = {
  source: string;
  entity_type: string;
  entity_id: string;
  canonical_entity_id: string;
  display_name: string;
  handle: string | null;
  url: string | null;
};

export type CollectorItem = {
  schema_version: "collector-item/v1";
  source: string;
  item_id: string;
  canonical_id: string;
  content_type: string;
  published_at: string;
  collected_at: string;
  url: string | null;
  title: string | null;
  text: string;
  language: string | null;
  author: CollectorAuthor;
  metrics: Record<string, JsonValue>;
  media: JsonValue[];
  relations: Record<string, JsonValue>;
  source_meta: Record<string, JsonValue>;
};

export type CollectorBatch = {
  schema_version: "collector-batch/v1";
  item_schema_version: "collector-item/v1";
  source: string;
  collector_run_id: string;
  collected_at: string;
  target: Record<string, JsonValue>;
  collector: Record<string, JsonValue>;
  item_count: number;
  items: CollectorItem[];
  warnings: string[];
  raw_meta: Record<string, JsonValue>;
};

export type MemoryUpdate = {
  primary_themes: string[];
  secondary_themes: Record<string, string[]>;
  account_notes: Record<string, string>;
  information_units: Record<string, JsonValue>[];
  event_clusters: Record<string, JsonValue>[];
  signal_evaluations: Record<string, JsonValue>[];
  entity_updates: Record<string, JsonValue>[];
  event_updates: Record<string, JsonValue>[];
  macro_updates: Record<string, JsonValue>[];
  source_assessments: Record<string, JsonValue>[];
  alert_candidates: Record<string, JsonValue>[];
  contradictions: Record<string, JsonValue>[];
};

export type JobInput = {
  schema_version: "signal-radar-job/v1";
  job_id: string;
  created_at: string;
  kind: "manual_text";
  config_path: string;
  collector_batch_path: string;
  title?: string | null;
  url?: string | null;
  user_label?: string | null;
  target_code?: string | null;
  input_channel: string;
  content_type: string;
  requires_verification: boolean;
};

export type JobStatus = {
  job_id: string;
  status: "created" | "queued" | "running" | "done" | "failed" | "canceled";
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  failed_at?: string;
  updated_at: string;
  provider?: string;
  model?: string;
  error?: string;
  paths?: Record<string, string>;
  memory_update?: Record<string, JsonValue>;
  memory_audit?: Record<string, JsonValue>;
};

export type AnalysisInputBuildResult = {
  run_id: string;
  generated_at: string;
  collector_batch_path: string;
  analysis_input_path: string;
  prompt_path: string;
  report_path: string;
  run_metrics_path: string;
  item_count: number;
  recommendation_count: number;
  keyword_count: number;
};

export type MemoryApplicationResult = {
  update_id: string;
  applied_at: string;
  summary_path: string;
  memory_update_path: string;
  run_metrics_path: string;
  memory_audit_path: string;
  memory_updates: number;
  already_applied: boolean;
};
