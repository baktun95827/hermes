import { createHash } from "node:crypto";
import { cleanText, isRecord } from "./schemas";
import type { CollectorItem, JsonValue } from "./types";

export type SourceQualityTier =
  | "official"
  | "primary"
  | "reputable"
  | "secondary"
  | "social"
  | "manual"
  | "promotional"
  | "unknown";

export type EvidenceKind =
  | "hard_evidence"
  | "weak_evidence"
  | "rumor"
  | "speculation"
  | "contradiction"
  | "unknown";

export type EvidenceUsefulnessStatus =
  | "useful"
  | "potential"
  | "duplicate"
  | "low_value"
  | "rejected";

export type QualityGateStatus =
  | "allow"
  | "watch"
  | "skip"
  | "block"
  | "needs_agent_recheck";

export type QualityGateSeverity = "info" | "watch" | "warning" | "critical";

export type EvidenceClassification = {
  source_id: string;
  source_quality: SourceQualityTier;
  evidence_kind: EvidenceKind;
  usefulness_status: EvidenceUsefulnessStatus;
  confidence: number;
  filter_reasons: string[];
};

export type QualityGateDecision = {
  status: QualityGateStatus;
  severity: QualityGateSeverity;
  evidence_kind: EvidenceKind;
  evidence_strength: string;
  verification_status: string;
  source_quality: SourceQualityTier;
  reason: string;
};

const RUMOR_PATTERN = /(rumor|unconfirmed|market talk|据传|传闻|网传|小作文)/i;
const SPECULATION_PATTERN = /(may|might|could|possibly|expected|预计|可能|推测|或许|大概|如果)/i;
const MARKETING_PATTERN = /(stock pick|guaranteed|free group|加群|荐股|稳赚|课程|老师带单|内部消息)/i;

export function sourceIdFromCollectorItem(item: CollectorItem): string {
  return cleanText(item.author?.canonical_entity_id) ||
    cleanText(item.author?.entity_id) ||
    `${cleanText(item.source) || "unknown"}:unknown`;
}

export function evidenceContentHash(item: CollectorItem): string {
  const normalized = [
    cleanText(item.source).toLowerCase(),
    cleanText(item.url).toLowerCase(),
    cleanText(item.title).toLowerCase(),
    normalizeText(item.text)
  ].join("\n");
  return createHash("sha256").update(normalized).digest("hex");
}

export function textExcerpt(text: string, maxLength = 1200): string {
  const cleaned = cleanText(text).replace(/\s+/g, " ");
  return cleaned.length > maxLength ? `${cleaned.slice(0, maxLength)}...` : cleaned;
}

export function classifyCollectorItem(
  item: CollectorItem,
  options: { duplicateOf?: string | null } = {}
): EvidenceClassification {
  const sourceQuality = sourceQualityFromCollectorItem(item);
  const text = cleanText(item.text);
  const reasons: string[] = [];
  const isDuplicate = Boolean(options.duplicateOf);
  const isMarketing = MARKETING_PATTERN.test(text);
  const isLowValue = text.length < 20 || isMarketing;

  if (isDuplicate) reasons.push("duplicate_content_hash");
  if (text.length < 20) reasons.push("too_short");
  if (isMarketing) reasons.push("promotional_language");
  if (item.source_meta?.requires_verification === true) reasons.push("requires_verification");

  const evidenceKind = evidenceKindFromTextAndSource(text, sourceQuality);
  let usefulnessStatus: EvidenceUsefulnessStatus = "potential";
  if (isDuplicate) usefulnessStatus = "duplicate";
  else if (isLowValue) usefulnessStatus = "low_value";
  else if (sourceQuality === "official" || sourceQuality === "primary" || text.length >= 80) usefulnessStatus = "useful";

  return {
    source_id: sourceIdFromCollectorItem(item),
    source_quality: sourceQuality,
    evidence_kind: evidenceKind,
    usefulness_status: usefulnessStatus,
    confidence: confidenceForEvidence(sourceQuality, evidenceKind, usefulnessStatus),
    filter_reasons: reasons
  };
}

export function sourceProfileFromCollectorItem(
  item: CollectorItem,
  classification = classifyCollectorItem(item)
): Record<string, JsonValue> {
  return {
    source: item.source,
    author: item.author as unknown as JsonValue,
    source_meta: item.source_meta as JsonValue,
    latest_content_type: item.content_type,
    latest_url: item.url
  };
}

export function qualityGateFromEvidence(classification: EvidenceClassification): QualityGateDecision {
  if (classification.usefulness_status === "duplicate") {
    return {
      status: "skip",
      severity: "info",
      evidence_kind: classification.evidence_kind,
      evidence_strength: "duplicate",
      verification_status: "unverified",
      source_quality: classification.source_quality,
      reason: "Evidence duplicates an existing content hash."
    };
  }
  if (classification.usefulness_status === "low_value" || classification.source_quality === "promotional") {
    return {
      status: "skip",
      severity: "watch",
      evidence_kind: classification.evidence_kind,
      evidence_strength: "weak",
      verification_status: "unverified",
      source_quality: classification.source_quality,
      reason: "Evidence was classified as low-value or promotional."
    };
  }
  if (classification.evidence_kind === "hard_evidence") {
    return {
      status: "allow",
      severity: "info",
      evidence_kind: classification.evidence_kind,
      evidence_strength: "official",
      verification_status: "confirmed",
      source_quality: classification.source_quality,
      reason: "Evidence comes from an official or primary source."
    };
  }
  if (classification.evidence_kind === "rumor" || classification.evidence_kind === "speculation") {
    return {
      status: "watch",
      severity: "warning",
      evidence_kind: classification.evidence_kind,
      evidence_strength: "weak",
      verification_status: "plausible",
      source_quality: classification.source_quality,
      reason: "Evidence is useful but should remain separated from hard facts."
    };
  }
  return {
    status: "watch",
    severity: "watch",
    evidence_kind: classification.evidence_kind,
    evidence_strength: "weak",
    verification_status: "unverified",
    source_quality: classification.source_quality,
    reason: "Evidence is potentially useful but not hard evidence."
  };
}

export function qualityGateFromMemoryRow(
  row: Record<string, JsonValue>,
  gateType: string
): QualityGateDecision {
  const evidenceStrength = signalField(row, "evidence_strength") || "unknown";
  const verificationStatus = signalField(row, "verification_status") || "unverified";
  const memoryAction = signalField(row, "memory_action") || "unknown";
  const alertLevel = signalField(row, "alert_level") || "none";
  const sourceQuality = sourceQualityFromEvidenceStrength(evidenceStrength);
  const evidenceKind = evidenceKindFromMemorySignals(row, gateType, evidenceStrength, verificationStatus);

  if (gateType.includes("contradiction")) {
    return {
      status: "needs_agent_recheck",
      severity: "critical",
      evidence_kind: "contradiction",
      evidence_strength: evidenceStrength,
      verification_status: verificationStatus,
      source_quality: sourceQuality,
      reason: "Memory update reported a contradiction."
    };
  }

  if (memoryAction === "reject") {
    return {
      status: "block",
      severity: "warning",
      evidence_kind: evidenceKind,
      evidence_strength: evidenceStrength,
      verification_status: verificationStatus,
      source_quality: sourceQuality,
      reason: "Agent rejected this memory action."
    };
  }

  if (memoryAction === "skip") {
    return {
      status: "skip",
      severity: "info",
      evidence_kind: evidenceKind,
      evidence_strength: evidenceStrength,
      verification_status: verificationStatus,
      source_quality: sourceQuality,
      reason: "Agent skipped this memory action."
    };
  }

  if (evidenceStrength === "official" || verificationStatus === "confirmed") {
    return {
      status: "allow",
      severity: alertLevel === "urgent" ? "critical" : "info",
      evidence_kind: evidenceKind,
      evidence_strength: evidenceStrength,
      verification_status: verificationStatus,
      source_quality: sourceQuality,
      reason: "Agent classified this as confirmed or official evidence."
    };
  }

  if (evidenceStrength === "weak" || evidenceStrength === "unknown" || verificationStatus === "unverified") {
    return {
      status: "watch",
      severity: alertLevel === "urgent" || alertLevel === "important" ? "warning" : "watch",
      evidence_kind: evidenceKind,
      evidence_strength: evidenceStrength,
      verification_status: verificationStatus,
      source_quality: sourceQuality,
      reason: "Agent memory signal is not backed by hard evidence."
    };
  }

  return {
    status: "watch",
    severity: alertLevel === "urgent" ? "warning" : "info",
    evidence_kind: evidenceKind,
    evidence_strength: evidenceStrength,
    verification_status: verificationStatus,
    source_quality: sourceQuality,
    reason: "Agent memory signal should be tracked with its evidence state."
  };
}

function sourceQualityFromCollectorItem(item: CollectorItem): SourceQualityTier {
  const source = cleanText(item.source).toLowerCase();
  const contentType = cleanText(item.content_type).toLowerCase();
  const text = cleanText(item.text);
  const meta = item.source_meta ?? {};
  const url = cleanText(item.url).toLowerCase();

  if (MARKETING_PATTERN.test(text)) return "promotional";
  if (meta.official === true || /filing|announcement|exchange|sec|cninfo|edgar/.test(source + " " + contentType + " " + url)) {
    return "official";
  }
  if (/official|company|investor_relations|ir/.test(source + " " + contentType + " " + url)) return "primary";
  if (source === "manual") return "manual";
  if (/twitter|x\.com|weibo|social|tweet|post/.test(source + " " + contentType + " " + url)) return "social";
  if (/reuters|bloomberg|wsj|ft|caixin|news/.test(source + " " + url)) return "reputable";
  return source ? "secondary" : "unknown";
}

function evidenceKindFromTextAndSource(text: string, sourceQuality: SourceQualityTier): EvidenceKind {
  if (RUMOR_PATTERN.test(text)) return "rumor";
  if (SPECULATION_PATTERN.test(text)) return "speculation";
  if (sourceQuality === "official" || sourceQuality === "primary") return "hard_evidence";
  if (sourceQuality === "promotional") return "unknown";
  return "weak_evidence";
}

function evidenceKindFromMemorySignals(
  row: Record<string, JsonValue>,
  gateType: string,
  evidenceStrength: string,
  verificationStatus: string
): EvidenceKind {
  const combined = `${cleanText(row.claim)} ${cleanText(row.summary)} ${cleanText(row.title)}`;
  if (gateType.includes("contradiction")) return "contradiction";
  if (RUMOR_PATTERN.test(combined)) return "rumor";
  if (SPECULATION_PATTERN.test(combined)) return "speculation";
  if (evidenceStrength === "official" || verificationStatus === "confirmed") return "hard_evidence";
  if (evidenceStrength === "weak" || evidenceStrength === "unknown") return "weak_evidence";
  return "weak_evidence";
}

function confidenceForEvidence(
  sourceQuality: SourceQualityTier,
  evidenceKind: EvidenceKind,
  usefulnessStatus: EvidenceUsefulnessStatus
): number {
  const base: Record<SourceQualityTier, number> = {
    official: 0.9,
    primary: 0.8,
    reputable: 0.65,
    secondary: 0.45,
    social: 0.3,
    manual: 0.25,
    promotional: 0.1,
    unknown: 0.3
  };
  let score = base[sourceQuality];
  if (evidenceKind === "rumor" || evidenceKind === "speculation") score = Math.min(score, 0.35);
  if (usefulnessStatus === "duplicate") score = Math.min(score, 0.2);
  if (usefulnessStatus === "low_value" || usefulnessStatus === "rejected") score = Math.min(score, 0.1);
  return Number(score.toFixed(4));
}

function sourceQualityFromEvidenceStrength(evidenceStrength: string): SourceQualityTier {
  if (evidenceStrength === "official") return "official";
  if (evidenceStrength === "multi_source") return "reputable";
  if (evidenceStrength === "single_source") return "secondary";
  if (evidenceStrength === "weak") return "unknown";
  return "unknown";
}

function signalField(row: Record<string, JsonValue>, field: string): string {
  const direct = cleanText(row[field]);
  if (direct) return direct;
  const evaluation = row.signal_evaluation;
  if (isRecord(evaluation)) return cleanText(evaluation[field]);
  return "";
}

function normalizeText(text: string): string {
  return cleanText(text).toLowerCase().replace(/\s+/g, " ");
}
