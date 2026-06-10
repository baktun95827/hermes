import { buildAnalysisInput } from "./analysis-input";
import { applyMemoryUpdate } from "./memory-application";

export type PipelineResult = {
  exit_code: number;
  stdout: string;
  stderr: string;
};

export class PipelineError extends Error {
  result: PipelineResult;

  constructor(message: string, result: PipelineResult) {
    super(message);
    this.name = "PipelineError";
    this.result = result;
  }
}

export async function buildAnalysisInputPipeline(options: {
  configPath: string;
  collectorBatchPath?: string | null;
}): Promise<PipelineResult> {
  try {
    const result = await buildAnalysisInput({
      configPath: options.configPath,
      collectorBatchPath: options.collectorBatchPath
    });
    return {
      exit_code: 0,
      stdout: [
        `Analysis Input: ${result.analysis_input_path}`,
        `Prompt: ${result.prompt_path}`,
        `Report: ${result.report_path}`,
        `Run Metrics: ${result.run_metrics_path}`,
        ""
      ].join("\n"),
      stderr: ""
    };
  } catch (error) {
    throw pipelineError("build-analysis-input", error);
  }
}

export async function applyMemoryPipeline(options: {
  configPath: string;
  summaryPath: string;
}): Promise<PipelineResult> {
  try {
    const result = await applyMemoryUpdate({
      configPath: options.configPath,
      summaryPath: options.summaryPath
    });
    return {
      exit_code: 0,
      stdout: [
        `Memory updated: ${result.memory_updates}`,
        `Summary: ${result.summary_path}`,
        `MEMORY_UPDATE: ${result.memory_update_path}`,
        `Run Metrics: ${result.run_metrics_path}`,
        `Memory Audit: ${result.memory_audit_path}`,
        ""
      ].join("\n"),
      stderr: ""
    };
  } catch (error) {
    throw pipelineError("apply-memory", error);
  }
}

function pipelineError(action: string, error: unknown): PipelineError {
  const message = error instanceof Error ? error.message : String(error);
  return new PipelineError(`${action} failed: ${message}`, {
    exit_code: 1,
    stdout: "",
    stderr: `${error instanceof Error ? error.name : "Error"}: ${message}\n`
  });
}
