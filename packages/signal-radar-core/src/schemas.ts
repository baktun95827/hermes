import { createHash } from "node:crypto";
import type { JsonValue, MemoryUpdate } from "./types";

export const COLLECTOR_BATCH_SCHEMA_VERSION = "collector-batch/v1";
export const COLLECTOR_ITEM_SCHEMA_VERSION = "collector-item/v1";

const VERIFICATION_STATUSES = new Set([
  "unverified",
  "plausible",
  "confirmed",
  "superseded",
  "rejected"
]);
const SIGNAL_TYPES = new Set([
  "new_fact",
  "new_angle",
  "confirmation",
  "repeat",
  "noise",
  "unknown"
]);
const NOVELTY_LEVELS = new Set(["high", "medium", "low", "none"]);
const EVIDENCE_STRENGTHS = new Set([
  "weak",
  "single_source",
  "multi_source",
  "official",
  "unknown"
]);
const MEMORY_ACTIONS = new Set([
  "write",
  "merge",
  "skip",
  "supersede",
  "reject",
  "unknown"
]);
const ALERT_LEVELS = new Set(["none", "watch", "important", "urgent"]);

export function uniquePreservingOrder(items: string[]): string[] {
  return [...new Set(items)];
}

export function cleanText(value: unknown): string {
  return value == null ? "" : String(value).trim();
}

export function normalizeAccountName(value: unknown): string {
  return cleanText(value).replace(/^@+/, "");
}

export function safeFilename(value: unknown): string {
  const cleaned = cleanText(value)
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/^[._]+|[._]+$/g, "");
  return cleaned || "untitled";
}

export function coerceStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return uniquePreservingOrder(value.map(cleanText).filter(Boolean));
}

export function coerceDictList(value: unknown): Record<string, JsonValue>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord) as Record<string, JsonValue>[];
}

export function coerceNumber01(value: unknown): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(1, parsed));
}

export function normalizeEnum(value: unknown, allowed: Set<string>, fallback: string): string {
  const normalized = cleanText(value).toLowerCase().replace(/[-\s]+/g, "_");
  return allowed.has(normalized) ? normalized : fallback;
}

export function normalizeSignalType(value: unknown): string {
  const aliases: Record<string, string> = {
    fact: "new_fact",
    new: "new_fact",
    new_view: "new_angle",
    angle: "new_angle",
    confirm: "confirmation",
    duplicate: "repeat"
  };
  const normalized = cleanText(value).toLowerCase().replace(/[-\s]+/g, "_");
  return normalizeEnum(aliases[normalized] ?? normalized, SIGNAL_TYPES, "unknown");
}

export function normalizeNoveltyLevel(value: unknown): string {
  const aliases: Record<string, string> = {
    duplicate: "none",
    duplicated: "none",
    low_value: "none",
    no_value: "none",
    no: "none"
  };
  const normalized = cleanText(value).toLowerCase().replace(/[-\s]+/g, "_");
  return normalizeEnum(aliases[normalized] ?? normalized, NOVELTY_LEVELS, "low");
}

export function buildSignalEvaluation(input: Record<string, JsonValue>): Record<string, JsonValue> {
  return {
    signal_type: normalizeSignalType(input.signal_type),
    novelty_level: normalizeNoveltyLevel(input.novelty_level),
    evidence_strength: normalizeEnum(input.evidence_strength, EVIDENCE_STRENGTHS, "unknown"),
    memory_action: normalizeEnum(input.memory_action, MEMORY_ACTIONS, "unknown"),
    alert_level: normalizeEnum(input.alert_level, ALERT_LEVELS, "none"),
    confidence: coerceNumber01(input.confidence)
  };
}

export function stableHashId(prefix: string, payload: unknown): string {
  const digest = createHash("sha256")
    .update(JSON.stringify(payload))
    .digest("hex")
    .slice(0, 24);
  return `${prefix}:${digest}`;
}

export function stableInformationUnitId(payload: Record<string, JsonValue>): string {
  return cleanText(payload.information_unit_id) || stableHashId("info", [
    payload.subject,
    payload.claim,
    payload.evidence_item_ids
  ]);
}

export function stableEventClusterId(payload: Record<string, JsonValue>): string {
  return cleanText(payload.cluster_id) || stableHashId("cluster", [
    payload.title,
    payload.summary,
    payload.evidence_item_ids
  ]);
}

export function emptyMemoryUpdate(): MemoryUpdate {
  return {
    primary_themes: [],
    secondary_themes: {},
    account_notes: {},
    information_units: [],
    event_clusters: [],
    signal_evaluations: [],
    entity_updates: [],
    event_updates: [],
    macro_updates: [],
    source_assessments: [],
    alert_candidates: [],
    contradictions: []
  };
}

export function normalizeMemoryUpdate(value: unknown): MemoryUpdate {
  const raw = isRecord(value) ? value : {};
  const secondary_themes: Record<string, string[]> = {};
  if (isRecord(raw.secondary_themes)) {
    for (const [theme, items] of Object.entries(raw.secondary_themes)) {
      const normalizedTheme = cleanText(theme);
      if (normalizedTheme) secondary_themes[normalizedTheme] = coerceStringList(items);
    }
  }

  const account_notes: Record<string, string> = {};
  if (isRecord(raw.account_notes)) {
    for (const [account, note] of Object.entries(raw.account_notes)) {
      const normalized = normalizeAccountName(account);
      const text = cleanText(note);
      if (normalized && text) account_notes[normalized] = text;
    }
  }

  return {
    primary_themes: coerceStringList(raw.primary_themes),
    secondary_themes,
    account_notes,
    information_units: coerceDictList(raw.information_units).map(normalizeInformationUnit),
    event_clusters: coerceDictList(raw.event_clusters).map(normalizeEventCluster),
    signal_evaluations: coerceDictList(raw.signal_evaluations).map((item) => ({
      ...item,
      signal_evaluation: buildSignalEvaluation(item)
    })),
    entity_updates: coerceDictList(raw.entity_updates),
    event_updates: coerceDictList(raw.event_updates),
    macro_updates: coerceDictList(raw.macro_updates),
    source_assessments: coerceDictList(raw.source_assessments),
    alert_candidates: coerceDictList(raw.alert_candidates).map(normalizeAgentSignalRow),
    contradictions: coerceDictList(raw.contradictions).map(normalizeAgentSignalRow)
  };
}

function normalizeAgentSignalRow(item: Record<string, JsonValue>): Record<string, JsonValue> {
  const signalEvaluation = buildSignalEvaluation(item);
  const normalized = { ...item };
  normalized.contract_version = "agent_output_contract/v1";
  normalized.subject = cleanText(item.subject ?? item.target ?? item.entity ?? item.topic ?? item.title);
  normalized.claim = cleanText(item.claim ?? item.summary ?? item.observation ?? item.reason);
  normalized.claim_id = cleanText(item.claim_id) || stableHashId("claim", [
    normalized.subject,
    normalized.claim,
    item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids
  ]);
  normalized.verification_status = normalizeEnum(item.verification_status, VERIFICATION_STATUSES, "unverified");
  normalized.signal_type = signalEvaluation.signal_type;
  normalized.novelty_level = signalEvaluation.novelty_level;
  normalized.evidence_strength = signalEvaluation.evidence_strength;
  normalized.memory_action = signalEvaluation.memory_action;
  normalized.alert_level = signalEvaluation.alert_level;
  normalized.confidence = signalEvaluation.confidence;
  normalized.risk_reason = cleanText(item.risk_reason ?? item.reason ?? item.uncertainty_reason ?? item.memory_risk_reason);
  normalized.memory_action_reason = cleanText(item.memory_action_reason ?? item.action_reason);
  normalized.signal_evaluation = signalEvaluation;
  normalized.evidence_item_ids = coerceStringList(item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids);
  normalized.source_ids = coerceStringList(item.source_ids);
  return normalized;
}

function normalizeInformationUnit(item: Record<string, JsonValue>): Record<string, JsonValue> {
  const normalized = { ...item };
  const signalEvaluation = buildSignalEvaluation(item);
  normalized.contract_version = "agent_output_contract/v1";
  normalized.information_unit_id = stableInformationUnitId(item);
  normalized.cluster_id = cleanText(item.cluster_id);
  normalized.subject = cleanText(item.subject ?? item.target ?? item.entity ?? item.topic);
  normalized.claim = cleanText(item.claim ?? item.summary ?? item.observation);
  normalized.claim_id = cleanText(item.claim_id) || stableHashId("claim", [
    normalized.subject,
    normalized.claim,
    item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids
  ]);
  normalized.what_changed = cleanText(item.what_changed);
  normalized.verification_status = normalizeEnum(item.verification_status, VERIFICATION_STATUSES, "unverified");
  normalized.signal_type = signalEvaluation.signal_type;
  normalized.novelty_level = signalEvaluation.novelty_level;
  normalized.evidence_strength = signalEvaluation.evidence_strength;
  normalized.memory_action = signalEvaluation.memory_action;
  normalized.alert_level = signalEvaluation.alert_level;
  normalized.confidence = signalEvaluation.confidence;
  normalized.risk_reason = cleanText(item.risk_reason ?? item.reason ?? item.uncertainty_reason ?? item.memory_risk_reason);
  normalized.memory_action_reason = cleanText(item.memory_action_reason ?? item.action_reason);
  normalized.signal_evaluation = signalEvaluation;
  normalized.evidence_item_ids = coerceStringList(item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids);
  normalized.source_ids = coerceStringList(item.source_ids);
  return normalized;
}

function normalizeEventCluster(item: Record<string, JsonValue>): Record<string, JsonValue> {
  const normalized = { ...item };
  const signalEvaluation = buildSignalEvaluation(item);
  normalized.contract_version = "agent_output_contract/v1";
  normalized.cluster_id = stableEventClusterId(item);
  normalized.title = cleanText(item.title);
  normalized.summary = cleanText(item.summary);
  normalized.claim = cleanText(item.claim ?? item.summary);
  normalized.claim_id = cleanText(item.claim_id) || stableHashId("claim", [
    normalized.title,
    normalized.summary,
    item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids
  ]);
  normalized.theme = cleanText(item.theme ?? item.primary_theme);
  normalized.secondary_themes = coerceStringList(item.secondary_themes);
  normalized.verification_status = normalizeEnum(item.verification_status, VERIFICATION_STATUSES, "unverified");
  normalized.signal_type = signalEvaluation.signal_type;
  normalized.novelty_level = signalEvaluation.novelty_level;
  normalized.evidence_strength = signalEvaluation.evidence_strength;
  normalized.memory_action = signalEvaluation.memory_action;
  normalized.alert_level = signalEvaluation.alert_level;
  normalized.confidence = signalEvaluation.confidence;
  normalized.risk_reason = cleanText(item.risk_reason ?? item.reason ?? item.uncertainty_reason ?? item.memory_risk_reason);
  normalized.memory_action_reason = cleanText(item.memory_action_reason ?? item.action_reason);
  normalized.signal_evaluation = signalEvaluation;
  normalized.evidence_item_ids = coerceStringList(item.evidence_item_ids ?? item.tweet_ids ?? item.item_ids);
  normalized.source_ids = coerceStringList(item.source_ids);
  return normalized;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
