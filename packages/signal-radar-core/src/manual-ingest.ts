import { createHash } from "node:crypto";
import { loadConfig, buildArtifactPaths } from "./config";
import { writeJsonAtomic } from "./fs";
import type { CollectorBatch, CollectorItem } from "./types";

export const MANUAL_SOURCE_ID = "manual";
export const MANUAL_COLLECTOR_TRANSPORT = "manual";
export const MANUAL_COLLECTOR_IMPLEMENTATION = "nextjs_or_cli";

export function utcNowIso(): string {
  return new Date().toISOString();
}

export function timestampSlug(now = new Date()): string {
  return now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "").replace("T", "_");
}

export function stableManualItemId(
  text: string,
  options: { title?: string | null; userLabel?: string | null; inputChannel?: string } = {}
): string {
  const payload = [
    text.trim(),
    options.title ?? "",
    options.userLabel ?? "",
    options.inputChannel ?? "cli"
  ].join("\n");
  return createHash("sha256").update(payload).digest("hex").slice(0, 24);
}

export function buildManualCollectorItem(options: {
  text: string;
  collectedAt: string;
  title?: string | null;
  url?: string | null;
  userLabel?: string | null;
  inputChannel?: string;
  contentType?: string;
  requiresVerification?: boolean;
  itemId?: string | null;
}): CollectorItem {
  const cleanText = options.text.trim();
  if (!cleanText) throw new Error("manual text cannot be empty");

  const inputChannel = options.inputChannel ?? "cli";
  const label = (options.userLabel ?? "user_note").trim() || "user_note";
  const itemId = options.itemId ?? stableManualItemId(cleanText, {
    title: options.title,
    userLabel: label,
    inputChannel
  });

  return {
    schema_version: "collector-item/v1",
    source: MANUAL_SOURCE_ID,
    item_id: itemId,
    canonical_id: `${MANUAL_SOURCE_ID}:${itemId}`,
    content_type: options.contentType ?? "note",
    published_at: options.collectedAt,
    collected_at: options.collectedAt,
    url: options.url ?? null,
    title: options.title ?? null,
    text: cleanText,
    language: null,
    author: {
      source: MANUAL_SOURCE_ID,
      entity_type: "manual_input",
      entity_id: label,
      canonical_entity_id: `${MANUAL_SOURCE_ID}:${label}`,
      display_name: label,
      handle: null,
      url: null
    },
    metrics: {},
    media: [],
    relations: {
      is_repost: false,
      quoted_item_id: null,
      reply_to_item_id: null,
      mentioned_entities: []
    },
    source_meta: {
      input_channel: inputChannel,
      user_label: label,
      requires_verification: Boolean(options.requiresVerification)
    }
  };
}

export function buildManualCollectorBatch(options: {
  text: string;
  runId?: string | null;
  collectedAt?: string | null;
  title?: string | null;
  url?: string | null;
  userLabel?: string | null;
  inputChannel?: string;
  contentType?: string;
  requiresVerification?: boolean;
  configPath?: string | null;
}): CollectorBatch {
  const collectedAt = options.collectedAt ?? utcNowIso();
  const runId = options.runId ?? `manual_${timestampSlug()}`;
  const label = (options.userLabel ?? "user_note").trim() || "user_note";
  const item = buildManualCollectorItem({
    text: options.text,
    collectedAt,
    title: options.title,
    url: options.url,
    userLabel: label,
    inputChannel: options.inputChannel ?? "cli",
    contentType: options.contentType ?? "note",
    requiresVerification: Boolean(options.requiresVerification)
  });

  return {
    schema_version: "collector-batch/v1",
    item_schema_version: "collector-item/v1",
    source: MANUAL_SOURCE_ID,
    collector_run_id: runId,
    collected_at: collectedAt,
    target: {
      kind: "manual_input",
      id: label,
      display_name: label
    },
    collector: {
      transport: MANUAL_COLLECTOR_TRANSPORT,
      implementation: MANUAL_COLLECTOR_IMPLEMENTATION,
      entrypoint: "services/signal-radar-worker/worker.ts ingest-text"
    },
    item_count: 1,
    items: [item],
    warnings: [],
    raw_meta: {
      config_path: options.configPath ?? null,
      input_channel: options.inputChannel ?? "cli",
      requires_verification: Boolean(options.requiresVerification)
    }
  };
}

export async function writeManualCollectorBatch(options: {
  configPath: string;
  text: string;
  runId?: string | null;
  title?: string | null;
  url?: string | null;
  userLabel?: string | null;
  inputChannel?: string;
  contentType?: string;
  requiresVerification?: boolean;
  outputPath?: string | null;
}): Promise<{ batch: CollectorBatch; batchPath: string }> {
  const config = await loadConfig(options.configPath);
  const batch = buildManualCollectorBatch({
    text: options.text,
    runId: options.runId,
    title: options.title,
    url: options.url,
    userLabel: options.userLabel,
    inputChannel: options.inputChannel,
    contentType: options.contentType,
    requiresVerification: options.requiresVerification,
    configPath: config.config_path
  });
  const batchPath = options.outputPath ?? buildArtifactPaths(config.output_dir, batch.collector_run_id).collector_batch;
  await writeJsonAtomic(batchPath, batch);
  return { batch, batchPath };
}
