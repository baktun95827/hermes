import path from "node:path";
import { readdir } from "node:fs/promises";
import { buildArtifactPaths, loadConfig, writeLatestManifest } from "./config";
import { pathExists, readJsonFile, writeJsonAtomic, writeTextAtomic } from "./fs";
import { cleanText } from "./schemas";
import type { AnalysisInputBuildResult, CollectorBatch, JsonValue } from "./types";

export type BuiltAnalysisInputPayload = {
  schema_version: "analysis_input/v1";
  run_id: string;
  generated_at: string;
  collector_batch: CollectorBatch;
  memory_context: Record<string, JsonValue>;
  raw_report: string;
  prompt: string;
  report_title: string;
  report: string;
  item_count: number;
  recommendation_count: number;
  keyword_count: number;
};

export async function buildAnalysisInput(options: {
  configPath: string;
  collectorBatchPath?: string | null;
}): Promise<AnalysisInputBuildResult> {
  const config = await loadConfig(options.configPath);
  const collectorBatchPath = options.collectorBatchPath ?? "";
  if (!collectorBatchPath) throw new Error("collector_batch_path is required");

  const collectorBatch = await readJsonFile<CollectorBatch | null>(collectorBatchPath, null);
  if (!collectorBatch) throw new Error(`collector batch not found: ${collectorBatchPath}`);

  const runId = collectorBatch.collector_run_id;
  const paths = buildArtifactPaths(config.output_dir, runId);
  const memoryContext = await buildMemoryContext(config.memory_dir);
  const built = buildAnalysisInputPayload({
    collectorBatch,
    memoryContext
  });

  const analysisInput = {
    schema_version: "analysis_input/v1",
    run_id: built.run_id,
    generated_at: built.generated_at,
    collector_batch_path: collectorBatchPath,
    collector_batch: collectorBatch,
    memory_context: memoryContext,
    raw_report: built.raw_report,
    prompt_path: paths.prompt,
    report_path: paths.report
  };
  const runMetrics = {
    run_id: runId,
    generated_at: built.generated_at,
    source: collectorBatch.source,
    item_count: collectorBatch.items.length,
    warnings: collectorBatch.warnings,
    analysis_input: {
      path: paths.analysis_input,
      prompt: paths.prompt,
      report: paths.report
    }
  };

  await writeJsonAtomic(paths.analysis_input, analysisInput);
  await writeTextAtomic(paths.prompt, built.prompt);
  await writeTextAtomic(paths.report, built.report);
  await writeJsonAtomic(paths.run_metrics, runMetrics);
  await writeLatestManifest(config.latest_run_file, {
    run_id: runId,
    generated_at: built.generated_at,
    paths: {
      collector_batch: collectorBatchPath,
      analysis_input: paths.analysis_input,
      prompt: paths.prompt,
      report: paths.report,
      run_metrics: paths.run_metrics
    }
  });

  return {
    run_id: runId,
    generated_at: built.generated_at,
    collector_batch_path: collectorBatchPath,
    analysis_input_path: paths.analysis_input,
    prompt_path: paths.prompt,
    report_path: paths.report,
    run_metrics_path: paths.run_metrics,
    item_count: collectorBatch.items.length,
    recommendation_count: 0,
    keyword_count: 0
  };
}

export function buildAnalysisInputPayload(options: {
  collectorBatch: CollectorBatch;
  memoryContext?: Record<string, JsonValue>;
  generatedAt?: string;
}): BuiltAnalysisInputPayload {
  const generatedAt = options.generatedAt ?? new Date().toISOString();
  const memoryContext = options.memoryContext ?? {};
  const rawReport = formatRawReport(options.collectorBatch);
  const reportTitle = reportTitleForCollector(options.collectorBatch, generatedAt);
  const prompt = buildAnalyzerPrompt({
    reportTitle,
    rawReport,
    historyContext: formatHistoryContext(memoryContext),
    collectorBatch: options.collectorBatch
  });
  return {
    schema_version: "analysis_input/v1",
    run_id: options.collectorBatch.collector_run_id,
    generated_at: generatedAt,
    collector_batch: options.collectorBatch,
    memory_context: memoryContext,
    raw_report: rawReport,
    prompt,
    report_title: reportTitle,
    report: `${reportTitle}\n\n${rawReport}`,
    item_count: options.collectorBatch.items.length,
    recommendation_count: 0,
    keyword_count: 0
  };
}

async function buildMemoryContext(memoryDir: string): Promise<Record<string, JsonValue>> {
  return {
    recent_theme_memories: await readCollection(memoryDir, "themes", 12),
    recent_entity_memories: await readCollection(memoryDir, "entities", 12),
    recent_event_memories: await readCollection(memoryDir, "events", 12),
    recent_macro_memories: await readCollection(memoryDir, "macro", 12),
    recent_source_memories: await readCollection(memoryDir, "sources", 12),
    account_notes: await readAccountNotes(memoryDir)
  };
}

async function readCollection(memoryDir: string, collection: string, limit: number): Promise<JsonValue[]> {
  const dir = path.join(memoryDir, collection);
  if (!(await pathExists(dir))) return [];
  const files = (await readdir(dir)).filter((file) => file.endsWith(".json")).sort().slice(-limit);
  const rows: JsonValue[] = [];
  for (const file of files) rows.push(await readJsonFile(path.join(dir, file), {}));
  return rows;
}

async function readAccountNotes(memoryDir: string): Promise<Record<string, JsonValue>> {
  const accounts = await readCollection(memoryDir, "accounts", 50);
  const notes: Record<string, JsonValue> = {};
  for (const account of accounts) {
    if (!account || typeof account !== "object" || Array.isArray(account)) continue;
    const row = account as Record<string, JsonValue>;
    const name = cleanText(row.username ?? row.account ?? row.id);
    const note = cleanText(row.note ?? row.latest_note);
    if (name && note) notes[name] = note;
  }
  return notes;
}

function formatHistoryContext(memoryContext: Record<string, JsonValue>): string {
  const sections: string[] = [];
  for (const key of [
    "recent_theme_memories",
    "recent_entity_memories",
    "recent_event_memories",
    "recent_macro_memories",
    "recent_source_memories"
  ]) {
    const value = memoryContext[key];
    if (Array.isArray(value) && value.length) {
      sections.push(`${key}:\n${JSON.stringify(value.slice(0, 8), null, 2)}`);
    }
  }
  if (memoryContext.account_notes && Object.keys(memoryContext.account_notes as Record<string, JsonValue>).length) {
    sections.push(`account_notes:\n${JSON.stringify(memoryContext.account_notes, null, 2)}`);
  }
  return sections.join("\n\n") || "No prior memory context available.";
}

function formatRawReport(collectorBatch: CollectorBatch): string {
  if (!collectorBatch.items.length) return "本次输入无新材料。";
  return collectorBatch.items
    .map((item) => {
      const lines = [
        reportItemHeading(item.source),
        `来源类型: ${item.source || "unknown"}`,
        item.title ? `标题: ${item.title}` : "",
        `作者/来源: ${item.author.display_name || item.author.entity_id || "unknown"}`,
        item.content_type ? `内容类型: ${item.content_type}` : "",
        item.source_meta.requires_verification ? "验证提示: 用户标记为需要额外验证" : "",
        item.published_at ? `时间: ${item.published_at}` : "",
        item.url ? `链接: ${item.url}` : "",
        "正文:",
        item.text
      ].filter(Boolean);
      return lines.join("\n");
    })
    .join("\n\n");
}

function reportItemHeading(source: string): string {
  if (source === "manual") return "--- MANUAL INPUT ---";
  if (source === "x" || source === "twitter") return "--- X POST ---";
  return source ? `--- ${source.toUpperCase()} ITEM ---` : "--- INPUT ITEM ---";
}

function reportTitleForCollector(collectorBatch: CollectorBatch, generatedAt: string): string {
  if (collectorBatch.source === "manual") return `手动输入研究报告 - ${generatedAt}`;
  if (collectorBatch.source === "x" || collectorBatch.source === "twitter") return `X 监控报告 - ${generatedAt}`;
  return `Signal Radar 研究报告 - ${generatedAt}`;
}

function buildAnalyzerPrompt(options: {
  reportTitle: string;
  rawReport: string;
  historyContext: string;
  collectorBatch: CollectorBatch;
}): string {
  return [
    "你是 Signal Radar analyzer。",
    "任务：阅读本次输入和历史记忆，生成中文研究简报，并在最后输出严格 JSON 的 ### MEMORY_UPDATE。",
    "",
    "要求：",
    "- 不要编辑文件。",
    "- 明确区分未验证、可信、已确认、重复、噪音。",
    "- MEMORY_UPDATE 必须是 JSON object，可以放在 ```json fenced block 中。",
    "- 使用 collector item canonical_id 作为 evidence_item_ids。",
    "- 没有价值的内容使用 memory_action=skip。",
    "",
    `报告标题: ${options.reportTitle}`,
    "",
    "历史记忆：",
    options.historyContext,
    "",
    "本次标准化输入：",
    JSON.stringify(options.collectorBatch, null, 2),
    "",
    "可读材料：",
    options.rawReport
  ].join("\n");
}
