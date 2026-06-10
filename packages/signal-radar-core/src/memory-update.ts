import { createHash } from "node:crypto";
import { normalizeMemoryUpdate, emptyMemoryUpdate } from "./schemas";
import type { MemoryUpdate } from "./types";

export function extractMemoryUpdateObject(summaryText: string): unknown | null {
  const lines = summaryText.split(/\r?\n/);
  const startIndex = lines.findIndex((line) => /^\s*#{0,6}\s*MEMORY_UPDATE\s*$/i.test(line));
  if (startIndex < 0) return null;

  let block = lines.slice(startIndex + 1).join("\n").trim();
  const fenced = block.match(/^```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fenced) block = fenced[1].trim();
  const objectText = extractFirstJsonObject(block);
  if (!objectText) return null;
  return JSON.parse(objectText);
}

export function parseMemoryUpdate(summaryText: string): MemoryUpdate {
  const extracted = extractMemoryUpdateObject(summaryText);
  if (!extracted) return emptyMemoryUpdate();
  return normalizeMemoryUpdate(extracted);
}

export function buildMemoryUpdateId(options: {
  summaryText: string;
  summaryPath: string;
  runId?: string | null;
}): string {
  const digest = createHash("sha256")
    .update(options.summaryText)
    .update("\n")
    .update(options.summaryPath)
    .update("\n")
    .update(options.runId ?? "")
    .digest("hex")
    .slice(0, 16);
  return `memupd_${digest}`;
}

export function hasParseableMemoryUpdate(parsed: MemoryUpdate): boolean {
  return Boolean(
    parsed.primary_themes.length ||
      Object.keys(parsed.secondary_themes).length ||
      Object.keys(parsed.account_notes).length ||
      parsed.information_units.length ||
      parsed.event_clusters.length ||
      parsed.signal_evaluations.length ||
      parsed.entity_updates.length ||
      parsed.event_updates.length ||
      parsed.macro_updates.length ||
      parsed.source_assessments.length ||
      parsed.alert_candidates.length ||
      parsed.contradictions.length
  );
}

function extractFirstJsonObject(text: string): string | null {
  const start = text.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let index = start; index < text.length; index += 1) {
    const char = text[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (char === "{") depth += 1;
    if (char === "}") depth -= 1;
    if (depth === 0) return text.slice(start, index + 1);
  }
  return null;
}
