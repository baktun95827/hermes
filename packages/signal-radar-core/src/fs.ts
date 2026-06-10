import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { JsonValue } from "./types";

export async function pathExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

export async function ensureDir(dirPath: string): Promise<void> {
  await mkdir(dirPath, { recursive: true });
}

export async function readTextIfExists(filePath: string, fallback = ""): Promise<string> {
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return fallback;
  }
}

export async function readJsonFile<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const loaded: unknown = JSON.parse(await readFile(filePath, "utf8"));
    return loaded as T;
  } catch {
    return fallback;
  }
}

export async function writeTextAtomic(filePath: string, text: string): Promise<void> {
  await ensureDir(path.dirname(filePath));
  const tmpPath = `${filePath}.tmp`;
  await writeFile(tmpPath, text, "utf8");
  await rename(tmpPath, filePath);
}

export async function writeJsonAtomic(filePath: string, payload: JsonValue): Promise<void> {
  await writeTextAtomic(filePath, `${JSON.stringify(payload, null, 2)}\n`);
}

export function stringifyStable(value: unknown): string {
  return JSON.stringify(value, Object.keys(flattenKeys(value)).sort(), 2);
}

function flattenKeys(value: unknown, keys: Record<string, true> = {}): Record<string, true> {
  if (Array.isArray(value)) {
    for (const item of value) flattenKeys(item, keys);
    return keys;
  }
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      keys[key] = true;
      flattenKeys(child, keys);
    }
  }
  return keys;
}
