from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import atomic_write_json
from .schemas import clean_text, coerce_string_list, safe_filename


MEMORY_AUDIT_SCHEMA_VERSION = "signal-radar-memory-audit/v1"
PROMPT_VERSION = "signal-radar-prompt/v1"
MAX_AUDIT_CONTENT_CHARS = 200_000
MAX_AUDIT_DIFF_CHARS = 200_000


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_content_payload(text: str | None) -> dict[str, Any]:
    if text is None:
        return {"content": None, "truncated": False}
    if len(text) <= MAX_AUDIT_CONTENT_CHARS:
        return {"content": text, "truncated": False}
    return {
        "content": text[:MAX_AUDIT_CONTENT_CHARS],
        "truncated": True,
        "original_length": len(text),
    }


def maybe_truncate_diff(diff_text: str) -> dict[str, Any]:
    if len(diff_text) <= MAX_AUDIT_DIFF_CHARS:
        return {"diff": diff_text, "truncated": False}
    return {
        "diff": diff_text[:MAX_AUDIT_DIFF_CHARS],
        "truncated": True,
        "original_length": len(diff_text),
    }


def should_snapshot_memory_file(memory_dir: Path, path: Path) -> bool:
    if not path.is_file():
        return False
    relative = path.relative_to(memory_dir)
    if relative.parts and relative.parts[0] == "audit":
        return False
    if path.name == ".write.lock" or path.suffix == ".tmp":
        return False
    return True


def snapshot_memory_tree(memory_dir: Path) -> dict[str, dict[str, Any]]:
    if not memory_dir.exists():
        return {}

    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(memory_dir.rglob("*")):
        if not should_snapshot_memory_file(memory_dir, path):
            continue
        relative_path = path.relative_to(memory_dir).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        snapshot[relative_path] = {
            "sha256": sha256_text(content),
            "content": content,
        }
    return snapshot


def build_file_diff(
    relative_path: str,
    before_content: str | None,
    after_content: str | None,
) -> str:
    before_lines = (before_content or "").splitlines(keepends=True)
    after_lines = (after_content or "").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )


def build_changed_files(
    before_snapshot: dict[str, dict[str, Any]],
    after_snapshot: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changed_files: list[dict[str, Any]] = []
    for relative_path in sorted(set(before_snapshot) | set(after_snapshot)):
        before = before_snapshot.get(relative_path)
        after = after_snapshot.get(relative_path)
        before_sha = before.get("sha256") if before else None
        after_sha = after.get("sha256") if after else None
        if before_sha == after_sha:
            continue

        before_content = before.get("content") if before else None
        after_content = after.get("content") if after else None
        if before is None:
            action = "created"
        elif after is None:
            action = "deleted"
        else:
            action = "modified"
        diff_payload = maybe_truncate_diff(
            build_file_diff(relative_path, before_content, after_content)
        )
        before_payload = audit_content_payload(before_content)
        after_payload = audit_content_payload(after_content)
        changed_files.append(
            {
                "path": relative_path,
                "action": action,
                "before_sha256": before_sha,
                "after_sha256": after_sha,
                "before_content": before_payload["content"],
                "before_content_truncated": before_payload["truncated"],
                "after_content": after_payload["content"],
                "after_content_truncated": after_payload["truncated"],
                "diff": diff_payload["diff"],
                "diff_truncated": diff_payload["truncated"],
            }
        )
    return changed_files


def collect_input_item_ids(parsed_memory_update: dict[str, Any]) -> list[str]:
    item_ids: list[str] = []
    for key in (
        "information_units",
        "event_clusters",
        "signal_evaluations",
        "entity_updates",
        "event_updates",
        "macro_updates",
        "source_assessments",
        "contradictions",
    ):
        for item in parsed_memory_update.get(key) or []:
            if not isinstance(item, dict):
                continue
            item_ids.extend(coerce_string_list(item.get("evidence_item_ids")))
    return list(dict.fromkeys(item_ids))


def collect_event_cluster_ids(parsed_memory_update: dict[str, Any]) -> list[str]:
    cluster_ids: list[str] = []
    for item in parsed_memory_update.get("event_clusters") or []:
        if isinstance(item, dict):
            cluster_id = clean_text(item.get("cluster_id"))
            if cluster_id:
                cluster_ids.append(cluster_id)
    for key in (
        "information_units",
        "signal_evaluations",
        "entity_updates",
        "event_updates",
        "macro_updates",
    ):
        for item in parsed_memory_update.get(key) or []:
            if isinstance(item, dict):
                cluster_id = clean_text(item.get("cluster_id"))
                if cluster_id:
                    cluster_ids.append(cluster_id)
    return list(dict.fromkeys(cluster_ids))


def build_memory_audit_record(
    *,
    update_id: str,
    status: str,
    applied_at: str,
    memory_dir: Path,
    memory_backend: str,
    before_snapshot: dict[str, dict[str, Any]],
    after_snapshot: dict[str, dict[str, Any]],
    parsed_memory_update: dict[str, Any],
    update_counts: dict[str, int],
    latest_payload: dict[str, Any],
    summary_file: str,
    memory_update_file: str,
    run_metrics_file: str,
    config_path: str,
) -> dict[str, Any]:
    paths = latest_payload.get("paths") if isinstance(latest_payload.get("paths"), dict) else {}
    changed_files = build_changed_files(before_snapshot, after_snapshot)
    return {
        "schema_version": MEMORY_AUDIT_SCHEMA_VERSION,
        "update_id": update_id,
        "status": status,
        "applied_at": applied_at,
        "memory_backend": memory_backend,
        "memory_dir": str(memory_dir),
        "config_path": config_path,
        "run_id": latest_payload.get("run_id"),
        "prompt_version": PROMPT_VERSION,
        "model": latest_payload.get("model") or "unknown",
        "paths": {
            "summary": summary_file,
            "memory_update": memory_update_file,
            "run_metrics": run_metrics_file,
            "analysis_input": paths.get("analysis_input"),
            "prompt": paths.get("prompt"),
            "collector_batch": paths.get("collector_batch"),
            "data": paths.get("data"),
        },
        "input_item_ids": collect_input_item_ids(parsed_memory_update),
        "event_cluster_ids": collect_event_cluster_ids(parsed_memory_update),
        "update_counts": update_counts,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "user_feedback": None,
    }


def memory_audit_path(memory_dir: Path, update_id: str) -> Path:
    return memory_dir / "audit" / f"{safe_filename(update_id)}.json"


def write_memory_audit_record(
    memory_dir: Path,
    audit_record: dict[str, Any],
) -> Path:
    audit_path = memory_audit_path(memory_dir, clean_text(audit_record.get("update_id")))
    if not audit_path.exists():
        atomic_write_json(audit_path, audit_record)
    return audit_path


def read_memory_audit_record(audit_path: Path) -> dict[str, Any] | None:
    if not audit_path.exists():
        return None
    try:
        loaded = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None
