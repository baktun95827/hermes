import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import os from "node:os";
import {
  appendPostgresJobLog,
  applyMemoryUpdateToPostgres,
  buildArtifactPaths,
  buildAnalysisInputPayload,
  claimNextPostgresJob,
  completePostgresJob,
  DEFAULT_CONFIG_PATH,
  DEFAULT_JOBS_DIR,
  enqueueManualTextJob,
  failPostgresJob,
  insertPostgresAnalysisArtifact,
  loadPostgresJobForRun,
  loadPostgresMemoryContext,
  loadConfig,
  readJsonFile,
  readTextIfExists,
  timestampSlug,
  updatePostgresAnalysisSummary,
  writeJsonAtomic,
  writeManualCollectorBatch,
  writeTextAtomic,
  buildAnalysisInputPipeline,
  applyMemoryPipeline,
  PipelineError,
  type CollectorBatch,
  type JobInput,
  type JobStatus,
  type JsonValue
} from "../../packages/signal-radar-core/src";

export const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/;

export function utcNowIso(): string {
  return new Date().toISOString();
}

export function uniqueManualJobId(): string {
  return `manual_${timestampSlug()}_${randomUUID().replace(/-/g, "").slice(0, 10)}`;
}

export function validateJobId(jobId: string): string {
  const normalized = String(jobId ?? "").trim();
  if (!JOB_ID_PATTERN.test(normalized)) throw new Error(`invalid job_id: ${jobId}`);
  return normalized;
}

export function resolveJobDir(jobsDir: string, jobId: string): string {
  const safeJobId = validateJobId(jobId);
  const root = path.resolve(expandHome(jobsDir));
  const candidate = path.resolve(root, safeJobId);
  const relative = path.relative(root, candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative) || path.dirname(candidate) !== root) {
    throw new Error(`job_id escapes jobs directory: ${jobId}`);
  }
  return candidate;
}

export async function createManualJob(options: {
  text: string;
  configPath?: string;
  jobsDir?: string;
  title?: string | null;
  url?: string | null;
  userLabel?: string | null;
  targetCode?: string | null;
  inputChannel?: string;
  contentType?: string;
  requiresVerification?: boolean;
}): Promise<string> {
  const text = options.text.trim();
  if (!text) throw new Error("text is required");
  const configPath = options.configPath ?? process.env.XRADAR_CONFIG ?? DEFAULT_CONFIG_PATH;
  const jobsDir = options.jobsDir ?? process.env.XRADAR_JOBS_DIR ?? DEFAULT_JOBS_DIR;
  const root = path.resolve(expandHome(jobsDir));
  await mkdir(root, { recursive: true });

  let jobDir = "";
  let jobId = "";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    jobId = uniqueManualJobId();
    jobDir = resolveJobDir(root, jobId);
    try {
      await mkdir(jobDir, { recursive: false });
      break;
    } catch {
      jobDir = "";
    }
  }
  if (!jobDir) throw new Error("failed to allocate a unique manual job_id");

  const { batch, batchPath } = await writeManualCollectorBatch({
    configPath,
    text,
    runId: jobId,
    title: options.title,
    url: options.url,
    userLabel: options.userLabel,
    targetCode: options.targetCode,
    inputChannel: options.inputChannel ?? "cli",
    contentType: options.contentType ?? "note",
    requiresVerification: Boolean(options.requiresVerification)
  });
  await writeJsonAtomic(path.join(jobDir, "collector_batch.json"), batch as unknown as JsonValue);

  const input: JobInput = {
    schema_version: "signal-radar-job/v1",
    job_id: jobId,
    created_at: utcNowIso(),
    kind: "manual_text",
    config_path: path.resolve(expandHome(configPath)),
    collector_batch_path: batchPath,
      title: options.title ?? null,
      url: options.url ?? null,
      user_label: options.userLabel ?? null,
      target_code: options.targetCode ?? null,
      input_channel: options.inputChannel ?? "cli",
      content_type: options.contentType ?? "note",
    requires_verification: Boolean(options.requiresVerification)
  };
  await writeJsonAtomic(path.join(jobDir, "input.json"), input as unknown as JsonValue);
  await writeStatus(jobDir, {
    job_id: jobId,
    status: "created",
    created_at: input.created_at,
    updated_at: utcNowIso(),
    paths: {
      job_dir: jobDir,
      collector_batch: batchPath
    }
  });
  return jobDir;
}

export async function runJob(options: {
  jobDir: string;
  providerName?: string;
  model?: string;
  applyMemory?: boolean;
}): Promise<JobStatus> {
  const jobDir = path.resolve(expandHome(options.jobDir));
  const input = await readJsonFile<JobInput | null>(path.join(jobDir, "input.json"), null);
  if (!input) throw new Error(`job input not found: ${path.join(jobDir, "input.json")}`);
  const provider = getProvider(options.providerName ?? process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture");
  const model = options.model ?? process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4";
  const startedAt = utcNowIso();
  await writeStatus(jobDir, {
    ...(await readStatus(jobDir)),
    job_id: input.job_id,
    status: "running",
    started_at: startedAt,
    updated_at: utcNowIso()
  });

  try {
    const config = await loadConfig(input.config_path);
    const paths = buildArtifactPaths(config.output_dir, input.job_id);
    const collectorBatch = await readJsonFile<CollectorBatch | null>(input.collector_batch_path, null);
    if (!collectorBatch) throw new Error(`collector batch not found: ${input.collector_batch_path}`);

    const buildResult = await buildAnalysisInputPipeline({
      configPath: input.config_path,
      collectorBatchPath: input.collector_batch_path
    });
    await logPipelineResult(jobDir, "build-analysis-input", buildResult.stdout, buildResult.stderr);

    const summaryPath = path.join(jobDir, "summary.txt");
    await provider.generate({
      promptPath: paths.prompt,
      outputPath: summaryPath,
      jobDir,
      jobInput: input,
      collectorBatch,
      model
    });

    if (options.applyMemory ?? true) {
      const applyResult = await applyMemoryPipeline({
        configPath: input.config_path,
        summaryPath
      });
      await logPipelineResult(jobDir, "apply-memory", applyResult.stdout, applyResult.stderr);
    }

    const { memoryUpdateStatus, memoryAuditStatus, finalMemoryPaths } = await memoryStatusFromArtifacts(paths);
    const finalStatus: JobStatus = {
      job_id: input.job_id,
      status: "done",
      created_at: input.created_at,
      started_at: startedAt,
      finished_at: utcNowIso(),
      updated_at: utcNowIso(),
      provider: provider.name,
      model,
      paths: {
        job_dir: jobDir,
        collector_batch: input.collector_batch_path,
        analysis_input: paths.analysis_input,
        prompt: paths.prompt,
        report: paths.report,
        summary: summaryPath,
        worker_log: path.join(jobDir, "worker.log"),
        ...finalMemoryPaths
      },
      memory_update: memoryUpdateStatus,
      memory_audit: memoryAuditStatus
    };
    await writeStatus(jobDir, finalStatus);
    return finalStatus;
  } catch (error) {
    if (error instanceof PipelineError) {
      await logPipelineResult(jobDir, "failed", error.result.stdout, error.result.stderr);
    }
    const failedStatus: JobStatus = {
      ...(await readStatus(jobDir)),
      job_id: input.job_id,
      status: "failed",
      failed_at: utcNowIso(),
      updated_at: utcNowIso(),
      error: error instanceof Error ? error.message : String(error)
    };
    await appendLog(jobDir, `ERROR: ${failedStatus.error}`);
    await writeStatus(jobDir, failedStatus);
    return failedStatus;
  }
}

export async function getJobPayload(jobId: string, jobsDir = process.env.XRADAR_JOBS_DIR ?? DEFAULT_JOBS_DIR): Promise<Record<string, JsonValue> | null> {
  const jobDir = resolveJobDir(jobsDir, jobId);
  const status = await readJsonFile<JobStatus | null>(path.join(jobDir, "status.json"), null);
  if (!status) return null;
  const paths = status.paths ?? {};
  const summary = await readTextIfExists(paths.summary ?? path.join(jobDir, "summary.txt"));
  const logTail = (await readTextIfExists(paths.worker_log ?? path.join(jobDir, "worker.log"))).slice(-8000);
  const memoryUpdate = paths.memory_update ? await readJsonFile<Record<string, JsonValue>>(paths.memory_update, {}) : {};
  const memoryAuditPath = paths.memory_audit ?? String(memoryUpdate.memory_audit ?? "");
  const memoryAudit = memoryAuditPath ? await readJsonFile<Record<string, JsonValue>>(memoryAuditPath, {}) : {};
  return {
    job_id: jobId,
    status: status as unknown as JsonValue,
    summary,
    memory_update: memoryUpdate as unknown as JsonValue,
    memory_audit: {
      path: memoryAuditPath,
      exists: Boolean(memoryAuditPath && Object.keys(memoryAudit).length),
      ...memoryAudit
    } as unknown as JsonValue,
    log_tail: logTail
  };
}

export async function runNextPostgresJob(options: {
  queueName?: string;
  workerId?: string;
  providerName?: string;
  model?: string;
} = {}): Promise<JobStatus | null> {
  const claimed = await claimNextPostgresJob({
    queueName: options.queueName ?? "analysis",
    workerId: options.workerId ?? `worker:${process.pid}`
  });
  if (!claimed) return null;
  return runPostgresJob({
    jobId: claimed.job_id,
    providerName: options.providerName,
    model: options.model
  });
}

export async function runPostgresWorkerLoop(options: {
  queueName?: string;
  workerId?: string;
  providerName?: string;
  model?: string;
  pollMs?: number;
  batchLimit?: number;
} = {}): Promise<void> {
  const pollMs = Math.max(250, options.pollMs ?? Number(process.env.XRADAR_WORKER_POLL_MS ?? 1500));
  const batchLimit = options.batchLimit ?? Number(process.env.XRADAR_WORKER_BATCH_LIMIT ?? 0);
  const workerId = options.workerId ?? `worker:${process.pid}`;
  let processed = 0;
  let shouldStop = false;
  const stop = () => {
    shouldStop = true;
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);

  while (!shouldStop) {
    const status = await runNextPostgresJob({
      queueName: options.queueName,
      workerId,
      providerName: options.providerName,
      model: options.model
    });
    if (status) {
      processed += 1;
      process.stdout.write(`${JSON.stringify({ worker_id: workerId, processed, job_id: status.job_id, status: status.status })}\n`);
      if (batchLimit > 0 && processed >= batchLimit) return;
      continue;
    }
    if (batchLimit > 0) return;
    await sleep(pollMs);
  }
}

export async function runPostgresJob(options: {
  jobId: string;
  providerName?: string;
  model?: string;
}): Promise<JobStatus> {
  let artifactId = "";
  let tempDir = "";
  const startedAt = utcNowIso();
  try {
    const job = await loadPostgresJobForRun(options.jobId);
    if (!job) throw new Error(`job not found: ${options.jobId}`);

    const provider = getProvider(options.providerName ?? job.provider ?? process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture");
    const model = options.model ?? job.model ?? process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4";
    const memoryContext = await loadPostgresMemoryContext();
    const built = buildAnalysisInputPayload({
      collectorBatch: job.collector_batch,
      memoryContext
    });
    artifactId = await insertPostgresAnalysisArtifact({
      jobId: job.job_id,
      provider: provider.name,
      model,
      runId: built.run_id,
      status: "running",
      analysisInput: {
        schema_version: built.schema_version,
        run_id: built.run_id,
        generated_at: built.generated_at,
        collector_batch: built.collector_batch
      } as Record<string, JsonValue>,
      memoryContext,
      rawReport: built.raw_report,
      prompt: built.prompt,
      report: built.report,
      runMetrics: {
        item_count: built.item_count,
        recommendation_count: built.recommendation_count,
        keyword_count: built.keyword_count
      },
      generatedAt: built.generated_at
    });

    tempDir = await mkdtemp(path.join(os.tmpdir(), "signal-radar-db-job-"));
    const promptPath = path.join(tempDir, "prompt.txt");
    const summaryPath = path.join(tempDir, "summary.txt");
    await writeTextAtomic(promptPath, built.prompt);
    await provider.generate({
      promptPath,
      outputPath: summaryPath,
      jobDir: tempDir,
      jobInput: {
        schema_version: "signal-radar-job/v1",
        job_id: job.job_id,
        created_at: startedAt,
        kind: "manual_text",
        config_path: "postgres",
        collector_batch_path: `postgres://signal_radar_collector_batches/${built.run_id}`,
        title: null,
        url: null,
        user_label: null,
        input_channel: "worker",
        content_type: "note",
        requires_verification: false
      },
      collectorBatch: job.collector_batch,
      model
    });

    const summary = await readTextIfExists(summaryPath);
    await updatePostgresAnalysisSummary(artifactId, summary, "done");
    const memoryResult = await applyMemoryUpdateToPostgres({
      jobId: job.job_id,
      artifactId,
      targetId: job.target_id,
      runId: built.run_id,
      summaryText: summary,
      summaryPath: `postgres://signal_radar_analysis_artifacts/${artifactId}/summary`
    });
    const workerLog = await readTextIfExists(path.join(tempDir, "worker.log"));
    if (workerLog) {
      await appendPostgresJobLog(job.job_id, {
        action: "provider.log",
        stdout: workerLog
      });
    }
    await completePostgresJob(job.job_id, {
      artifact_id: artifactId,
      update_id: memoryResult.update_id,
      memory_versions_created: memoryResult.memory_updates
    });
    return {
      job_id: job.job_id,
      status: "done",
      started_at: startedAt,
      finished_at: utcNowIso(),
      updated_at: utcNowIso(),
      provider: provider.name,
      model,
      memory_update: {
        update_id: memoryResult.update_id,
        memory_versions_created: memoryResult.memory_updates
      }
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (artifactId) await updatePostgresAnalysisSummary(artifactId, "", "failed");
    await failPostgresJob(options.jobId, message);
    return {
      job_id: options.jobId,
      status: "failed",
      started_at: startedAt,
      failed_at: utcNowIso(),
      updated_at: utcNowIso(),
      error: message
    };
  } finally {
    if (tempDir) await rm(tempDir, { recursive: true, force: true });
  }
}

type ProviderGenerateOptions = {
  promptPath: string;
  outputPath: string;
  jobDir: string;
  jobInput: JobInput;
  collectorBatch: CollectorBatch;
  model: string;
};

type AnalyzerProvider = {
  name: string;
  generate(options: ProviderGenerateOptions): Promise<void>;
};

class FixtureProvider implements AnalyzerProvider {
  name = "fixture";

  async generate(options: ProviderGenerateOptions): Promise<void> {
    const item = options.collectorBatch.items[0];
    const canonicalId = item?.canonical_id ?? "manual:unknown";
    const sourceId = item?.author?.canonical_entity_id ?? "manual:user_note";
    const text = item?.text?.trim() ?? "";
    const preview = text.length > 240 ? `${text.slice(0, 240)}...` : text;
    const memoryUpdate = {
      primary_themes: [],
      secondary_themes: {},
      account_notes: {},
      information_units: [
        {
          event_type: "other",
          relation_to_memory: "new_event",
          subject: item?.title || "手动输入材料",
          claim: preview || "手动输入材料需要进一步分析。",
          what_changed: "fixture provider 仅用于链路验证，不做真实研究判断。",
          risk_reason: "fixture provider 不做真实研究判断，不能作为事实写入。",
          memory_action_reason: "链路验证输出默认跳过记忆写入。",
          changed_dimensions: ["other"],
          affected_entities: [],
          affected_themes: ["手动输入"],
          market_mechanism: "fixture provider 不判断市场机制。",
          time_horizon: "unknown",
          verification_status: "unverified",
          signal_type: "unknown",
          novelty_level: "low",
          evidence_strength: "weak",
          memory_action: "skip",
          alert_level: "none",
          confidence: 0,
          evidence_item_ids: [canonicalId],
          source_ids: [sourceId]
        }
      ],
      event_clusters: [],
      signal_evaluations: [],
      entity_updates: [],
      event_updates: [],
      macro_updates: [],
      source_assessments: [],
      alert_candidates: [],
      contradictions: []
    };
    const summary = [
      "手动输入链路 smoke summary。",
      "",
      "这份输出来自 fixture provider，只用于验证 Next.js API、worker、collector_batch、analysis_input 和 apply-memory 链路。",
      "",
      "### MEMORY_UPDATE",
      "```json",
      JSON.stringify(memoryUpdate, null, 2),
      "```",
      ""
    ].join("\n");
    await writeTextAtomic(options.outputPath, summary);
  }
}

class CodexCliProvider implements AnalyzerProvider {
  name = "codex-cli";

  async generate(options: ProviderGenerateOptions): Promise<void> {
    const prompt = await readFile(options.promptPath, "utf8");
    const instruction = [
      "You are the Signal Radar analyzer. Do not edit files.",
      "Read the prompt below and return only the final Chinese brief followed by a strict `### MEMORY_UPDATE` JSON block.",
      ""
    ].join("\n");
    const codexBin = process.env.XRADAR_CODEX_BIN ?? "codex";
    await runCommand(
      options.jobDir,
      [
        codexBin,
        "exec",
        "--cd",
        /*turbopackIgnore: true*/ process.cwd(),
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-m",
        options.model,
        "--output-last-message",
        options.outputPath,
        "-"
      ],
      instruction + prompt
    );
    const output = await readTextIfExists(options.outputPath);
    if (!output.trim()) throw new Error("codex-cli provider did not write a summary");
  }
}

export function getProvider(name: string): AnalyzerProvider {
  const normalized = name.trim().toLowerCase();
  if (normalized === "fixture") return new FixtureProvider();
  if (["codex", "codex-cli", "codex_cli"].includes(normalized)) return new CodexCliProvider();
  throw new Error(`unknown analyzer provider: ${name}`);
}

export async function writeStatus(jobDir: string, payload: JobStatus): Promise<void> {
  await writeJsonAtomic(path.join(jobDir, "status.json"), {
    ...payload,
    updated_at: utcNowIso()
  } as unknown as JsonValue);
}

export async function readStatus(jobDir: string): Promise<JobStatus> {
  return readJsonFile<JobStatus>(path.join(jobDir, "status.json"), {
    job_id: path.basename(jobDir),
    status: "created",
    updated_at: utcNowIso()
  });
}

async function appendLog(jobDir: string, text: string): Promise<void> {
  const logPath = path.join(jobDir, "worker.log");
  await mkdir(jobDir, { recursive: true });
  await new Promise<void>((resolve, reject) => {
    const stream = createWriteStream(logPath, { flags: "a", encoding: "utf8" });
    stream.on("error", reject);
    stream.on("finish", resolve);
    stream.write(text.endsWith("\n") ? text : `${text}\n`);
    stream.end();
  });
}

async function runCommand(jobDir: string, command: string[], inputText: string): Promise<void> {
  await appendLog(jobDir, `$ ${command.join(" ")}`);
  await new Promise<void>((resolve, reject) => {
    const child = spawn(command[0], command.slice(1), {
      cwd: process.cwd(),
      stdio: ["pipe", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", async (code) => {
      if (stdout) await appendLog(jobDir, stdout);
      if (stderr) await appendLog(jobDir, stderr);
      if (code === 0) resolve();
      else reject(new Error(`command failed with exit code ${code}: ${command.join(" ")}`));
    });
    child.stdin.end(inputText);
  });
}

async function logPipelineResult(jobDir: string, action: string, stdout: string, stderr: string): Promise<void> {
  await appendLog(jobDir, `$ core.pipeline ${action}`);
  if (stdout) await appendLog(jobDir, stdout);
  if (stderr) await appendLog(jobDir, stderr);
}

async function memoryStatusFromArtifacts(paths: ReturnType<typeof buildArtifactPaths>): Promise<{
  memoryUpdateStatus: Record<string, JsonValue>;
  memoryAuditStatus: Record<string, JsonValue>;
  finalMemoryPaths: Record<string, string>;
}> {
  const memoryUpdate = await readJsonFile<Record<string, JsonValue>>(paths.memory_update, {});
  const runMetrics = await readJsonFile<Record<string, JsonValue>>(paths.run_metrics, {});
  const memorySection = isRecord(runMetrics.memory) ? runMetrics.memory : {};
  const auditPath = String(memoryUpdate.memory_audit ?? memorySection.memory_audit ?? "");
  const auditPayload = auditPath ? await readJsonFile<Record<string, JsonValue>>(auditPath, {}) : {};
  return {
    memoryUpdateStatus: {
      path: paths.memory_update,
      exists: Object.keys(memoryUpdate).length > 0,
      update_id: memoryUpdate.update_id,
      already_applied: memoryUpdate.already_applied,
      memory_updates: isRecord(memorySection) ? memorySection.memory_updates : undefined,
      information_unit_count: memoryUpdate.information_unit_count,
      event_cluster_count: memoryUpdate.event_cluster_count
    } as Record<string, JsonValue>,
    memoryAuditStatus: {
      path: auditPath,
      exists: Boolean(auditPath && Object.keys(auditPayload).length),
      status: auditPayload.status,
      changed_file_count: auditPayload.changed_file_count,
      changed_files: auditPayload.changed_files
    } as Record<string, JsonValue>,
    finalMemoryPaths: {
      memory_update: paths.memory_update,
      run_metrics: paths.run_metrics,
      ...(auditPath ? { memory_audit: auditPath } : {})
    }
  };
}

function expandHome(value: string): string {
  return value.replace(/^~(?=$|\/|\\)/, process.env.HOME ?? "~");
}

function isRecord(value: unknown): value is Record<string, JsonValue> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

async function readTextArg(text?: string, textFile?: string): Promise<string> {
  if (textFile) return readFile(textFile, "utf8");
  if (text != null) return text;
  if (!process.stdin.isTTY) {
    const chunks: Buffer[] = [];
    for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
    return Buffer.concat(chunks).toString("utf8");
  }
  throw new Error("--text, --text-file, or stdin is required");
}

async function main(argv: string[]): Promise<number> {
  const [command, ...args] = argv;
  const parsed = parseArgs(args);
  if (command === "ingest-text") {
    const text = await readTextArg(stringArg(parsed.text), stringArg(parsed["text-file"]));
    const jobDir = await createManualJob({
      text,
      configPath: stringArg(parsed.config) ?? DEFAULT_CONFIG_PATH,
      jobsDir: stringArg(parsed["jobs-dir"]) ?? DEFAULT_JOBS_DIR,
      title: stringArg(parsed.title),
      url: stringArg(parsed.url),
      userLabel: stringArg(parsed["user-label"]),
      targetCode: stringArg(parsed["target-code"]),
      inputChannel: stringArg(parsed["input-channel"]) ?? "cli",
      contentType: stringArg(parsed["content-type"]) ?? "note",
      requiresVerification: Boolean(parsed["requires-verification"])
    });
    if (parsed.run) {
      const status = await runJob({
        jobDir,
        providerName: stringArg(parsed.provider) ?? "fixture",
        model: stringArg(parsed.model) ?? "gpt-5.4",
        applyMemory: !parsed["no-apply-memory"]
      });
      process.stdout.write(`${JSON.stringify(status, null, 2)}\n`);
      return status.status === "done" ? 0 : 1;
    }
    process.stdout.write(`${jobDir}\n`);
    return 0;
  }
  if (command === "enqueue-ingest-text") {
    const text = await readTextArg(stringArg(parsed.text), stringArg(parsed["text-file"]));
    const result = await enqueueManualTextJob({
      text,
      title: stringArg(parsed.title),
      url: stringArg(parsed.url),
      userLabel: stringArg(parsed["user-label"]),
      targetCode: stringArg(parsed["target-code"]),
      inputChannel: stringArg(parsed["input-channel"]) ?? "cli",
      contentType: stringArg(parsed["content-type"]) ?? "note",
      requiresVerification: Boolean(parsed["requires-verification"]),
      provider: stringArg(parsed.provider) ?? "fixture",
      model: stringArg(parsed.model) ?? "gpt-5.4",
      priority: parsed.priority ? Number(parsed.priority) : 0
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return 0;
  }
  if (command === "db-work-once") {
    const status = await runNextPostgresJob({
      queueName: stringArg(parsed.queue) ?? "analysis",
      workerId: stringArg(parsed["worker-id"]),
      providerName: stringArg(parsed.provider),
      model: stringArg(parsed.model)
    });
    process.stdout.write(`${JSON.stringify(status ?? { status: "idle" }, null, 2)}\n`);
    return status?.status === "failed" ? 1 : 0;
  }
  if (command === "db-worker") {
    await runPostgresWorkerLoop({
      queueName: stringArg(parsed.queue) ?? "analysis",
      workerId: stringArg(parsed["worker-id"]),
      providerName: stringArg(parsed.provider),
      model: stringArg(parsed.model),
      pollMs: parsed["poll-ms"] ? Number(parsed["poll-ms"]) : undefined,
      batchLimit: parsed.limit ? Number(parsed.limit) : undefined
    });
    return 0;
  }
  if (command === "run-job") {
    const jobDir = stringArg(parsed["job-dir"]);
    if (!jobDir) throw new Error("--job-dir is required");
    const status = await runJob({
      jobDir,
      providerName: stringArg(parsed.provider) ?? "fixture",
      model: stringArg(parsed.model) ?? "gpt-5.4",
      applyMemory: !parsed["no-apply-memory"]
    });
    process.stdout.write(`${JSON.stringify(status, null, 2)}\n`);
    return status.status === "done" ? 0 : 1;
  }
  process.stderr.write("Usage: npm run signal-radar -- <ingest-text|enqueue-ingest-text|run-job|db-work-once|db-worker> [options]\n");
  return 2;
}

function stringArg(value: string | boolean | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseArgs(args: string[]): Record<string, string | boolean> {
  const parsed: Record<string, string | boolean> = {};
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = args[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (error) => {
      process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
      process.exit(1);
    }
  );
}
