import { stringifyStable } from "./fs";
import type { JsonValue } from "./types";

export type JsonDiffOperation = {
  op: "add" | "remove" | "replace";
  path: string;
  before?: JsonValue;
  after?: JsonValue;
};

const MISSING = Symbol("missing");

export function diffJson(before: JsonValue | undefined, after: JsonValue | undefined): JsonDiffOperation[] {
  const operations: JsonDiffOperation[] = [];
  diffValue(before === undefined ? MISSING : before, after === undefined ? MISSING : after, "", operations);
  return operations;
}

export function hasJsonDiff(before: JsonValue | undefined, after: JsonValue | undefined): boolean {
  return diffJson(before, after).length > 0;
}

function diffValue(
  before: JsonValue | typeof MISSING,
  after: JsonValue | typeof MISSING,
  path: string,
  operations: JsonDiffOperation[]
): void {
  if (before === MISSING && after !== MISSING) {
    operations.push({ op: "add", path: path || "/", after });
    return;
  }
  if (after === MISSING && before !== MISSING) {
    operations.push({ op: "remove", path: path || "/", before });
    return;
  }
  if (before === MISSING || after === MISSING) return;
  if (stringifyStable(before) === stringifyStable(after)) return;

  if (isPlainRecord(before) && isPlainRecord(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    for (const key of keys) {
      diffValue(
        Object.prototype.hasOwnProperty.call(before, key) ? before[key] : MISSING,
        Object.prototype.hasOwnProperty.call(after, key) ? after[key] : MISSING,
        `${path}/${escapeJsonPointer(key)}`,
        operations
      );
    }
    return;
  }

  operations.push({ op: "replace", path: path || "/", before, after });
}

function escapeJsonPointer(value: string): string {
  return value.replace(/~/g, "~0").replace(/\//g, "~1");
}

function isPlainRecord(value: unknown): value is Record<string, JsonValue> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
