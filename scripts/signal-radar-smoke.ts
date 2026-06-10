import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  createManualJob,
  runJob
} from "../services/signal-radar-worker/worker";
import {
  applyMemoryUpdate,
  writeJsonAtomic,
  type JobStatus
} from "../packages/signal-radar-core/src";

function assertTrue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function main(): Promise<void> {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), "signal-radar-ts-smoke-"));
  console.log(`temp_root=${tempRoot}`);
  try {
    const configPath = await writeConfig(tempRoot);
    await uniqueJobIdCheck(tempRoot, configPath);
    await workerFixtureSmoke(tempRoot, configPath);
    await codexCliProviderSmoke(tempRoot, configPath);
    await memoryUpdateSampleApply(tempRoot, configPath);
    console.log("ok typescript signal radar smoke");
  } finally {
    await rm(tempRoot, { recursive: true, force: true });
  }
}

async function writeConfig(root: string): Promise<string> {
  const configPath = path.join(root, "config.json");
  await writeJsonAtomic(configPath, {
    base_dir: root,
    accounts: [],
    discovery: { enabled: false, min_interactions: 3 },
    memory_backend: "file",
    state_file: "memory/state.json",
    memory_dir: "memory",
    output_dir: "reports",
    latest_run_file: "latest_run.json",
    themes: ["manual research", "AI infrastructure"],
    theme_aliases: {},
    secondary_theme_aliases: {}
  });
  return configPath;
}

async function uniqueJobIdCheck(root: string, configPath: string): Promise<void> {
  const jobsDir = path.join(root, "jobs-ids");
  const first = await createManualJob({
    text: "Manual note one for unique id smoke.",
    configPath,
    jobsDir,
    title: "unique one"
  });
  const second = await createManualJob({
    text: "Manual note two for unique id smoke.",
    configPath,
    jobsDir,
    title: "unique two"
  });
  assertTrue(path.basename(first) !== path.basename(second), "manual job IDs must be unique");
  console.log("ok unique job ids");
}

async function workerFixtureSmoke(root: string, configPath: string): Promise<JobStatus> {
  const jobDir = await createManualJob({
    text: "Manual note: SampleCo liquid cooling demand is being discussed, but it needs primary-source verification.",
    title: "SampleCo liquid cooling discussion",
    userLabel: "worker_smoke",
    requiresVerification: true,
    configPath,
    jobsDir: path.join(root, "jobs-worker")
  });
  const status = await runJob({ jobDir, providerName: "fixture", model: "gpt-5.4" });
  assertTrue(status.status === "done", "worker fixture job did not finish");
  assertMemoryArtifacts(status, root);
  const reportText = await readText(String(status.paths?.report));
  assertTrue(reportText.startsWith("手动输入研究报告"), "manual report has source-specific title");
  assertTrue(reportText.includes("--- MANUAL INPUT ---"), "manual report body is not source-neutral");
  console.log(`ok worker fixture ${status.job_id}`);
  return status;
}

async function codexCliProviderSmoke(root: string, configPath: string): Promise<JobStatus> {
  const shim = await createCodexShim(path.join(root, "codex-shim"));
  const previous = process.env.XRADAR_CODEX_BIN;
  process.env.XRADAR_CODEX_BIN = shim;
  try {
    const jobDir = await createManualJob({
      text: "Manual note for codex-cli provider smoke. Treat it as unverified.",
      title: "codex-cli smoke",
      userLabel: "codex_smoke",
      requiresVerification: true,
      configPath,
      jobsDir: path.join(root, "jobs-codex-cli")
    });
    const status = await runJob({ jobDir, providerName: "codex-cli", model: "gpt-5.4" });
    assertTrue(status.status === "done", "codex-cli shim job did not finish");
    assertMemoryArtifacts(status, root);
    console.log(`ok codex-cli provider shim ${status.job_id}`);
    return status;
  } finally {
    if (previous == null) delete process.env.XRADAR_CODEX_BIN;
    else process.env.XRADAR_CODEX_BIN = previous;
  }
}

async function memoryUpdateSampleApply(root: string, configPath: string): Promise<void> {
  const summaryPath = path.join(root, "reports", "summary_sample.txt");
  await writeFile(
    summaryPath,
    [
      "Sample summary.",
      "",
      "### MEMORY_UPDATE",
      "```json",
      JSON.stringify({
        primary_themes: ["AI infrastructure"],
        secondary_themes: { "AI infrastructure": ["liquid cooling"] },
        account_notes: { sample_user: "Publishes infrastructure notes that require verification." },
        information_units: [],
        event_clusters: [],
        signal_evaluations: [],
        entity_updates: [],
        event_updates: [],
        macro_updates: [],
        source_assessments: [],
        alert_candidates: [],
        contradictions: []
      }),
      "```"
    ].join("\n"),
    "utf8"
  );
  const result = await applyMemoryUpdate({ configPath, summaryPath });
  assertTrue(result.memory_updates >= 2, "sample memory update should write theme/account memory");
  console.log("ok MEMORY_UPDATE sample apply");
}

function assertMemoryArtifacts(status: JobStatus, root: string): void {
  const paths = status.paths ?? {};
  assertTrue(paths.memory_update, "missing memory_update path");
  assertTrue(paths.memory_audit, "missing memory_audit path");
  assertTrue(path.resolve(paths.memory_update).startsWith(path.resolve(root)), "memory_update escaped temp root");
  assertTrue(path.resolve(paths.memory_audit).startsWith(path.resolve(root)), "memory_audit escaped temp root");
  assertTrue(status.memory_update?.path === paths.memory_update, "memory update path not exposed");
  assertTrue(status.memory_audit?.path === paths.memory_audit, "audit path not exposed");
}

async function createCodexShim(dir: string): Promise<string> {
  await import("node:fs/promises").then((fs) => fs.mkdir(dir, { recursive: true }));
  const shim = path.join(dir, "codex");
  const script = `#!/usr/bin/env node
const fs = require("node:fs");
const args = process.argv.slice(2);
for (const flag of ["exec", "--cd", "--sandbox", "read-only", "--ephemeral", "-m", "--output-last-message", "-"]) {
  if (!args.includes(flag)) {
    console.error("missing codex shim arg: " + flag);
    process.exit(1);
  }
}
const outputPath = args[args.indexOf("--output-last-message") + 1];
process.stdin.resume();
let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const fence = String.fromCharCode(96, 96, 96);
  const payload = {
    primary_themes: ["AI infrastructure"],
    secondary_themes: {"AI infrastructure": ["liquid cooling"]},
    account_notes: {},
    information_units: [{
      event_type: "other",
      relation_to_memory: "new_event",
      subject: "SampleCo cooling note",
      claim: "A manual note says SampleCo cooling demand is being discussed.",
      what_changed: "User-supplied material introduced a new unverified demand discussion.",
      changed_dimensions: ["demand"],
      affected_entities: ["entity:sampleco"],
      affected_themes: ["AI infrastructure"],
      market_mechanism: "Potential capex sentiment, pending verification.",
      time_horizon: "unknown",
      verification_status: "unverified",
      signal_type: "new_angle",
      novelty_level: "medium",
      evidence_strength: "single_source",
      memory_action: "write",
      alert_level: "watch",
      confidence: 0.35,
      evidence_item_ids: ["manual:codex-shim"],
      source_ids: ["manual:codex_shim"]
    }],
    event_clusters: [],
    signal_evaluations: [],
    entity_updates: [],
    event_updates: [],
    macro_updates: [],
    source_assessments: [],
    alert_candidates: [],
    contradictions: []
  };
  fs.writeFileSync(outputPath, "Codex CLI shim summary.\\n\\n### MEMORY_UPDATE\\n" + fence + "json\\n" + JSON.stringify(payload, null, 2) + "\\n" + fence + "\\n");
});
`;
  await writeFile(shim, script, { encoding: "utf8", mode: 0o755 });
  return shim;
}

async function readText(filePath: string): Promise<string> {
  return readFile(filePath, "utf8");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
