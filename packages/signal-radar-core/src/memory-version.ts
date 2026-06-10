import { diffJson, type JsonDiffOperation } from "./json-diff";
import { cleanText, normalizeAccountName } from "./schemas";
import type { JsonValue, MemoryUpdate } from "./types";

export type MemoryCollection =
  | "themes"
  | "accounts"
  | "information_units"
  | "event_clusters"
  | "signal_evaluations"
  | "entities"
  | "events"
  | "macro"
  | "sources"
  | "alert_candidates"
  | "contradictions";

export type MemoryRecordCandidate = {
  collection: MemoryCollection;
  recordKey: string;
  title: string | null;
  payload: Record<string, JsonValue>;
};

export type MemoryVersionChange = {
  collection: MemoryCollection;
  recordKey: string;
  title: string | null;
  operation: "create" | "update" | "noop";
  before: Record<string, JsonValue> | null;
  after: Record<string, JsonValue>;
  diff: JsonDiffOperation[];
};

export function buildMemoryRecordCandidates(parsed: MemoryUpdate): MemoryRecordCandidate[] {
  const candidates: MemoryRecordCandidate[] = [];

  for (const primaryTheme of parsed.primary_themes) {
    const key = cleanText(primaryTheme);
    if (!key) continue;
    candidates.push({
      collection: "themes",
      recordKey: key,
      title: key,
      payload: {
        primary_theme: key,
        latest_secondary_themes: parsed.secondary_themes[key] ?? []
      }
    });
  }

  for (const [account, note] of Object.entries(parsed.account_notes)) {
    const key = normalizeAccountName(account);
    if (!key || !cleanText(note)) continue;
    candidates.push({
      collection: "accounts",
      recordKey: key,
      title: key,
      payload: { username: key, note: cleanText(note) }
    });
  }

  pushRecordList(candidates, "information_units", parsed.information_units, [
    "information_unit_id",
    "subject",
    "claim"
  ]);
  pushRecordList(candidates, "event_clusters", parsed.event_clusters, ["cluster_id", "title", "summary"]);
  pushRecordList(candidates, "signal_evaluations", parsed.signal_evaluations, [
    "signal_evaluation_id",
    "subject",
    "claim"
  ]);
  pushRecordList(candidates, "entities", parsed.entity_updates, ["entity_id", "id", "name", "title"]);
  pushRecordList(candidates, "events", parsed.event_updates, ["event_id", "id", "title", "subject"]);
  pushRecordList(candidates, "macro", parsed.macro_updates, ["macro_id", "id", "title", "subject"]);
  pushRecordList(candidates, "sources", parsed.source_assessments, ["source_id", "id", "source", "name"]);
  pushRecordList(candidates, "alert_candidates", parsed.alert_candidates, ["alert_id", "id", "subject", "claim"]);
  pushRecordList(candidates, "contradictions", parsed.contradictions, [
    "contradiction_id",
    "id",
    "subject",
    "claim"
  ]);

  return dedupeCandidates(candidates);
}

export function buildMemoryVersionChange(
  candidate: MemoryRecordCandidate,
  before: Record<string, JsonValue> | null
): MemoryVersionChange {
  const diff = diffJson((before ?? undefined) as JsonValue | undefined, candidate.payload as JsonValue);
  return {
    collection: candidate.collection,
    recordKey: candidate.recordKey,
    title: candidate.title,
    operation: before ? (diff.length ? "update" : "noop") : "create",
    before,
    after: candidate.payload,
    diff
  };
}

function pushRecordList(
  candidates: MemoryRecordCandidate[],
  collection: MemoryCollection,
  rows: Record<string, JsonValue>[],
  keyFields: string[]
): void {
  for (const row of rows) {
    const recordKey = recordKeyFromFields(row, keyFields);
    if (!recordKey) continue;
    candidates.push({
      collection,
      recordKey,
      title: titleFromPayload(row),
      payload: row
    });
  }
}

function recordKeyFromFields(row: Record<string, JsonValue>, fields: string[]): string {
  for (const field of fields) {
    const value = cleanText(row[field]);
    if (value) return value;
  }
  return "";
}

function titleFromPayload(row: Record<string, JsonValue>): string | null {
  return (
    cleanText(row.title) ||
    cleanText(row.subject) ||
    cleanText(row.name) ||
    cleanText(row.claim).slice(0, 96) ||
    null
  );
}

function dedupeCandidates(candidates: MemoryRecordCandidate[]): MemoryRecordCandidate[] {
  const seen = new Set<string>();
  const result: MemoryRecordCandidate[] = [];
  for (const candidate of candidates) {
    const key = `${candidate.collection}\n${candidate.recordKey}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(candidate);
  }
  return result;
}
