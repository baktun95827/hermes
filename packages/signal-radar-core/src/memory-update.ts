import { createHash } from "node:crypto";
import { normalizeMemoryUpdate, emptyMemoryUpdate } from "./schemas";
import type { JsonValue, MemoryUpdate } from "./types";

export type AgentOutputContractIssue = {
  path: string;
  severity: "warning" | "error";
  field: "claim" | "evidence_item_ids" | "memory_action" | "confidence" | "risk_reason";
  message: string;
};

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

export function analyzeMemoryUpdateContract(parsed: MemoryUpdate): AgentOutputContractIssue[] {
  const issues: AgentOutputContractIssue[] = [];
  inspectRows(issues, "information_units", parsed.information_units, { requiresClaim: true });
  inspectRows(issues, "event_clusters", parsed.event_clusters, { requiresClaim: true });
  inspectRows(issues, "alert_candidates", parsed.alert_candidates, { requiresClaim: true });
  inspectRows(issues, "contradictions", parsed.contradictions, { requiresClaim: true });
  return issues;
}

function inspectRows(
  issues: AgentOutputContractIssue[],
  collection: string,
  rows: Record<string, JsonValue>[],
  options: { requiresClaim: boolean }
): void {
  rows.forEach((row, index) => {
    const path = `${collection}[${index}]`;
    const memoryAction = field(row, "memory_action");
    const confidence = row.confidence;
    const evidenceIds = Array.isArray(row.evidence_item_ids) ? row.evidence_item_ids.filter(Boolean) : [];
    if (options.requiresClaim && !field(row, "claim") && !field(row, "summary")) {
      issues.push({
        path,
        severity: "error",
        field: "claim",
        message: "Agent output must include a concrete claim or summary."
      });
    }
    if (!memoryAction || memoryAction === "unknown") {
      issues.push({
        path,
        severity: "error",
        field: "memory_action",
        message: "Agent output must set memory_action so downstream write policy is stable."
      });
    }
    if (confidence == null || confidence === "") {
      issues.push({
        path,
        severity: "warning",
        field: "confidence",
        message: "Agent output should include confidence in the 0-1 range."
      });
    }
    if (!evidenceIds.length && !["skip", "reject"].includes(memoryAction)) {
      issues.push({
        path,
        severity: "error",
        field: "evidence_item_ids",
        message: "Write-like memory actions must link to evidence_item_ids."
      });
    }
    if (!field(row, "risk_reason") && !["confirmed", "rejected"].includes(field(row, "verification_status"))) {
      issues.push({
        path,
        severity: "warning",
        field: "risk_reason",
        message: "Agent output should include risk_reason for non-final claims."
      });
    }
  });
}

function field(row: Record<string, JsonValue>, key: string): string {
  const direct = row[key];
  if (typeof direct === "string") return direct.trim();
  if (typeof direct === "number" || typeof direct === "boolean") return String(direct);
  const evaluation = row.signal_evaluation;
  if (evaluation && typeof evaluation === "object" && !Array.isArray(evaluation)) {
    const nested = (evaluation as Record<string, JsonValue>)[key];
    if (typeof nested === "string") return nested.trim();
    if (typeof nested === "number" || typeof nested === "boolean") return String(nested);
  }
  return "";
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
