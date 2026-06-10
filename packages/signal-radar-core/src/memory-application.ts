import path from "node:path";
import { readFile } from "node:fs/promises";
import { buildArtifactPaths, loadConfig, writeLatestManifest } from "./config";
import { pathExists, readJsonFile, writeJsonAtomic } from "./fs";
import { buildMemoryUpdateId, hasParseableMemoryUpdate, parseMemoryUpdate } from "./memory-update";
import { cleanText, safeFilename } from "./schemas";
import type { JsonValue, MemoryApplicationResult, MemoryUpdate } from "./types";

export async function applyMemoryUpdate(options: {
  configPath: string;
  summaryPath: string;
}): Promise<MemoryApplicationResult> {
  const config = await loadConfig(options.configPath);
  if (!(await pathExists(options.summaryPath))) {
    throw new Error(`summary file not found: ${options.summaryPath}`);
  }
  const summaryText = await readFile(options.summaryPath, "utf8");
  const parsed = parseMemoryUpdate(summaryText);
  if (!hasParseableMemoryUpdate(parsed)) throw new Error("no parseable MEMORY_UPDATE found in summary");

  const latest = await readJsonFile<Record<string, JsonValue>>(config.latest_run_file, {});
  const runId = cleanText(latest.run_id) || inferRunId(options.summaryPath);
  const paths = buildArtifactPaths(config.output_dir, runId);
  const updateId = buildMemoryUpdateId({
    summaryText,
    summaryPath: options.summaryPath,
    runId
  });
  const appliedAt = new Date().toISOString();
  const changedFiles: { path: string; action: string }[] = [];
  const alreadyApplied = false;

  await applyMemoryCollections({
    memoryDir: config.memory_dir,
    parsed,
    updateId,
    appliedAt,
    changedFiles
  });

  const memoryUpdatePayload: Record<string, JsonValue> = {
    update_id: updateId,
    applied_at: appliedAt,
    already_applied: alreadyApplied,
    information_unit_count: parsed.information_units.length,
    event_cluster_count: parsed.event_clusters.length,
    entity_updates_applied: parsed.entity_updates.length,
    event_updates_applied: parsed.event_updates.length,
    macro_updates_applied: parsed.macro_updates.length,
    source_updates_applied: parsed.source_assessments.length,
    source_observation_updates_applied: collectSourceIds(parsed).length,
    memory_audit: paths.memory_audit,
    parsed: parsed as unknown as JsonValue
  };
  const auditPayload: Record<string, JsonValue> = {
    schema_version: "memory-audit/v1",
    update_id: updateId,
    status: "applied",
    applied_at: appliedAt,
    summary_path: options.summaryPath,
    memory_update_path: paths.memory_update,
    changed_file_count: changedFiles.length,
    changed_files: changedFiles as unknown as JsonValue
  };
  const previousRunMetrics = await readJsonFile<Record<string, JsonValue>>(paths.run_metrics, {});
  const runMetrics = {
    ...previousRunMetrics,
    memory: {
      update_id: updateId,
      applied_at: appliedAt,
      memory_updates: changedFiles.length,
      memory_update: paths.memory_update,
      memory_audit: paths.memory_audit,
      already_applied: alreadyApplied
    }
  };

  await writeJsonAtomic(paths.memory_update, memoryUpdatePayload);
  await writeJsonAtomic(paths.memory_audit, auditPayload);
  await writeJsonAtomic(paths.run_metrics, runMetrics as Record<string, JsonValue>);
  await writeLatestManifest(config.latest_run_file, {
    ...latest,
    run_id: runId,
    updated_at: appliedAt,
    paths: {
      ...((latest.paths as Record<string, JsonValue> | undefined) ?? {}),
      summary: options.summaryPath,
      memory_update: paths.memory_update,
      memory_audit: paths.memory_audit,
      run_metrics: paths.run_metrics
    }
  });

  return {
    update_id: updateId,
    applied_at: appliedAt,
    summary_path: options.summaryPath,
    memory_update_path: paths.memory_update,
    run_metrics_path: paths.run_metrics,
    memory_audit_path: paths.memory_audit,
    memory_updates: changedFiles.length,
    already_applied: alreadyApplied
  };
}

async function applyMemoryCollections(options: {
  memoryDir: string;
  parsed: MemoryUpdate;
  updateId: string;
  appliedAt: string;
  changedFiles: { path: string; action: string }[];
}): Promise<void> {
  for (const primaryTheme of options.parsed.primary_themes) {
    const filePath = path.join(options.memoryDir, "themes", `${safeFilename(primaryTheme)}.json`);
    const previous = await readJsonFile<Record<string, JsonValue>>(filePath, {});
    await upsertMemoryFile(filePath, {
      ...previous,
      primary_theme: primaryTheme,
      latest_secondary_themes: options.parsed.secondary_themes[primaryTheme] ?? [],
      run_count: Number(previous.run_count ?? 0) + 1,
      updated_at: options.appliedAt,
      update_id: options.updateId
    }, options.changedFiles);
  }

  for (const [username, note] of Object.entries(options.parsed.account_notes)) {
    await upsertMemoryFile(
      path.join(options.memoryDir, "accounts", `${safeFilename(username)}.json`),
      { username, note, updated_at: options.appliedAt, update_id: options.updateId },
      options.changedFiles
    );
  }

  await writeUpdateCollection(options.memoryDir, "entities", options.parsed.entity_updates, "entity_id", options);
  await writeUpdateCollection(options.memoryDir, "events", options.parsed.event_updates, "event_id", options);
  await writeUpdateCollection(options.memoryDir, "macro", options.parsed.macro_updates, "macro_id", options);
  await writeUpdateCollection(options.memoryDir, "sources", options.parsed.source_assessments, "source_id", options);
  await writeUpdateCollection(options.memoryDir, "contradictions", options.parsed.contradictions, "contradiction_id", options);

  for (const sourceId of collectSourceIds(options.parsed)) {
    const filePath = path.join(options.memoryDir, "sources", `${safeFilename(sourceId)}.json`);
    const previous = await readJsonFile<Record<string, JsonValue>>(filePath, {});
    await upsertMemoryFile(filePath, {
      ...previous,
      source_id: sourceId,
      observed_count: Number(previous.observed_count ?? 0) + 1,
      latest_observed_at: options.appliedAt,
      update_id: options.updateId
    }, options.changedFiles);
  }

  await upsertMemoryFile(
    path.join(options.memoryDir, "index.json"),
    {
      schema_version: "signal-radar-memory-index/v1",
      updated_at: options.appliedAt,
      update_id: options.updateId,
      collections: ["themes", "accounts", "entities", "events", "macro", "sources", "contradictions"]
    },
    options.changedFiles
  );
}

async function writeUpdateCollection(
  memoryDir: string,
  collection: string,
  updates: Record<string, JsonValue>[],
  idField: string,
  options: { updateId: string; appliedAt: string; changedFiles: { path: string; action: string }[] }
): Promise<void> {
  for (const update of updates) {
    const id = cleanText(update[idField] ?? update.id ?? update.title ?? update.subject ?? update.claim) || `${collection}_${safeFilename(options.updateId)}`;
    await upsertMemoryFile(
      path.join(memoryDir, collection, `${safeFilename(id)}.json`),
      {
        ...update,
        [idField]: id,
        updated_at: options.appliedAt,
        update_id: options.updateId
      },
      options.changedFiles
    );
  }
}

async function upsertMemoryFile(
  filePath: string,
  payload: Record<string, JsonValue>,
  changedFiles: { path: string; action: string }[]
): Promise<void> {
  const existed = await pathExists(filePath);
  const previous = existed ? JSON.stringify(await readJsonFile(filePath, {}), null, 2) : "";
  const next = JSON.stringify(payload, null, 2);
  if (previous === next) return;
  await writeJsonAtomic(filePath, payload);
  changedFiles.push({ path: filePath, action: existed ? "update" : "create" });
}

function collectSourceIds(parsed: MemoryUpdate): string[] {
  const ids = new Set<string>();
  for (const item of [
    ...parsed.information_units,
    ...parsed.event_clusters,
    ...parsed.signal_evaluations,
    ...parsed.entity_updates,
    ...parsed.event_updates,
    ...parsed.macro_updates,
    ...parsed.contradictions
  ]) {
    const sourceIds = item.source_ids;
    if (Array.isArray(sourceIds)) {
      for (const sourceId of sourceIds) {
        const normalized = cleanText(sourceId);
        if (normalized) ids.add(normalized);
      }
    }
  }
  return [...ids];
}

function inferRunId(summaryPath: string): string {
  const match = path.basename(summaryPath).match(/summary_(.+?)\.txt$/);
  return match?.[1] ?? `manual_${Date.now()}`;
}
