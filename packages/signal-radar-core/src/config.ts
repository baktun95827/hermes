import path from "node:path";
import YAML from "yaml";
import { readFile } from "node:fs/promises";
import { pathExists, writeJsonAtomic } from "./fs";
import type { ArtifactPaths, JsonValue, SignalRadarConfig } from "./types";

export const DEFAULT_CONFIG: Omit<SignalRadarConfig, "config_path" | "base_dir" | "state_file" | "memory_dir" | "output_dir" | "latest_run_file"> & {
  state_file: string;
  memory_dir: string;
  output_dir: string;
  latest_run_file: string;
} = {
  accounts: [],
  tweets_per_account: 15,
  auth: { cookies_file: "cookies.json" },
  discovery: { enabled: true, min_interactions: 3 },
  scroll_count: 5,
  delay_between_accounts: 5,
  memory_backend: "postgres",
  state_file: "memory/state.json",
  memory_dir: "memory",
  output_dir: "reports",
  latest_run_file: "latest_run.json",
  themes: [],
  theme_aliases: {},
  secondary_theme_aliases: {}
};

export function repoRoot(): string {
  return /*turbopackIgnore: true*/ process.cwd();
}

export const REPO_ROOT = repoRoot();
export const DEFAULT_CONFIG_PATH = path.join(/*turbopackIgnore: true*/ process.cwd(), "signal-radar.config.json");
export const DEFAULT_JOBS_DIR = path.join(/*turbopackIgnore: true*/ process.cwd(), "data", "jobs");

export function resolveConfigPath(rawPath: string): string {
  const expanded = rawPath.replace(/^~(?=$|\/|\\)/, process.env.HOME ?? "~");
  return path.isAbsolute(expanded) ? expanded : path.join(/*turbopackIgnore: true*/ process.cwd(), expanded);
}

export function resolvePath(baseDir: string, rawPath: string): string {
  const expanded = String(rawPath).replace(/^~(?=$|\/|\\)/, process.env.HOME ?? "~");
  return path.isAbsolute(expanded) ? expanded : path.join(baseDir, expanded);
}

export async function loadYamlOrJson(filePath: string): Promise<Record<string, unknown>> {
  const text = await readFile(filePath, "utf8");
  if (filePath.toLowerCase().endsWith(".json")) {
    const loaded: unknown = JSON.parse(text);
    return loaded && typeof loaded === "object" && !Array.isArray(loaded)
      ? (loaded as Record<string, unknown>)
      : {};
  }
  const loaded: unknown = YAML.parse(text);
  return loaded && typeof loaded === "object" && !Array.isArray(loaded)
    ? (loaded as Record<string, unknown>)
    : {};
}

export function mergeDeep<T extends Record<string, unknown>>(base: T, override: Record<string, unknown>): T {
  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(override)) {
    if (isPlainObject(value) && isPlainObject(merged[key])) {
      merged[key] = mergeDeep(merged[key] as Record<string, unknown>, value);
    } else {
      merged[key] = value;
    }
  }
  return merged as T;
}

export async function loadConfig(rawPath = DEFAULT_CONFIG_PATH): Promise<SignalRadarConfig> {
  const configPath = resolveConfigPath(rawPath);
  const loaded = (await pathExists(configPath)) ? await loadYamlOrJson(configPath) : {};
  const merged = mergeDeep(DEFAULT_CONFIG as unknown as Record<string, unknown>, loaded);
  const baseDir = resolvePath(path.dirname(configPath), String(merged.base_dir ?? "."));
  const auth = isPlainObject(merged.auth) ? merged.auth : {};
  const config: SignalRadarConfig = {
    config_path: configPath,
    base_dir: baseDir,
    accounts: asStringArray(merged.accounts),
    tweets_per_account: asNumber(merged.tweets_per_account, 15),
    auth: {
      cookies_file: auth.cookies_file ? resolvePath(baseDir, String(auth.cookies_file)) : undefined
    },
    discovery: {
      enabled: Boolean((isPlainObject(merged.discovery) ? merged.discovery.enabled : undefined) ?? true),
      min_interactions: asNumber(isPlainObject(merged.discovery) ? merged.discovery.min_interactions : undefined, 3)
    },
    scroll_count: asNumber(merged.scroll_count, 5),
    delay_between_accounts: asNumber(merged.delay_between_accounts, 5),
    memory_backend: String(merged.memory_backend ?? DEFAULT_CONFIG.memory_backend) === "file" ? "file" : "postgres",
    state_file: resolvePath(baseDir, String(merged.state_file ?? DEFAULT_CONFIG.state_file)),
    memory_dir: resolvePath(baseDir, String(merged.memory_dir ?? DEFAULT_CONFIG.memory_dir)),
    output_dir: resolvePath(baseDir, String(merged.output_dir ?? DEFAULT_CONFIG.output_dir)),
    latest_run_file: resolvePath(baseDir, String(merged.latest_run_file ?? DEFAULT_CONFIG.latest_run_file)),
    themes: asStringArray(merged.themes),
    theme_aliases: asStringArrayMap(merged.theme_aliases),
    secondary_theme_aliases: asNestedStringArrayMap(merged.secondary_theme_aliases)
  };
  return config;
}

export function buildArtifactPaths(outputDir: string, runId: string): ArtifactPaths {
  return {
    data: path.join(outputDir, `data_${runId}.json`),
    collector_batch: path.join(outputDir, `collector_batch_${runId}.json`),
    analysis_input: path.join(outputDir, `analysis_input_${runId}.json`),
    prompt: path.join(outputDir, `prompt_${runId}.txt`),
    report: path.join(outputDir, `report_${runId}.txt`),
    summary: path.join(outputDir, `summary_${runId}.txt`),
    memory_update: path.join(outputDir, `memory_update_${runId}.json`),
    run_metrics: path.join(outputDir, `run_metrics_${runId}.json`),
    warning: path.join(outputDir, `warning_${runId}.txt`),
    memory_audit: path.join(outputDir, `memory_audit_${runId}.json`)
  };
}

export async function writeLatestManifest(latestRunFile: string, payload: Record<string, JsonValue>): Promise<void> {
  await writeJsonAtomic(latestRunFile, payload);
}

function asNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).map((item) => item.trim()).filter(Boolean) : [];
}

function asStringArrayMap(value: unknown): Record<string, string[]> {
  if (!isPlainObject(value)) return {};
  const result: Record<string, string[]> = {};
  for (const [key, list] of Object.entries(value)) result[key] = asStringArray(list);
  return result;
}

function asNestedStringArrayMap(value: unknown): Record<string, Record<string, string[]>> {
  if (!isPlainObject(value)) return {};
  const result: Record<string, Record<string, string[]>> = {};
  for (const [key, child] of Object.entries(value)) result[key] = asStringArrayMap(child);
  return result;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
