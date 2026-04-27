#!/usr/bin/env python3
"""
Signal Radar for Hermes.

Commands:
  - collect: scrape configured X accounts and write prompt/report artifacts
  - latest: print the latest artifact manifest or selected fields from it
  - apply-memory: parse a Hermes summary and submit MEMORY_UPDATE to memory backend
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "accounts": [],
    "tweets_per_account": 15,
    "auth": {"cookies_file": "cookies.json"},
    "discovery": {"enabled": True, "min_interactions": 3},
    "scroll_count": 5,
    "delay_between_accounts": 5,
    "memory_backend": "file",
    "state_file": "memory/state.json",
    "memory_dir": "memory",
    "output_dir": "reports",
    "latest_run_file": "latest_run.json",
    "themes": [],
    "theme_aliases": {},
    "secondary_theme_aliases": {},
}

STATUS_OK = "ok"
STATUS_LOGIN_WALL = "login_wall"
STATUS_NO_VISIBLE_TWEETS = "no_visible_tweets"
STATUS_ERROR = "error"

COLLECTOR_BATCH_SCHEMA_VERSION = "collector-batch/v1"
COLLECTOR_ITEM_SCHEMA_VERSION = "collector-item/v1"
X_SOURCE_ID = "x"
X_COLLECTOR_TRANSPORT = "browser"
X_COLLECTOR_IMPLEMENTATION = "playwright"

VERIFICATION_STATUSES = {
    "unverified",
    "plausible",
    "confirmed",
    "superseded",
    "rejected",
}
SIGNAL_TYPES = {
    "new_fact",
    "new_angle",
    "repeat",
    "noise",
    "unknown",
}
NOVELTY_LEVELS = {"high", "medium", "low", "none"}
EVIDENCE_STRENGTHS = {
    "weak",
    "single_source",
    "multi_source",
    "official",
    "unknown",
}
MEMORY_ACTIONS = {
    "write",
    "merge",
    "skip",
    "supersede",
    "reject",
    "unknown",
}
ALERT_LEVELS = {"none", "watch", "important", "urgent"}
CHANGED_SINCE_VALUES = {"last_memory", "recent_run", "unknown"}
CONFLICT_TYPES = {
    "source_conflict",
    "data_conflict",
    "official_unverified",
    "unknown",
}
CONTRADICTION_SEVERITIES = {"low", "medium", "high", "unknown"}
THESIS_DIRECTIONS = {"bull", "bear", "neutral", "mixed", "unknown"}
THESIS_STATUSES = {
    "active",
    "watch",
    "strengthened",
    "weakened",
    "invalidated",
    "superseded",
    "unknown",
}
SKIP_MEMORY_ACTIONS = {"ignore", "ignored", "reject", "rejected", "skip", "no_op", "noop"}
SKIP_NOVELTY_VALUES = {"duplicate", "duplicated", "none", "low_value", "no_value"}
SKIP_SIGNAL_TYPES = {"noise"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d_%H%M%S")


def unique_preserving_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def normalize_account_name(value: str) -> str:
    return str(value).strip().lstrip("@")


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(value).strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned or "untitled"


def clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_verification_status(value: Any) -> str:
    status = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    return status if status in VERIFICATION_STATUSES else "unverified"


def normalize_signal_type(value: Any) -> str:
    signal_type = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fact": "new_fact",
        "new": "new_fact",
        "new_view": "new_angle",
        "angle": "new_angle",
        "duplicate": "repeat",
        "duplicated": "repeat",
    }
    signal_type = aliases.get(signal_type, signal_type)
    return signal_type if signal_type in SIGNAL_TYPES else "unknown"


def normalize_novelty_level(value: Any) -> str:
    novelty = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "duplicate": "none",
        "duplicated": "none",
        "low_value": "none",
        "no_value": "none",
        "no": "none",
    }
    novelty = aliases.get(novelty, novelty)
    return novelty if novelty in NOVELTY_LEVELS else "low"


def normalize_evidence_strength(value: Any) -> str:
    strength = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "single": "single_source",
        "one_source": "single_source",
        "multi": "multi_source",
        "multiple": "multi_source",
        "primary": "official",
    }
    strength = aliases.get(strength, strength)
    return strength if strength in EVIDENCE_STRENGTHS else "unknown"


def normalize_memory_action(value: Any) -> str:
    action = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "create": "write",
        "update": "write",
        "create_or_update": "write",
        "append": "write",
        "keep": "write",
        "ignore": "skip",
        "ignored": "skip",
        "no_op": "skip",
        "noop": "skip",
        "rejected": "reject",
    }
    action = aliases.get(action, action)
    return action if action in MEMORY_ACTIONS else "write"


def normalize_alert_level(value: Any) -> str:
    level = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "low": "watch",
        "medium": "important",
        "high": "urgent",
    }
    level = aliases.get(level, level)
    return level if level in ALERT_LEVELS else "none"


def normalize_changed_since(value: Any) -> str:
    changed_since = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "memory": "last_memory",
        "previous_memory": "last_memory",
        "last": "last_memory",
        "run": "recent_run",
        "latest_run": "recent_run",
        "unknown_change": "unknown",
    }
    changed_since = aliases.get(changed_since, changed_since)
    return changed_since if changed_since in CHANGED_SINCE_VALUES else "unknown"


def normalize_conflict_type(value: Any) -> str:
    conflict_type = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "source": "source_conflict",
        "sources": "source_conflict",
        "data": "data_conflict",
        "official": "official_unverified",
        "unverified_official": "official_unverified",
    }
    conflict_type = aliases.get(conflict_type, conflict_type)
    return conflict_type if conflict_type in CONFLICT_TYPES else "unknown"


def normalize_contradiction_severity(value: Any) -> str:
    severity = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "watch": "low",
        "important": "medium",
        "urgent": "high",
    }
    severity = aliases.get(severity, severity)
    return severity if severity in CONTRADICTION_SEVERITIES else "unknown"


def normalize_thesis_direction(value: Any) -> str:
    direction = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "long": "bull",
        "positive": "bull",
        "upside": "bull",
        "多": "bull",
        "多头": "bull",
        "short": "bear",
        "negative": "bear",
        "downside": "bear",
        "risk": "bear",
        "空": "bear",
        "空头": "bear",
        "base": "neutral",
        "balanced": "neutral",
        "双向": "mixed",
    }
    direction = aliases.get(direction, direction)
    return direction if direction in THESIS_DIRECTIONS else "unknown"


def normalize_thesis_status(value: Any) -> str:
    status = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "new": "active",
        "created": "active",
        "monitor": "watch",
        "strengthen": "strengthened",
        "stronger": "strengthened",
        "upgraded": "strengthened",
        "weaken": "weakened",
        "weaker": "weakened",
        "downgraded": "weakened",
        "invalid": "invalidated",
        "rejected": "invalidated",
        "supersede": "superseded",
    }
    status = aliases.get(status, status)
    return status if status in THESIS_STATUSES else "active"


def coerce_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def coerce_non_negative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


def signal_field(update: dict[str, Any], key: str) -> Any:
    signal_evaluation = update.get("signal_evaluation")
    if isinstance(signal_evaluation, dict) and key in signal_evaluation:
        return signal_evaluation.get(key)
    return update.get(key)


def build_signal_evaluation(update: dict[str, Any]) -> dict[str, Any]:
    evidence_count = (
        coerce_non_negative_int(signal_field(update, "evidence_count"))
        or len(coerce_string_list(update.get("evidence_item_ids")))
    )
    source_count = (
        coerce_non_negative_int(signal_field(update, "source_count"))
        or len(coerce_string_list(update.get("source_ids")))
    )
    raw_evidence_strength = signal_field(update, "evidence_strength")
    evidence_strength = normalize_evidence_strength(raw_evidence_strength)
    if evidence_strength == "unknown":
        if source_count > 1 or evidence_count > 1:
            evidence_strength = "multi_source"
        elif source_count == 1 or evidence_count == 1:
            evidence_strength = "single_source"
        else:
            evidence_strength = "weak"

    return {
        "signal_type": normalize_signal_type(signal_field(update, "signal_type")),
        "novelty_level": normalize_novelty_level(
            signal_field(update, "novelty_level") or update.get("novelty")
        ),
        "evidence_strength": evidence_strength,
        "memory_action": normalize_memory_action(
            signal_field(update, "memory_action")
            or update.get("action")
            or update.get("timeline_action")
        ),
        "alert_level": normalize_alert_level(signal_field(update, "alert_level")),
        "confidence": coerce_float_or_none(
            signal_field(update, "confidence") or update.get("confidence")
        ),
        "evidence_count": evidence_count,
        "source_count": source_count,
    }


def is_valuable_signal(signal_evaluation: dict[str, Any]) -> bool:
    return (
        signal_evaluation.get("memory_action") in {"write", "merge", "supersede"}
        and signal_evaluation.get("signal_type") not in SKIP_SIGNAL_TYPES
        and signal_evaluation.get("novelty_level") in {"high", "medium"}
    )


def should_skip_structured_memory_update(update: dict[str, Any]) -> bool:
    action = clean_text(update.get("action") or update.get("timeline_action")).lower()
    novelty = clean_text(update.get("novelty")).lower()
    status = normalize_verification_status(update.get("verification_status"))
    signal_evaluation = build_signal_evaluation(update)
    return (
        action in SKIP_MEMORY_ACTIONS
        or novelty in SKIP_NOVELTY_VALUES
        or status == "rejected"
        or signal_evaluation["memory_action"] in {"skip", "reject"}
        or signal_evaluation["novelty_level"] == "none"
        or signal_evaluation["signal_type"] in SKIP_SIGNAL_TYPES
    )


def stable_claim_id(prefix: str, update: dict[str, Any], scope_keys: list[str]) -> str:
    raw_claim_id = clean_text(update.get("claim_id") or update.get("id"))
    if raw_claim_id:
        return safe_filename(raw_claim_id)

    identity: dict[str, Any] = {
        "claim": clean_text(update.get("claim")),
        "claim_type": clean_text(update.get("claim_type")),
    }
    for key in scope_keys:
        identity[key] = clean_text(update.get(key))
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest[:16]}"


def build_diff_context(update: dict[str, Any]) -> dict[str, Any]:
    return {
        "what_changed": clean_text(update.get("what_changed")),
        "changed_since": normalize_changed_since(update.get("changed_since")),
        "prior_claim_refs": coerce_string_list(update.get("prior_claim_refs")),
    }


def stable_contradiction_id(update: dict[str, Any]) -> str:
    raw_contradiction_id = clean_text(update.get("contradiction_id") or update.get("id"))
    if raw_contradiction_id:
        return safe_filename(raw_contradiction_id)

    identity = {
        "claim": clean_text(update.get("claim") or update.get("summary")),
        "conflicts_with": clean_text(
            update.get("conflicts_with") or update.get("conflict")
        ),
        "conflict_type": normalize_conflict_type(update.get("conflict_type")),
        "related_entity_ids": coerce_string_list(update.get("related_entity_ids")),
        "related_event_ids": coerce_string_list(update.get("related_event_ids")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"contradiction_{digest[:16]}"


def stable_thesis_id(
    entity_id: str,
    thesis_update: dict[str, Any],
    update: dict[str, Any],
    claim: str,
) -> str:
    raw_thesis_id = clean_text(
        thesis_update.get("thesis_id")
        or thesis_update.get("id")
        or update.get("thesis_id")
    )
    if raw_thesis_id:
        return safe_filename(raw_thesis_id)

    identity = {
        "entity_id": entity_id,
        "title": clean_text(thesis_update.get("title") or update.get("thesis_title")),
        "direction": normalize_thesis_direction(
            thesis_update.get("direction") or update.get("thesis_direction")
        ),
        "claim": claim,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"thesis_{digest[:16]}"


def has_embedded_thesis_update(update: dict[str, Any]) -> bool:
    if isinstance(update.get("thesis_update"), dict):
        return True
    return any(
        update.get(key) is not None
        for key in (
            "thesis_id",
            "thesis_title",
            "thesis_direction",
            "thesis_status",
            "bull_case",
            "bear_case",
            "key_watchpoints",
            "invalidation_points",
            "catalysts",
            "thesis_impact",
            "what_changed",
        )
    )


def build_embedded_thesis_update(
    update: dict[str, Any],
    entity_id: str,
    claim: str,
    claim_id: str,
    evidence_item_ids: list[str],
    source_ids: list[str],
    signal_evaluation: dict[str, Any],
    seen_at: str,
    update_id: str,
) -> dict[str, Any] | None:
    raw = update.get("thesis_update")
    if not isinstance(raw, dict):
        if not has_embedded_thesis_update(update):
            return None
        raw = {}

    title = clean_text(raw.get("title") or update.get("thesis_title"))
    if not title:
        title = claim[:80] if len(claim) <= 80 else f"{claim[:77]}..."

    thesis_id = stable_thesis_id(entity_id, raw, update, claim)
    direction = normalize_thesis_direction(
        raw.get("direction") or update.get("thesis_direction")
    )
    thesis_status = normalize_thesis_status(
        raw.get("thesis_status")
        or raw.get("status")
        or update.get("thesis_status")
        or ("superseded" if signal_evaluation["memory_action"] == "supersede" else None)
    )
    return {
        "thesis_id": thesis_id,
        "title": title,
        "direction": direction,
        "thesis_status": thesis_status,
        "bull_case": coerce_string_list(raw.get("bull_case") or update.get("bull_case")),
        "bear_case": coerce_string_list(raw.get("bear_case") or update.get("bear_case")),
        "key_watchpoints": coerce_string_list(
            raw.get("key_watchpoints") or update.get("key_watchpoints")
        ),
        "invalidation_points": coerce_string_list(
            raw.get("invalidation_points") or update.get("invalidation_points")
        ),
        "catalysts": coerce_string_list(raw.get("catalysts") or update.get("catalysts")),
        "what_changed": clean_text(raw.get("what_changed") or update.get("what_changed")),
        "thesis_impact": clean_text(
            raw.get("thesis_impact") or update.get("thesis_impact")
        ),
        "prior_claim_refs": coerce_string_list(
            raw.get("prior_claim_refs") or update.get("prior_claim_refs")
        ),
        "update_entry": {
            "time": seen_at,
            "update_id": update_id,
            "claim_id": claim_id,
            "what_changed": clean_text(
                raw.get("what_changed") or update.get("what_changed")
            ),
            "thesis_impact": clean_text(
                raw.get("thesis_impact") or update.get("thesis_impact")
            ),
            "signal_evaluation": signal_evaluation,
            "evidence_item_ids": evidence_item_ids,
            "source_ids": source_ids,
        },
    }


def merge_embedded_thesis(
    existing: dict[str, Any],
    thesis_update: dict[str, Any],
    seen_at: str,
) -> dict[str, Any]:
    if not isinstance(existing, dict):
        existing = {}

    thesis_id = thesis_update["thesis_id"]
    merged = dict(existing)
    merged.update(
        {
            "thesis_id": thesis_id,
            "title": thesis_update["title"] or existing.get("title") or thesis_id,
            "direction": (
                thesis_update["direction"]
                if thesis_update["direction"] != "unknown"
                else existing.get("direction") or "unknown"
            ),
            "thesis_status": (
                thesis_update["thesis_status"]
                if thesis_update["thesis_status"] != "unknown"
                else existing.get("thesis_status") or "active"
            ),
            "created_at": existing.get("created_at") or seen_at,
            "updated_at": seen_at,
            "last_update_id": thesis_update["update_entry"]["update_id"],
        }
    )

    for key in (
        "bull_case",
        "bear_case",
        "key_watchpoints",
        "invalidation_points",
        "catalysts",
        "prior_claim_refs",
    ):
        merged[key] = unique_preserving_order(
            coerce_string_list(existing.get(key)) + thesis_update[key]
        )[-30:]

    related_claim_ids = unique_preserving_order(
        coerce_string_list(existing.get("related_claim_ids"))
        + [thesis_update["update_entry"]["claim_id"]]
    )
    merged["related_claim_ids"] = related_claim_ids[-50:]

    updates = existing.get("updates", [])
    if not isinstance(updates, list):
        updates = []
    update_entry = thesis_update["update_entry"]
    if update_entry["what_changed"] or update_entry["thesis_impact"]:
        updates.append(update_entry)
    merged["updates"] = updates[-30:]

    if thesis_update["what_changed"]:
        merged["latest_what_changed"] = thesis_update["what_changed"]
    if thesis_update["thesis_impact"]:
        merged["latest_thesis_impact"] = thesis_update["thesis_impact"]
    merged["latest_signal_evaluation"] = update_entry["signal_evaluation"]
    return merged


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_config_path(raw_path: str) -> Path:
    raw = Path(raw_path).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    candidates = [
        (Path.cwd() / raw).resolve(),
        (SCRIPT_DIR / raw).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            print("请先安装: pip install pyyaml --break-system-packages")
            sys.exit(1)
        loaded = yaml.safe_load(text) or {}
    else:
        loaded = json.loads(text)

    if not isinstance(loaded, dict):
        print(f"配置文件格式错误: {path}")
        sys.exit(1)
    return loaded


def load_config(path: str) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    loaded = load_yaml_or_json(config_path)
    config = merge_dicts(DEFAULT_CONFIG, loaded)
    base_dir = config_path.parent

    config["accounts"] = [
        normalize_account_name(item)
        for item in config.get("accounts", [])
        if normalize_account_name(item)
    ]
    config["memory_backend"] = (
        str(config.get("memory_backend") or "file").strip().lower()
    )
    if config["memory_backend"] != "file":
        print(
            "当前只实现 memory_backend=file；"
            f"收到不支持的 backend: {config['memory_backend']}"
        )
        sys.exit(1)
    config["auth"]["cookies_file"] = str(
        resolve_path(base_dir, config["auth"]["cookies_file"])
    )
    config["state_file"] = str(resolve_path(base_dir, config["state_file"]))
    config["memory_dir"] = str(resolve_path(base_dir, config["memory_dir"]))
    config["output_dir"] = str(resolve_path(base_dir, config["output_dir"]))
    config["latest_run_file"] = str(
        resolve_path(base_dir, config["latest_run_file"])
    )
    config["config_path"] = str(config_path)
    config["base_dir"] = str(base_dir.resolve())
    return config


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        temp_path.write_text(text, encoding=encoding)
        os.replace(temp_path, path)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_legacy_state_paths(base_dir: str, state_file: str) -> list[Path]:
    current = Path(state_file).resolve()
    candidates: list[Path] = []
    legacy = resolve_path(Path(base_dir), "state.json")
    if legacy != current:
        candidates.append(legacy)
    return candidates


def read_latest_manifest(latest_run_file: Path) -> dict[str, Any] | None:
    if not latest_run_file.exists():
        return None
    return json.loads(latest_run_file.read_text(encoding="utf-8"))


def write_latest_manifest(latest_run_file: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(latest_run_file, payload)


def build_artifact_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    return {
        "data": output_dir / f"data_{run_id}.json",
        "collector_batch": output_dir / f"collector_batch_{run_id}.json",
        "prompt": output_dir / f"prompt_{run_id}.txt",
        "report": output_dir / f"report_{run_id}.txt",
        "summary": output_dir / f"summary_{run_id}.txt",
        "memory_update": output_dir / f"memory_update_{run_id}.json",
        "warning": output_dir / f"warning_{run_id}.txt",
    }


class StateManager:
    """
    持久化状态：
    - seen_ids: 已处理过的推文 ID 集合（去重）
    - last_run: 兼容旧消费者的运行时间字段
    - updated_at: 当前更可靠的状态文件最近写入时间

    兼容旧版本：
    - 如果旧 state.json 里仍有 theme_history/account_notes，
      会在 FileMemoryStore 中迁移，然后从 state.json 清理掉
    """

    def __init__(self, state_file: str, legacy_paths: list[Path] | None = None):
        self.path = Path(state_file)
        self.legacy_paths = legacy_paths or []
        self.loaded_from_path: Path | None = None
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        candidates = [self.path, *self.legacy_paths]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.loaded_from_path = candidate
                    loaded.setdefault("version", 1)
                    loaded.setdefault("updated_at", None)
                    loaded.setdefault("seen_ids", [])
                    loaded.setdefault("last_run", None)
                    return loaded
            except Exception:
                continue
        return {
            "version": 1,
            "seen_ids": [],
            "last_run": None,
            "updated_at": None,
        }

    def save(self, update_last_run: bool = True):
        if update_last_run:
            self.data["last_run"] = utc_now().isoformat()
        self.data["version"] = 1
        self.data["updated_at"] = utc_now().isoformat()
        self.data["seen_ids"] = self.data["seen_ids"][-2000:]
        atomic_write_json(self.path, self.data)

    def is_seen(self, tweet_id: str) -> bool:
        return tweet_id in self.data["seen_ids"]

    def mark_seen(self, tweet_id: str):
        if tweet_id and tweet_id not in self.data["seen_ids"]:
            self.data["seen_ids"].append(tweet_id)

    def get_legacy_account_notes(self) -> dict[str, str]:
        notes = self.data.get("account_notes", {})
        return notes if isinstance(notes, dict) else {}

    def get_legacy_theme_history(self) -> list[dict[str, Any]]:
        history = self.data.get("theme_history", [])
        return history if isinstance(history, list) else []

    def clear_legacy_memory(self):
        self.data.pop("account_notes", None)
        self.data.pop("theme_history", None)


class ThemeNormalizer:
    def __init__(
        self,
        canonical_primary_themes: list[str] | None = None,
        alias_config: dict[str, Any] | None = None,
        secondary_alias_config: dict[str, Any] | None = None,
    ):
        self.canonical_primary_themes = [
            item.strip()
            for item in (canonical_primary_themes or [])
            if str(item).strip()
        ]
        self.alias_config = alias_config if isinstance(alias_config, dict) else {}
        self.secondary_alias_config = (
            secondary_alias_config
            if isinstance(secondary_alias_config, dict)
            else {}
        )
        self.primary_alias_map = self._build_primary_alias_map()
        self.secondary_alias_map = self._build_secondary_alias_map()

    def _normalize_key(self, value: str) -> str:
        text = str(value).strip().lower()
        text = (
            text.replace("／", "/")
            .replace("｜", "|")
            .replace("–", "-")
            .replace("—", "-")
        )
        text = re.sub(r"\s+", "", text)
        return text

    def _candidate_aliases(self, canonical: str) -> list[str]:
        aliases = [canonical]
        aliases.extend(
            [part.strip() for part in re.split(r"[/|｜]+", canonical) if part.strip()]
        )
        aliases.extend(
            [part.strip() for part in re.split(r"[()（）]+", canonical) if part.strip()]
        )
        return unique_preserving_order(aliases)

    def _build_primary_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        canonical_values = unique_preserving_order(
            self.canonical_primary_themes + list(self.alias_config.keys())
        )
        for canonical in canonical_values:
            if not canonical:
                continue
            candidates = self._candidate_aliases(canonical)
            extra_aliases = self.alias_config.get(canonical, [])
            if isinstance(extra_aliases, str):
                extra_aliases = [extra_aliases]
            if isinstance(extra_aliases, list):
                candidates.extend(str(item).strip() for item in extra_aliases if str(item).strip())
            for alias in unique_preserving_order(candidates):
                alias_map[self._normalize_key(alias)] = canonical
        return alias_map

    def _build_secondary_alias_map(self) -> dict[str, dict[str, str]]:
        alias_map: dict[str, dict[str, str]] = {}
        for primary_theme, secondary_aliases in self.secondary_alias_config.items():
            canonical_primary = self.normalize_primary_theme(primary_theme)
            if not canonical_primary or not isinstance(secondary_aliases, dict):
                continue
            primary_map = alias_map.setdefault(canonical_primary, {})
            for canonical_secondary, aliases in secondary_aliases.items():
                canonical_secondary_text = str(canonical_secondary).strip()
                if not canonical_secondary_text:
                    continue
                candidates = self._candidate_aliases(canonical_secondary_text)
                if isinstance(aliases, str):
                    aliases = [aliases]
                if isinstance(aliases, list):
                    candidates.extend(
                        str(item).strip()
                        for item in aliases
                        if str(item).strip()
                    )
                for alias in unique_preserving_order(candidates):
                    primary_map[self._normalize_key(alias)] = canonical_secondary_text
        return alias_map

    def normalize_primary_theme(self, theme: str) -> str:
        clean = str(theme).strip()
        if not clean:
            return ""
        return self.primary_alias_map.get(self._normalize_key(clean), clean)

    def normalize_primary_themes(self, themes: list[str]) -> list[str]:
        normalized = [
            self.normalize_primary_theme(item)
            for item in themes
            if str(item).strip()
        ]
        return unique_preserving_order([item for item in normalized if item])

    def normalize_secondary_theme(
        self,
        primary_theme: str,
        secondary_theme: str,
    ) -> str:
        canonical_primary = self.normalize_primary_theme(primary_theme)
        clean = str(secondary_theme).strip()
        if not clean:
            return ""
        primary_aliases = self.secondary_alias_map.get(canonical_primary, {})
        return primary_aliases.get(self._normalize_key(clean), clean)

    def normalize_secondary_themes(
        self,
        primary_theme: str,
        themes: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in themes:
            clean = self.normalize_secondary_theme(primary_theme, item)
            if not clean:
                continue
            key = self._normalize_key(clean)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(clean)
        return normalized

    def normalize_secondary_mapping(
        self,
        mapping: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for primary_theme, subthemes in mapping.items():
            canonical = self.normalize_primary_theme(primary_theme)
            if not canonical:
                continue
            existing = normalized.get(canonical, [])
            merged = existing + self.normalize_secondary_themes(canonical, subthemes)
            normalized[canonical] = self.normalize_secondary_themes(canonical, merged)
        return normalized


class MemoryBackend(Protocol):
    root: Path
    index_path: Path
    normalizer: ThemeNormalizer

    def lock(
        self,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
        stale_after_seconds: float = 300.0,
    ) -> Any:
        ...

    def migrate_legacy_state(self, state: StateManager) -> bool:
        ...

    def update_account_note(
        self,
        username: str,
        note: str,
        seen_at: str,
        update_id: str,
        primary_themes: list[str] | None = None,
        secondary_themes: dict[str, list[str]] | None = None,
    ) -> bool:
        ...

    def update_theme_memory(
        self,
        primary_theme: str,
        secondary_themes: list[str],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def update_entity_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def update_event_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def update_macro_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def update_source_assessment(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def update_contradiction_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        ...

    def get_account_notes(self) -> dict[str, str]:
        ...

    def get_recent_theme_memories(self, n: int = 10) -> list[dict[str, Any]]:
        ...

    def get_recent_entity_memories(self, n: int = 8) -> list[dict[str, Any]]:
        ...

    def get_recent_event_memories(self, n: int = 8) -> list[dict[str, Any]]:
        ...

    def get_recent_macro_memories(self, n: int = 8) -> list[dict[str, Any]]:
        ...

    def rebuild_index(self) -> None:
        ...


class FileMemoryStore:
    """File-backed memory backend for local development and Hermes runtime."""

    def __init__(self, memory_dir: str, normalizer: ThemeNormalizer | None = None):
        self.root = Path(memory_dir)
        self.accounts_dir = self.root / "accounts"
        self.themes_dir = self.root / "themes"
        self.entities_dir = self.root / "entities"
        self.events_dir = self.root / "events"
        self.macro_dir = self.root / "macro"
        self.sources_dir = self.root / "sources"
        self.contradictions_dir = self.root / "contradictions"
        self.index_path = self.root / "index.json"
        self.lock_path = self.root / ".write.lock"
        self.normalizer = normalizer or ThemeNormalizer()

    def ensure_dirs(self):
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self.themes_dir.mkdir(parents=True, exist_ok=True)
        self.entities_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.macro_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.contradictions_dir.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return dict(default)

    def _write_json(self, path: Path, payload: dict[str, Any]):
        atomic_write_json(path, payload)

    @contextmanager
    def lock(
        self,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
        stale_after_seconds: float = 300.0,
    ):
        self.ensure_dirs()
        deadline = time.monotonic() + timeout_seconds
        payload = {
            "pid": os.getpid(),
            "acquired_at": utc_now().isoformat(),
        }

        while True:
            try:
                fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False))
                break
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                    if age > stale_after_seconds:
                        self.lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"memory lock timeout: {self.lock_path}")
                time.sleep(poll_interval_seconds)

        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def account_path(self, username: str) -> Path:
        return self.accounts_dir / f"{safe_filename(normalize_account_name(username))}.json"

    def theme_path(self, primary_theme: str) -> Path:
        return self.themes_dir / f"{safe_filename(primary_theme)}.json"

    def entity_path(self, entity_id: str) -> Path:
        return self.entities_dir / f"{safe_filename(entity_id)}.json"

    def event_path(self, event_id: str) -> Path:
        return self.events_dir / f"{safe_filename(event_id)}.json"

    def macro_path(self, macro_id: str) -> Path:
        return self.macro_dir / f"{safe_filename(macro_id)}.json"

    def source_path(self, source_id: str) -> Path:
        return self.sources_dir / f"{safe_filename(source_id)}.json"

    def contradiction_path(self, contradiction_id: str) -> Path:
        return self.contradictions_dir / f"{safe_filename(contradiction_id)}.json"

    def migrate_legacy_state(self, state: StateManager) -> bool:
        changed = False
        legacy_notes = state.get_legacy_account_notes()
        legacy_history = state.get_legacy_theme_history()
        if not legacy_notes and not legacy_history:
            return False

        self.ensure_dirs()
        for username, note in legacy_notes.items():
            self.update_account_note(
                username=username,
                note=note,
                seen_at=utc_now().isoformat(),
                update_id=f"legacy-account-{safe_filename(username)}",
            )
            changed = True

        for entry in legacy_history:
            if not isinstance(entry, dict):
                continue
            seen_at = str(entry.get("time") or utc_now().isoformat())
            for theme in entry.get("themes", []):
                clean = str(theme).strip()
                if not clean:
                    continue
                self.update_theme_memory(
                    primary_theme=clean,
                    secondary_themes=[],
                    seen_at=seen_at,
                    update_id=(
                        "legacy-theme-"
                        f"{safe_filename(clean)}-{safe_filename(seen_at)}"
                    ),
                )
                changed = True

        if changed:
            state.clear_legacy_memory()
            state.save(update_last_run=False)
            self.rebuild_index()
        return changed

    def update_account_note(
        self,
        username: str,
        note: str,
        seen_at: str,
        update_id: str,
        primary_themes: list[str] | None = None,
        secondary_themes: dict[str, list[str]] | None = None,
    ) -> bool:
        username = normalize_account_name(username)
        note = note.strip()
        if not username:
            return False

        normalized_primary = (
            self.normalizer.normalize_primary_themes(primary_themes or [])
            if primary_themes is not None
            else None
        )
        normalized_secondary = (
            self.normalizer.normalize_secondary_mapping(secondary_themes or {})
            if secondary_themes is not None
            else None
        )

        path = self.account_path(username)
        payload = self._read_json(
            path,
            {
                "username": username,
                "created_at": seen_at,
                "updated_at": seen_at,
                "latest_note": "",
                "note_history": [],
                "latest_primary_themes": [],
                "latest_secondary_themes": {},
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if update_id in applied_update_ids:
            return False
        payload["username"] = username
        payload["updated_at"] = seen_at
        payload["last_update_id"] = update_id
        if note:
            if note != payload.get("latest_note"):
                history = payload.get("note_history", [])
                if not isinstance(history, list):
                    history = []
                history.append({"time": seen_at, "note": note})
                payload["note_history"] = history[-20:]
            payload["latest_note"] = note
        if normalized_primary is not None:
            payload["latest_primary_themes"] = normalized_primary
        if normalized_secondary is not None:
            payload["latest_secondary_themes"] = normalized_secondary
        payload["applied_update_ids"] = (applied_update_ids + [update_id])[-50:]
        self._write_json(path, payload)
        return True

    def update_theme_memory(
        self,
        primary_theme: str,
        secondary_themes: list[str],
        seen_at: str,
        update_id: str,
    ) -> bool:
        primary_theme = self.normalizer.normalize_primary_theme(primary_theme).strip()
        if not primary_theme:
            return False

        clean_secondary = self.normalizer.normalize_secondary_themes(
            primary_theme,
            secondary_themes,
        )
        path = self.theme_path(primary_theme)
        payload = self._read_json(
            path,
            {
                "primary_theme": primary_theme,
                "created_at": seen_at,
                "updated_at": seen_at,
                "run_count": 0,
                "latest_secondary_themes": [],
                "recent_runs": [],
                "secondary_themes": {},
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if update_id in applied_update_ids:
            return False
        payload["primary_theme"] = primary_theme
        payload["updated_at"] = seen_at
        payload["last_update_id"] = update_id
        payload["run_count"] = int(payload.get("run_count", 0)) + 1
        payload["latest_secondary_themes"] = clean_secondary

        recent_runs = payload.get("recent_runs", [])
        if not isinstance(recent_runs, list):
            recent_runs = []
        recent_runs.append(
            {
                "time": seen_at,
                "secondary_themes": clean_secondary,
            }
        )
        payload["recent_runs"] = recent_runs[-20:]
        payload["applied_update_ids"] = (applied_update_ids + [update_id])[-50:]

        secondary_index = payload.get("secondary_themes", {})
        if not isinstance(secondary_index, dict):
            secondary_index = {}
        for secondary in clean_secondary:
            existing = secondary_index.get(secondary, {})
            if not isinstance(existing, dict):
                existing = {}
            count = int(existing.get("count", 0)) + 1
            secondary_index[secondary] = {
                "count": count,
                "first_seen": existing.get("first_seen") or seen_at,
                "last_seen": seen_at,
            }
        payload["secondary_themes"] = secondary_index
        self._write_json(path, payload)
        return True

    def update_entity_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        if should_skip_structured_memory_update(update):
            return False

        entity_id = clean_text(
            update.get("entity_id")
            or update.get("symbol")
            or update.get("display_name")
        )
        raw_thesis_update = (
            update.get("thesis_update")
            if isinstance(update.get("thesis_update"), dict)
            else {}
        )
        claim = clean_text(
            update.get("claim")
            or update.get("summary")
            or raw_thesis_update.get("what_changed")
            or raw_thesis_update.get("title")
            or update.get("thesis_title")
        )
        if not entity_id or not claim:
            return False

        claim_id = stable_claim_id("entity_claim", update, ["entity_id", "symbol"])
        entry_update_id = f"{update_id}:{claim_id}"
        path = self.entity_path(entity_id)
        payload = self._read_json(
            path,
            {
                "schema_version": "entity-memory/v1",
                "entity_id": entity_id,
                "entity_type": clean_text(update.get("entity_type")) or "unknown",
                "display_name": clean_text(update.get("display_name")) or entity_id,
                "aliases": [],
                "created_at": seen_at,
                "updated_at": seen_at,
                "claims": {},
                "theses": {},
                "recent_claim_ids": [],
                "recent_thesis_ids": [],
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if entry_update_id in applied_update_ids:
            return False

        aliases = unique_preserving_order(
            coerce_string_list(payload.get("aliases"))
            + coerce_string_list(update.get("aliases"))
        )
        claims = payload.get("claims", {})
        if not isinstance(claims, dict):
            claims = {}
        existing = claims.get(claim_id, {})
        if not isinstance(existing, dict):
            existing = {}

        evidence_item_ids = unique_preserving_order(
            coerce_string_list(existing.get("evidence_item_ids"))
            + coerce_string_list(update.get("evidence_item_ids"))
        )
        source_ids = unique_preserving_order(
            coerce_string_list(existing.get("source_ids"))
            + coerce_string_list(update.get("source_ids"))
        )
        signal_evaluation = build_signal_evaluation(update)
        cluster_id = clean_text(update.get("cluster_id"))
        diff_context = build_diff_context(update)
        thesis_update = build_embedded_thesis_update(
            update=update,
            entity_id=entity_id,
            claim=claim,
            claim_id=claim_id,
            evidence_item_ids=evidence_item_ids,
            source_ids=source_ids,
            signal_evaluation=signal_evaluation,
            seen_at=seen_at,
            update_id=update_id,
        )
        claims[claim_id] = {
            "claim_id": claim_id,
            "cluster_id": cluster_id,
            "claim": claim,
            "claim_type": clean_text(update.get("claim_type")) or "signal",
            "thesis_ids": [thesis_update["thesis_id"]] if thesis_update else [],
            "what_changed": diff_context["what_changed"],
            "changed_since": diff_context["changed_since"],
            "prior_claim_refs": diff_context["prior_claim_refs"],
            "verification_status": normalize_verification_status(
                update.get("verification_status")
            ),
            "confidence": update.get("confidence"),
            "materiality": clean_text(update.get("materiality")),
            "novelty": clean_text(update.get("novelty")),
            "signal_evaluation": signal_evaluation,
            "why_it_matters": clean_text(update.get("why_it_matters")),
            "evidence_item_ids": evidence_item_ids,
            "source_ids": source_ids,
            "first_seen": existing.get("first_seen") or seen_at,
            "last_seen": seen_at,
            "update_count": int(existing.get("update_count", 0)) + 1,
            "last_update_id": update_id,
        }

        recent_claim_ids = coerce_string_list(payload.get("recent_claim_ids"))
        recent_claim_ids = unique_preserving_order(recent_claim_ids + [claim_id])[-30:]
        theses = payload.get("theses", {})
        if not isinstance(theses, dict):
            theses = {}
        recent_thesis_ids = coerce_string_list(payload.get("recent_thesis_ids"))
        if thesis_update:
            thesis_id = thesis_update["thesis_id"]
            existing_thesis = theses.get(thesis_id, {})
            if not isinstance(existing_thesis, dict):
                existing_thesis = {}
            theses[thesis_id] = merge_embedded_thesis(
                existing=existing_thesis,
                thesis_update=thesis_update,
                seen_at=seen_at,
            )
            recent_thesis_ids = unique_preserving_order(
                recent_thesis_ids + [thesis_id]
            )[-30:]
        payload.update(
            {
                "schema_version": "entity-memory/v1",
                "entity_id": entity_id,
                "entity_type": clean_text(update.get("entity_type"))
                or payload.get("entity_type")
                or "unknown",
                "display_name": clean_text(update.get("display_name"))
                or payload.get("display_name")
                or entity_id,
                "aliases": aliases,
                "updated_at": seen_at,
                "last_valuable_at": (
                    seen_at
                    if is_valuable_signal(signal_evaluation)
                    else payload.get("last_valuable_at")
                ),
                "status": (
                    "superseded"
                    if signal_evaluation["memory_action"] == "supersede"
                    else clean_text(update.get("status"))
                    or payload.get("status")
                    or "active"
                ),
                "decay_score": (
                    coerce_float_or_none(update.get("decay_score"))
                    if update.get("decay_score") is not None
                    else payload.get("decay_score")
                ),
                "latest_signal_evaluation": signal_evaluation,
                "claims": claims,
                "theses": theses,
                "recent_claim_ids": recent_claim_ids,
                "recent_thesis_ids": recent_thesis_ids,
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def update_event_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        if should_skip_structured_memory_update(update):
            return False

        event_id = clean_text(update.get("event_id") or update.get("title"))
        claim = clean_text(update.get("claim") or update.get("summary"))
        if not event_id or not claim:
            return False

        claim_id = stable_claim_id("event_claim", update, ["event_id", "timestamp"])
        entry_update_id = f"{update_id}:{claim_id}"
        path = self.event_path(event_id)
        payload = self._read_json(
            path,
            {
                "schema_version": "event-memory/v1",
                "event_id": event_id,
                "title": clean_text(update.get("title")) or event_id,
                "created_at": seen_at,
                "updated_at": seen_at,
                "timeline": [],
                "claims": {},
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if entry_update_id in applied_update_ids:
            return False

        claims = payload.get("claims", {})
        if not isinstance(claims, dict):
            claims = {}
        existing = claims.get(claim_id, {})
        if not isinstance(existing, dict):
            existing = {}
        evidence_item_ids = unique_preserving_order(
            coerce_string_list(existing.get("evidence_item_ids"))
            + coerce_string_list(update.get("evidence_item_ids"))
        )
        source_ids = unique_preserving_order(
            coerce_string_list(existing.get("source_ids"))
            + coerce_string_list(update.get("source_ids"))
        )
        status = normalize_verification_status(update.get("verification_status"))
        signal_evaluation = build_signal_evaluation(update)
        cluster_id = clean_text(update.get("cluster_id"))
        diff_context = build_diff_context(update)
        claims[claim_id] = {
            "claim_id": claim_id,
            "cluster_id": cluster_id,
            "claim": claim,
            "what_changed": diff_context["what_changed"],
            "changed_since": diff_context["changed_since"],
            "prior_claim_refs": diff_context["prior_claim_refs"],
            "verification_status": status,
            "confidence": update.get("confidence"),
            "importance": clean_text(update.get("importance")),
            "signal_evaluation": signal_evaluation,
            "evidence_item_ids": evidence_item_ids,
            "source_ids": source_ids,
            "first_seen": existing.get("first_seen") or seen_at,
            "last_seen": seen_at,
            "update_count": int(existing.get("update_count", 0)) + 1,
            "last_update_id": update_id,
        }

        timeline = payload.get("timeline", [])
        if not isinstance(timeline, list):
            timeline = []
        timeline.append(
            {
                "time": clean_text(update.get("timestamp")) or seen_at,
                "claim_id": claim_id,
                "cluster_id": cluster_id,
                "claim": claim,
                "what_changed": diff_context["what_changed"],
                "changed_since": diff_context["changed_since"],
                "prior_claim_refs": diff_context["prior_claim_refs"],
                "verification_status": status,
                "importance": clean_text(update.get("importance")),
                "signal_evaluation": signal_evaluation,
                "evidence_item_ids": evidence_item_ids,
                "source_ids": source_ids,
            }
        )
        payload.update(
            {
                "schema_version": "event-memory/v1",
                "event_id": event_id,
                "title": clean_text(update.get("title")) or payload.get("title") or event_id,
                "updated_at": seen_at,
                "last_valuable_at": (
                    seen_at
                    if is_valuable_signal(signal_evaluation)
                    else payload.get("last_valuable_at")
                ),
                "status": (
                    "superseded"
                    if signal_evaluation["memory_action"] == "supersede"
                    else clean_text(update.get("status"))
                    or payload.get("status")
                    or "active"
                ),
                "decay_score": (
                    coerce_float_or_none(update.get("decay_score"))
                    if update.get("decay_score") is not None
                    else payload.get("decay_score")
                ),
                "latest_signal_evaluation": signal_evaluation,
                "timeline": timeline[-80:],
                "claims": claims,
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def update_macro_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        if should_skip_structured_memory_update(update):
            return False

        macro_id = clean_text(update.get("macro_id") or update.get("topic"))
        claim = clean_text(update.get("claim") or update.get("observation"))
        if not macro_id or not claim:
            return False

        claim_id = stable_claim_id("macro_claim", update, ["macro_id", "topic"])
        entry_update_id = f"{update_id}:{claim_id}"
        path = self.macro_path(macro_id)
        payload = self._read_json(
            path,
            {
                "schema_version": "macro-memory/v1",
                "macro_id": macro_id,
                "topic": clean_text(update.get("topic")) or macro_id,
                "created_at": seen_at,
                "updated_at": seen_at,
                "observations": [],
                "claims": {},
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if entry_update_id in applied_update_ids:
            return False

        claims = payload.get("claims", {})
        if not isinstance(claims, dict):
            claims = {}
        existing = claims.get(claim_id, {})
        if not isinstance(existing, dict):
            existing = {}
        evidence_item_ids = unique_preserving_order(
            coerce_string_list(existing.get("evidence_item_ids"))
            + coerce_string_list(update.get("evidence_item_ids"))
        )
        source_ids = unique_preserving_order(
            coerce_string_list(existing.get("source_ids"))
            + coerce_string_list(update.get("source_ids"))
        )
        status = normalize_verification_status(update.get("verification_status"))
        signal_evaluation = build_signal_evaluation(update)
        cluster_id = clean_text(update.get("cluster_id"))
        diff_context = build_diff_context(update)
        claims[claim_id] = {
            "claim_id": claim_id,
            "cluster_id": cluster_id,
            "claim": claim,
            "what_changed": diff_context["what_changed"],
            "changed_since": diff_context["changed_since"],
            "prior_claim_refs": diff_context["prior_claim_refs"],
            "verification_status": status,
            "confidence": update.get("confidence"),
            "time_horizon": clean_text(update.get("time_horizon")),
            "materiality": clean_text(update.get("materiality")),
            "signal_evaluation": signal_evaluation,
            "evidence_item_ids": evidence_item_ids,
            "source_ids": source_ids,
            "first_seen": existing.get("first_seen") or seen_at,
            "last_seen": seen_at,
            "update_count": int(existing.get("update_count", 0)) + 1,
            "last_update_id": update_id,
        }

        observations = payload.get("observations", [])
        if not isinstance(observations, list):
            observations = []
        observations.append(
            {
                "time": clean_text(update.get("timestamp")) or seen_at,
                "claim_id": claim_id,
                "cluster_id": cluster_id,
                "claim": claim,
                "what_changed": diff_context["what_changed"],
                "changed_since": diff_context["changed_since"],
                "prior_claim_refs": diff_context["prior_claim_refs"],
                "verification_status": status,
                "time_horizon": clean_text(update.get("time_horizon")),
                "materiality": clean_text(update.get("materiality")),
                "signal_evaluation": signal_evaluation,
                "evidence_item_ids": evidence_item_ids,
                "source_ids": source_ids,
            }
        )
        payload.update(
            {
                "schema_version": "macro-memory/v1",
                "macro_id": macro_id,
                "topic": clean_text(update.get("topic")) or payload.get("topic") or macro_id,
                "updated_at": seen_at,
                "last_valuable_at": (
                    seen_at
                    if is_valuable_signal(signal_evaluation)
                    else payload.get("last_valuable_at")
                ),
                "status": (
                    "superseded"
                    if signal_evaluation["memory_action"] == "supersede"
                    else clean_text(update.get("status"))
                    or payload.get("status")
                    or "active"
                ),
                "decay_score": (
                    coerce_float_or_none(update.get("decay_score"))
                    if update.get("decay_score") is not None
                    else payload.get("decay_score")
                ),
                "latest_signal_evaluation": signal_evaluation,
                "observations": observations[-80:],
                "claims": claims,
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def update_source_assessment(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        if should_skip_structured_memory_update(update):
            return False

        source_id = clean_text(
            update.get("source_id")
            or update.get("canonical_source_id")
            or update.get("username")
        )
        if not source_id:
            return False

        entry_update_id = f"{update_id}:{safe_filename(source_id)}"
        path = self.source_path(source_id)
        payload = self._read_json(
            path,
            {
                "schema_version": "source-memory/v1",
                "source_id": source_id,
                "source_type": clean_text(update.get("source_type")) or "unknown",
                "display_name": clean_text(update.get("display_name")) or source_id,
                "created_at": seen_at,
                "updated_at": seen_at,
                "latest_assessment": "",
                "assessment_history": [],
                "topic_strength": {},
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if entry_update_id in applied_update_ids:
            return False

        source_profile = update.get("source_profile")
        if not isinstance(source_profile, dict):
            source_profile = {}

        def profile_field(key: str) -> Any:
            return source_profile.get(key) if key in source_profile else update.get(key)

        assessment = clean_text(update.get("assessment") or update.get("note"))
        signal_evaluation = build_signal_evaluation(update)
        history = payload.get("assessment_history", [])
        if not isinstance(history, list):
            history = []
        if assessment and assessment != payload.get("latest_assessment"):
            history.append(
                {
                    "time": seen_at,
                    "assessment": assessment,
                    "credibility": clean_text(update.get("credibility")),
                    "requires_confirmation": clean_text(
                        update.get("requires_confirmation")
                    ),
                    "confirmation_required": clean_text(
                        profile_field("confirmation_required")
                    ),
                    "bias_tags": coerce_string_list(update.get("bias_tags")),
                    "signal_evaluation": signal_evaluation,
                }
            )

        topic_strength = payload.get("topic_strength", {})
        if not isinstance(topic_strength, dict):
            topic_strength = {}
        topic_strength.update(coerce_number_mapping(profile_field("topic_strength")))
        last_valuable_at = clean_text(profile_field("last_valuable_at"))
        if not last_valuable_at and is_valuable_signal(signal_evaluation):
            last_valuable_at = seen_at

        payload.update(
            {
                "schema_version": "source-memory/v1",
                "source_id": source_id,
                "source_type": clean_text(profile_field("source_type"))
                or payload.get("source_type")
                or "unknown",
                "display_name": clean_text(update.get("display_name"))
                or payload.get("display_name")
                or source_id,
                "updated_at": seen_at,
                "last_valuable_at": last_valuable_at
                or payload.get("last_valuable_at"),
                "latest_assessment": assessment or payload.get("latest_assessment", ""),
                "credibility": clean_text(update.get("credibility"))
                or payload.get("credibility", ""),
                "requires_confirmation": clean_text(
                    update.get("requires_confirmation")
                )
                or payload.get("requires_confirmation", ""),
                "confirmation_required": clean_text(
                    profile_field("confirmation_required")
                )
                or payload.get("confirmation_required", ""),
                "repeat_tendency": clean_text(profile_field("repeat_tendency"))
                or payload.get("repeat_tendency", ""),
                "hit_rate": (
                    coerce_float_or_none(profile_field("hit_rate"))
                    if profile_field("hit_rate") is not None
                    else payload.get("hit_rate")
                ),
                "repeat_rate": (
                    coerce_float_or_none(profile_field("repeat_rate"))
                    if profile_field("repeat_rate") is not None
                    else payload.get("repeat_rate")
                ),
                "topic_strength": topic_strength,
                "bias_tags": unique_preserving_order(
                    coerce_string_list(payload.get("bias_tags"))
                    + coerce_string_list(update.get("bias_tags"))
                ),
                "latest_signal_evaluation": signal_evaluation,
                "assessment_history": history[-20:],
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def update_contradiction_memory(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
    ) -> bool:
        if normalize_memory_action(update.get("memory_action") or update.get("action")) in {
            "skip",
            "reject",
        }:
            return False

        claim = clean_text(update.get("claim") or update.get("summary"))
        conflicts_with = clean_text(
            update.get("conflicts_with") or update.get("conflict")
        )
        if not claim or not conflicts_with:
            return False

        contradiction_id = stable_contradiction_id(update)
        entry_update_id = f"{update_id}:{contradiction_id}"
        path = self.contradiction_path(contradiction_id)
        payload = self._read_json(
            path,
            {
                "schema_version": "contradiction-memory/v1",
                "contradiction_id": contradiction_id,
                "title": clean_text(update.get("title")) or claim[:80],
                "claim": claim,
                "conflicts_with": conflicts_with,
                "conflict_type": normalize_conflict_type(update.get("conflict_type")),
                "severity": normalize_contradiction_severity(update.get("severity")),
                "status": clean_text(update.get("status")) or "open",
                "created_at": seen_at,
                "updated_at": seen_at,
                "evidence_item_ids": [],
                "source_ids": [],
                "related_entity_ids": [],
                "related_event_ids": [],
                "related_macro_ids": [],
                "related_thesis_ids": [],
                "history": [],
                "applied_update_ids": [],
                "last_update_id": None,
            },
        )
        applied_update_ids = payload.get("applied_update_ids", [])
        if not isinstance(applied_update_ids, list):
            applied_update_ids = []
        if entry_update_id in applied_update_ids:
            return False

        evidence_item_ids = unique_preserving_order(
            coerce_string_list(payload.get("evidence_item_ids"))
            + coerce_string_list(update.get("evidence_item_ids"))
        )
        source_ids = unique_preserving_order(
            coerce_string_list(payload.get("source_ids"))
            + coerce_string_list(update.get("source_ids"))
        )
        related_entity_ids = unique_preserving_order(
            coerce_string_list(payload.get("related_entity_ids"))
            + coerce_string_list(update.get("related_entity_ids"))
        )
        related_event_ids = unique_preserving_order(
            coerce_string_list(payload.get("related_event_ids"))
            + coerce_string_list(update.get("related_event_ids"))
        )
        related_macro_ids = unique_preserving_order(
            coerce_string_list(payload.get("related_macro_ids"))
            + coerce_string_list(update.get("related_macro_ids"))
        )
        related_thesis_ids = unique_preserving_order(
            coerce_string_list(payload.get("related_thesis_ids"))
            + coerce_string_list(update.get("related_thesis_ids"))
        )
        conflict_type = normalize_conflict_type(update.get("conflict_type"))
        severity = normalize_contradiction_severity(update.get("severity"))
        signal_evaluation = build_signal_evaluation(update)
        history = payload.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "time": seen_at,
                "update_id": update_id,
                "claim": claim,
                "conflicts_with": conflicts_with,
                "conflict_type": conflict_type,
                "severity": severity,
                "status": clean_text(update.get("status")) or "open",
                "notes": clean_text(update.get("notes") or update.get("reason")),
                "signal_evaluation": signal_evaluation,
                "evidence_item_ids": evidence_item_ids,
                "source_ids": source_ids,
            }
        )

        payload.update(
            {
                "schema_version": "contradiction-memory/v1",
                "contradiction_id": contradiction_id,
                "title": clean_text(update.get("title"))
                or payload.get("title")
                or claim[:80],
                "claim": claim,
                "conflicts_with": conflicts_with,
                "conflict_type": (
                    conflict_type
                    if conflict_type != "unknown"
                    else payload.get("conflict_type") or "unknown"
                ),
                "severity": (
                    severity
                    if severity != "unknown"
                    else payload.get("severity") or "unknown"
                ),
                "status": clean_text(update.get("status"))
                or payload.get("status")
                or "open",
                "updated_at": seen_at,
                "evidence_item_ids": evidence_item_ids,
                "source_ids": source_ids,
                "related_entity_ids": related_entity_ids,
                "related_event_ids": related_event_ids,
                "related_macro_ids": related_macro_ids,
                "related_thesis_ids": related_thesis_ids,
                "latest_signal_evaluation": signal_evaluation,
                "history": history[-50:],
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def get_account_notes(self) -> dict[str, str]:
        notes: dict[str, str] = {}
        if not self.accounts_dir.exists():
            return notes
        for path in sorted(self.accounts_dir.glob("*.json")):
            payload = self._read_json(path, {})
            username = normalize_account_name(payload.get("username", path.stem))
            note = str(payload.get("latest_note", "")).strip()
            if username and note:
                notes[username] = note
        return notes

    def get_recent_theme_memories(self, n: int = 10) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        if not self.themes_dir.exists():
            return memories
        for path in self.themes_dir.glob("*.json"):
            payload = self._read_json(path, {})
            if not payload:
                continue
            secondary_index = payload.get("secondary_themes", {})
            secondary_items: list[tuple[str, dict[str, Any]]] = []
            if isinstance(secondary_index, dict):
                for key, value in secondary_index.items():
                    if isinstance(value, dict):
                        secondary_items.append((str(key), value))
            secondary_items.sort(
                key=lambda item: (
                    str(item[1].get("last_seen", "")),
                    int(item[1].get("count", 0)),
                ),
                reverse=True,
            )
            memories.append(
                {
                    "primary_theme": str(payload.get("primary_theme", "")).strip(),
                    "updated_at": str(payload.get("updated_at", "")),
                    "run_count": int(payload.get("run_count", 0)),
                    "latest_secondary_themes": payload.get("latest_secondary_themes", []),
                    "top_secondary_themes": [name for name, _ in secondary_items[:5]],
                }
            )
        memories.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [item for item in memories if item.get("primary_theme")][:n]

    def get_recent_entity_memories(self, n: int = 8) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        if not self.entities_dir.exists():
            return memories
        for path in self.entities_dir.glob("*.json"):
            payload = self._read_json(path, {})
            claim_ids = coerce_string_list(payload.get("recent_claim_ids"))[-3:]
            claims = payload.get("claims", {})
            claim_texts: list[str] = []
            change_texts: list[str] = []
            if isinstance(claims, dict):
                for claim_id in claim_ids:
                    claim_payload = claims.get(claim_id, {})
                    if isinstance(claim_payload, dict):
                        claim = clean_text(claim_payload.get("claim"))
                        if claim:
                            claim_texts.append(claim)
                        what_changed = clean_text(claim_payload.get("what_changed"))
                        if what_changed:
                            change_texts.append(what_changed)
            thesis_ids = coerce_string_list(payload.get("recent_thesis_ids"))[-3:]
            theses = payload.get("theses", {})
            thesis_texts: list[str] = []
            if isinstance(theses, dict):
                for thesis_id in thesis_ids:
                    thesis_payload = theses.get(thesis_id, {})
                    if isinstance(thesis_payload, dict):
                        title = clean_text(thesis_payload.get("title"))
                        direction = clean_text(thesis_payload.get("direction"))
                        status = clean_text(thesis_payload.get("thesis_status"))
                        if title:
                            thesis_texts.append(
                                f"{title} [{direction or 'unknown'}/{status or 'active'}]"
                            )
            memories.append(
                {
                    "entity_id": clean_text(payload.get("entity_id")),
                    "display_name": clean_text(payload.get("display_name")),
                    "entity_type": clean_text(payload.get("entity_type")),
                    "updated_at": clean_text(payload.get("updated_at")),
                    "recent_claims": claim_texts,
                    "recent_changes": change_texts,
                    "recent_theses": thesis_texts,
                }
            )
        memories.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [item for item in memories if item.get("entity_id")][:n]

    def get_recent_event_memories(self, n: int = 8) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        if not self.events_dir.exists():
            return memories
        for path in self.events_dir.glob("*.json"):
            payload = self._read_json(path, {})
            timeline = payload.get("timeline", [])
            if not isinstance(timeline, list):
                timeline = []
            recent = []
            changes = []
            for item in timeline[-3:]:
                if isinstance(item, dict):
                    claim = clean_text(item.get("claim"))
                    if claim:
                        recent.append(claim)
                    what_changed = clean_text(item.get("what_changed"))
                    if what_changed:
                        changes.append(what_changed)
            memories.append(
                {
                    "event_id": clean_text(payload.get("event_id")),
                    "title": clean_text(payload.get("title")),
                    "updated_at": clean_text(payload.get("updated_at")),
                    "recent_claims": recent,
                    "recent_changes": changes,
                }
            )
        memories.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [item for item in memories if item.get("event_id")][:n]

    def get_recent_macro_memories(self, n: int = 8) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        if not self.macro_dir.exists():
            return memories
        for path in self.macro_dir.glob("*.json"):
            payload = self._read_json(path, {})
            observations = payload.get("observations", [])
            if not isinstance(observations, list):
                observations = []
            recent = []
            changes = []
            for item in observations[-3:]:
                if isinstance(item, dict):
                    claim = clean_text(item.get("claim"))
                    if claim:
                        recent.append(claim)
                    what_changed = clean_text(item.get("what_changed"))
                    if what_changed:
                        changes.append(what_changed)
            memories.append(
                {
                    "macro_id": clean_text(payload.get("macro_id")),
                    "topic": clean_text(payload.get("topic")),
                    "updated_at": clean_text(payload.get("updated_at")),
                    "recent_claims": recent,
                    "recent_changes": changes,
                }
            )
        memories.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [item for item in memories if item.get("macro_id")][:n]

    def rebuild_index(self):
        self.ensure_dirs()
        accounts: dict[str, Any] = {}
        for path in sorted(self.accounts_dir.glob("*.json")):
            payload = self._read_json(path, {})
            username = normalize_account_name(payload.get("username", path.stem))
            if not username:
                continue
            accounts[username] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "latest_primary_themes": payload.get("latest_primary_themes", []),
            }

        themes: dict[str, Any] = {}
        for path in sorted(self.themes_dir.glob("*.json")):
            payload = self._read_json(path, {})
            primary_theme = str(payload.get("primary_theme", "")).strip()
            if not primary_theme:
                continue
            themes[primary_theme] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "run_count": payload.get("run_count", 0),
                "latest_secondary_themes": payload.get("latest_secondary_themes", []),
            }

        entities: dict[str, Any] = {}
        for path in sorted(self.entities_dir.glob("*.json")):
            payload = self._read_json(path, {})
            entity_id = clean_text(payload.get("entity_id"))
            if not entity_id:
                continue
            entities[entity_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "last_valuable_at": payload.get("last_valuable_at"),
                "status": payload.get("status"),
                "entity_type": payload.get("entity_type"),
                "display_name": payload.get("display_name"),
                "latest_signal_evaluation": payload.get("latest_signal_evaluation"),
                "claim_count": len(payload.get("claims", {}))
                if isinstance(payload.get("claims"), dict)
                else 0,
                "thesis_count": len(payload.get("theses", {}))
                if isinstance(payload.get("theses"), dict)
                else 0,
            }

        events: dict[str, Any] = {}
        for path in sorted(self.events_dir.glob("*.json")):
            payload = self._read_json(path, {})
            event_id = clean_text(payload.get("event_id"))
            if not event_id:
                continue
            timeline = payload.get("timeline", [])
            events[event_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "last_valuable_at": payload.get("last_valuable_at"),
                "status": payload.get("status"),
                "title": payload.get("title"),
                "latest_signal_evaluation": payload.get("latest_signal_evaluation"),
                "timeline_count": len(timeline) if isinstance(timeline, list) else 0,
            }

        macro: dict[str, Any] = {}
        for path in sorted(self.macro_dir.glob("*.json")):
            payload = self._read_json(path, {})
            macro_id = clean_text(payload.get("macro_id"))
            if not macro_id:
                continue
            observations = payload.get("observations", [])
            macro[macro_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "last_valuable_at": payload.get("last_valuable_at"),
                "status": payload.get("status"),
                "topic": payload.get("topic"),
                "latest_signal_evaluation": payload.get("latest_signal_evaluation"),
                "observation_count": (
                    len(observations) if isinstance(observations, list) else 0
                ),
            }

        sources: dict[str, Any] = {}
        for path in sorted(self.sources_dir.glob("*.json")):
            payload = self._read_json(path, {})
            source_id = clean_text(payload.get("source_id"))
            if not source_id:
                continue
            sources[source_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "last_valuable_at": payload.get("last_valuable_at"),
                "source_type": payload.get("source_type"),
                "credibility": payload.get("credibility"),
                "requires_confirmation": payload.get("requires_confirmation"),
                "confirmation_required": payload.get("confirmation_required"),
                "repeat_tendency": payload.get("repeat_tendency"),
            }

        contradictions: dict[str, Any] = {}
        for path in sorted(self.contradictions_dir.glob("*.json")):
            payload = self._read_json(path, {})
            contradiction_id = clean_text(payload.get("contradiction_id"))
            if not contradiction_id:
                continue
            contradictions[contradiction_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "status": payload.get("status"),
                "severity": payload.get("severity"),
                "conflict_type": payload.get("conflict_type"),
                "claim": payload.get("claim"),
                "related_entity_ids": payload.get("related_entity_ids", []),
                "related_event_ids": payload.get("related_event_ids", []),
            }

        index_payload = {
            "version": 5,
            "updated_at": utc_now().isoformat(),
            "account_count": len(accounts),
            "theme_count": len(themes),
            "entity_count": len(entities),
            "event_count": len(events),
            "macro_count": len(macro),
            "source_count": len(sources),
            "contradiction_count": len(contradictions),
            "accounts": accounts,
            "themes": themes,
            "entities": entities,
            "events": events,
            "macro": macro,
            "sources": sources,
            "contradictions": contradictions,
        }
        self._write_json(self.index_path, index_payload)


def create_memory_backend(
    config: dict[str, Any],
    normalizer: ThemeNormalizer | None = None,
) -> MemoryBackend:
    backend = str(config.get("memory_backend") or "file").strip().lower()
    if backend == "file":
        return FileMemoryStore(config["memory_dir"], normalizer=normalizer)
    raise ValueError(f"unsupported memory backend: {backend}")


@dataclass
class FetchResult:
    username: str
    tweets: list[dict[str, Any]]
    status: str
    visible_tweet_count: int = 0
    new_tweet_count: int = 0
    page_url: str | None = None
    page_title: str | None = None
    error: str | None = None
    debug_path: str | None = None


def normalize_same_site(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }
    return mapping.get(normalized)


def load_cookie_export(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"cookies 文件不存在: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    cookies: list[dict[str, Any]] = []

    if isinstance(raw, dict):
        for name, value in raw.items():
            cookies.append(
                {
                    "name": str(name),
                    "value": str(value),
                    "domain": ".x.com",
                    "path": "/",
                }
            )
        return cookies

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            cookie = {
                "name": str(name),
                "value": str(item.get("value", "")),
                "domain": str(item.get("domain") or ".x.com"),
                "path": str(item.get("path") or "/"),
            }
            if "secure" in item:
                cookie["secure"] = bool(item["secure"])
            if "httpOnly" in item:
                cookie["httpOnly"] = bool(item["httpOnly"])
            same_site = normalize_same_site(
                item.get("sameSite") or item.get("same_site")
            )
            if same_site:
                cookie["sameSite"] = same_site
            expires = item.get("expires")
            if expires not in (None, "", -1):
                try:
                    cookie["expires"] = float(expires)
                except (TypeError, ValueError):
                    pass
            cookies.append(cookie)
        if cookies:
            return cookies

    raise ValueError("cookies.json 格式不支持，需为对象或 cookie 数组")


class PlaywrightFetcher:
    def __init__(self, cookies_file: Path, debug_dir: Path):
        self.cookies_file = cookies_file
        self.debug_dir = debug_dir
        self.browser = None
        self.context = None

    async def start(self, pw):
        self.browser = await pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        cookies = load_cookie_export(self.cookies_file)
        await self.context.add_cookies(cookies)
        print("✅ 浏览器已启动，cookies 已加载")

    async def close(self):
        if self.browser:
            await self.browser.close()

    async def fetch_user_tweets(
        self,
        username: str,
        state: StateManager,
        max_tweets: int = 15,
        scroll_count: int = 5,
    ) -> FetchResult:
        page = await self.context.new_page()
        page_title = None
        page_url = None

        try:
            url = f"https://x.com/{username}"
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            for _ in range(scroll_count):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1.3)

            page_url = page.url
            page_title = await page.title()

            if await self._is_login_wall(page):
                debug_path = await self._capture_debug(page, username)
                print(f"  ❌ @{username}: 落到登录墙")
                return FetchResult(
                    username=username,
                    tweets=[],
                    status=STATUS_LOGIN_WALL,
                    page_url=page_url,
                    page_title=page_title,
                    debug_path=debug_path,
                )

            tweet_elements = await page.query_selector_all(
                "article[data-testid='tweet']"
            )
            visible_tweet_count = len(tweet_elements)
            if visible_tweet_count == 0:
                debug_path = await self._capture_debug(page, username)
                print(f"  ❌ @{username}: 页面可见推文为 0")
                return FetchResult(
                    username=username,
                    tweets=[],
                    status=STATUS_NO_VISIBLE_TWEETS,
                    visible_tweet_count=0,
                    page_url=page_url,
                    page_title=page_title,
                    debug_path=debug_path,
                )

            tweets: list[dict[str, Any]] = []
            for el in tweet_elements:
                if len(tweets) >= max_tweets:
                    break
                tweet = await self._parse_tweet(el, username)
                if not tweet or not tweet.get("text"):
                    continue
                tweet_id = tweet.get("id")
                if tweet_id and state.is_seen(tweet_id):
                    continue
                tweets.append(tweet)
                state.mark_seen(tweet_id)

            print(
                f"  📥 @{username}: 可见 {visible_tweet_count} 条，新增 {len(tweets)} 条"
            )
            return FetchResult(
                username=username,
                tweets=tweets,
                status=STATUS_OK,
                visible_tweet_count=visible_tweet_count,
                new_tweet_count=len(tweets),
                page_url=page_url,
                page_title=page_title,
            )
        except Exception as exc:
            debug_path = await self._capture_debug(page, username)
            print(f"  ❌ @{username}: 抓取失败 — {exc}")
            return FetchResult(
                username=username,
                tweets=[],
                status=STATUS_ERROR,
                page_url=page.url if page else page_url,
                page_title=page_title,
                error=str(exc),
                debug_path=debug_path,
            )
        finally:
            await page.close()

    async def _capture_debug(self, page, username: str) -> str | None:
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / f"debug_{username}.png"
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return None

    async def _is_login_wall(self, page) -> bool:
        url = page.url.lower()
        if "/i/flow/login" in url:
            return True

        body_text = (await page.text_content("body") or "").lower()
        login_markers = (
            "sign in",
            "log in",
            "join x today",
            "登录",
            "注册",
            "现在加入",
            "create account",
        )
        if any(marker in body_text for marker in login_markers):
            return True

        return bool(await page.query_selector("input[name='text']"))

    def _match_status_href(self, href: str | None) -> tuple[str, str] | None:
        if not href:
            return None
        match = re.search(r"/([^/]+)/status/(\d+)", str(href))
        if not match:
            return None
        return match.group(1), match.group(2)

    async def _extract_status_metadata(
        self,
        el,
        source_account: str,
    ) -> tuple[str, str | None, str | None, str | None]:
        author = source_account
        tweet_id = None
        created_at = None
        tweet_url = None

        time_el = await el.query_selector("time")
        if time_el:
            created_at = await time_el.get_attribute("datetime")
            href = await time_el.evaluate(
                "node => node.closest('a')?.getAttribute('href')"
            )
            match = self._match_status_href(href)
            if match:
                author, tweet_id = match
                tweet_url = f"https://x.com/{author}/status/{tweet_id}"

        if tweet_id:
            return author, tweet_id, created_at, tweet_url

        link_elements = await el.query_selector_all('a[href*="/status/"]')
        for link_el in link_elements:
            href = await link_el.get_attribute("href")
            match = self._match_status_href(href)
            if not match:
                continue
            author, tweet_id = match
            tweet_url = f"https://x.com/{author}/status/{tweet_id}"
            break

        return author, tweet_id, created_at, tweet_url

    async def _extract_text_content(self, el) -> tuple[str, str]:
        text_candidates: list[str] = []
        quoted_text = ""

        text_nodes = await el.query_selector_all('[data-testid="tweetText"]')
        for node in text_nodes:
            value = re.sub(r"\s+", " ", (await node.inner_text() or "")).strip()
            if value and value not in text_candidates:
                text_candidates.append(value)

        if not text_candidates:
            lang_nodes = await el.query_selector_all("div[lang]")
            for node in lang_nodes[:6]:
                value = re.sub(r"\s+", " ", (await node.inner_text() or "")).strip()
                if value and value not in text_candidates:
                    text_candidates.append(value)

        if len(text_candidates) > 1:
            quoted_text = text_candidates[-1]

        return (text_candidates[0] if text_candidates else ""), quoted_text

    async def _parse_tweet(
        self, el, source_account: str
    ) -> dict[str, Any] | None:
        try:
            images: list[str] = []
            img_elements = await el.query_selector_all(
                '[data-testid="tweetPhoto"] img'
            )
            for img in img_elements:
                src = await img.get_attribute("src")
                if src and "pbs.twimg.com" in src:
                    clean = re.sub(r"name=\w+", "name=large", src)
                    if clean not in images:
                        images.append(clean)

            has_video = bool(
                await el.query_selector('[data-testid="videoPlayer"]')
            )
            text, quoted_text = await self._extract_text_content(el)
            if not text and (images or has_video):
                media_parts: list[str] = []
                if images:
                    media_parts.append(f"{len(images)}张图片")
                if has_video:
                    media_parts.append("视频")
                text = f"[媒体推文：{', '.join(media_parts)}]"

            if not text:
                return None

            author, tweet_id, created_at, tweet_url = await self._extract_status_metadata(
                el,
                source_account,
            )
            stats = await self._parse_stats(el)
            is_retweet = text.startswith("RT @") or bool(
                await el.query_selector('[data-testid="socialContext"]')
            )

            return {
                "id": tweet_id,
                "text": text,
                "author": author,
                "source_account": source_account,
                "created_at": created_at,
                "is_retweet": is_retweet,
                "mentions": extract_mentions(text),
                "images": images,
                "has_video": has_video,
                "quoted_text": quoted_text,
                "retweet_count": stats.get("retweet", 0),
                "like_count": stats.get("like", 0),
                "reply_count": stats.get("reply", 0),
                "tweet_url": tweet_url,
            }
        except Exception:
            return None

    async def _parse_stats(self, el) -> dict[str, int]:
        stats: dict[str, int] = {}
        for key in ["reply", "retweet", "like"]:
            try:
                btn = await el.query_selector(f'[data-testid="{key}"]')
                if not btn:
                    continue
                aria = await btn.get_attribute("aria-label") or ""
                text = await btn.text_content() or ""
                parsed = parse_metric_value(aria) or parse_metric_value(text)
                if parsed is not None:
                    stats[key] = parsed
            except Exception:
                pass
        return stats


def parse_metric_value(label: str) -> int | None:
    if not label:
        return None

    match = re.search(
        r"(\d+(?:[.,]\d+)?(?:,\d{3})?)\s*([kmb万亿]?)",
        label.strip().lower(),
    )
    if not match:
        return None

    raw_number = match.group(1)
    suffix = match.group(2)

    if suffix:
        if "," in raw_number and "." not in raw_number:
            parts = raw_number.split(",")
            if len(parts[-1]) != 3:
                raw_number = ".".join(parts)
            else:
                raw_number = "".join(parts)
        raw_number = raw_number.replace(",", "")
        try:
            value = float(raw_number)
        except ValueError:
            return None
        multiplier = {
            "k": 1_000,
            "m": 1_000_000,
            "b": 1_000_000_000,
            "万": 10_000,
            "亿": 100_000_000,
        }[suffix]
        return int(round(value * multiplier))

    try:
        return int(raw_number.replace(",", ""))
    except ValueError:
        return None


def extract_mentions(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"@(\w+)", text)


def build_x_item_id(tweet: dict[str, Any]) -> str:
    tweet_id = str(tweet.get("id") or "").strip()
    if tweet_id:
        return tweet_id

    fallback_material = "|".join(
        [
            str(tweet.get("author") or ""),
            str(tweet.get("source_account") or ""),
            str(tweet.get("created_at") or ""),
            str(tweet.get("tweet_url") or ""),
            str(tweet.get("text") or ""),
        ]
    )
    digest = hashlib.sha256(
        fallback_material.encode("utf-8")
    ).hexdigest()[:20]
    return f"synthetic-{digest}"


def build_x_author_payload(username: str) -> dict[str, Any]:
    normalized = normalize_account_name(username)
    handle = f"@{normalized}" if normalized else None
    url = f"https://x.com/{normalized}" if normalized else None
    display_name = handle or normalized or ""
    return {
        "source": X_SOURCE_ID,
        "entity_type": "account",
        "entity_id": normalized,
        "canonical_entity_id": f"{X_SOURCE_ID}:{normalized}" if normalized else None,
        "display_name": display_name,
        "handle": handle,
        "url": url,
    }


def build_x_item_url(tweet: dict[str, Any], item_id: str, author: str) -> str:
    existing = str(tweet.get("tweet_url") or "").strip()
    if existing:
        return existing
    normalized_author = normalize_account_name(author)
    if normalized_author and item_id and not item_id.startswith("synthetic-"):
        return f"https://x.com/{normalized_author}/status/{item_id}"
    if normalized_author:
        return f"https://x.com/{normalized_author}"
    return ""


def normalize_x_tweet_to_collector_item(
    tweet: dict[str, Any],
    collected_at: str,
) -> dict[str, Any]:
    author = normalize_account_name(
        tweet.get("author") or tweet.get("source_account") or ""
    )
    source_account = normalize_account_name(tweet.get("source_account") or author)
    item_id = build_x_item_id(tweet)
    image_urls = [
        str(url).strip()
        for url in tweet.get("images", [])
        if str(url).strip()
    ]
    media = [{"type": "image", "url": url} for url in image_urls]
    if tweet.get("has_video"):
        media.append({"type": "video", "url": None})

    mentions = [
        normalize_account_name(item)
        for item in tweet.get("mentions", [])
        if normalize_account_name(item)
    ]

    return {
        "schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": X_SOURCE_ID,
        "item_id": item_id,
        "canonical_id": f"{X_SOURCE_ID}:{item_id}",
        "content_type": "post",
        "published_at": tweet.get("created_at"),
        "collected_at": collected_at,
        "url": build_x_item_url(tweet, item_id, author),
        "title": None,
        "text": tweet.get("text") or "",
        "language": None,
        "author": build_x_author_payload(author),
        "metrics": {
            "likes": tweet.get("like_count", 0),
            "replies": tweet.get("reply_count", 0),
            "reposts": tweet.get("retweet_count", 0),
            "views": None,
        },
        "media": media,
        "relations": {
            "is_repost": bool(tweet.get("is_retweet")),
            "quoted_item_id": None,
            "reply_to_item_id": None,
            "mentioned_entities": [f"{X_SOURCE_ID}:{item}" for item in mentions],
        },
        "source_meta": {
            "source_account": source_account,
            "quoted_text": tweet.get("quoted_text") or None,
            "has_video": bool(tweet.get("has_video")),
            "image_urls": image_urls,
            "mentioned_users": mentions,
        },
    }


def build_collector_target(accounts: list[str]) -> dict[str, Any]:
    normalized = [
        normalize_account_name(item)
        for item in accounts
        if normalize_account_name(item)
    ]
    if len(normalized) == 1:
        username = normalized[0]
        return {
            "kind": "account",
            "id": username,
            "display_name": f"@{username}",
        }

    preview = ", ".join(f"@{item}" for item in normalized[:3])
    if len(normalized) > 3:
        preview += f" +{len(normalized) - 3}"
    return {
        "kind": "account_set",
        "id": "configured_accounts",
        "display_name": preview or "configured accounts",
        "members": normalized,
    }


def build_x_collector_batch(
    run_id: str,
    collected_at: str,
    accounts: list[str],
    fetch_results: list["FetchResult"],
    warning: str | None,
    config_path: str,
) -> dict[str, Any]:
    items = [
        normalize_x_tweet_to_collector_item(tweet, collected_at)
        for result in fetch_results
        for tweet in result.tweets
    ]
    return {
        "schema_version": COLLECTOR_BATCH_SCHEMA_VERSION,
        "item_schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": X_SOURCE_ID,
        "collector_run_id": run_id,
        "collected_at": collected_at,
        "target": build_collector_target(accounts),
        "collector": {
            "transport": X_COLLECTOR_TRANSPORT,
            "implementation": X_COLLECTOR_IMPLEMENTATION,
            "entrypoint": "monitor.py collect",
        },
        "item_count": len(items),
        "items": items,
        "warnings": [warning] if warning else [],
        "raw_meta": {
            "config_path": config_path,
            "account_results": [asdict(result) for result in fetch_results],
        },
    }


class DiscoveryEngine:
    def __init__(self, monitored: list[str], min_interactions: int = 3):
        self.monitored = {normalize_account_name(item).lower() for item in monitored}
        self.min_interactions = min_interactions
        self.counter = Counter()

    def process(self, all_tweets: list[dict[str, Any]]):
        for tweet in all_tweets:
            for mention in tweet.get("mentions", []):
                if mention.lower() not in self.monitored:
                    self.counter[mention] += 1

    def get_recommendations(self) -> list[dict[str, Any]]:
        return [
            {"username": username, "count": count}
            for username, count in self.counter.most_common(10)
            if count >= self.min_interactions
        ]


def format_raw_report(account_tweets: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    all_tweets = [
        tweet
        for tweets in account_tweets.values()
        for tweet in tweets
    ]

    if not all_tweets:
        return "本次监控无新推文。"

    all_tweets.sort(
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )

    for tweet in all_tweets:
        lines.append("--- TWEET ---")
        lines.append(f"作者: @{tweet['author']}")
        if tweet.get("source_account") and tweet["source_account"] != tweet["author"]:
            lines.append(f"监控源: @{tweet['source_account']}")
        if tweet.get("created_at"):
            lines.append(f"时间: {tweet['created_at']}")
        if tweet.get("tweet_url"):
            lines.append(f"链接: {tweet['tweet_url']}")
        if tweet.get("is_retweet"):
            lines.append("类型: 转推/转发")
        lines.append("正文:")
        lines.append(tweet["text"])
        if tweet.get("quoted_text"):
            lines.append(f"引用推文: {tweet['quoted_text']}")
        if tweet.get("images"):
            lines.append(f"图片: {', '.join(tweet['images'])}")
        if tweet.get("has_video"):
            lines.append("[包含视频]")
        engagement = []
        if tweet.get("like_count"):
            engagement.append(f"❤️ {tweet['like_count']}")
        if tweet.get("retweet_count"):
            engagement.append(f"🔁 {tweet['retweet_count']}")
        if tweet.get("reply_count"):
            engagement.append(f"💬 {tweet['reply_count']}")
        if engagement:
            lines.append(f"互动: {' | '.join(engagement)}")
        lines.append("")

    return "\n".join(lines)


def format_discovery_section(
    recommendations: list[dict[str, Any]],
    keywords: list[str],
) -> str:
    lines: list[str] = []
    if recommendations:
        lines.append("── 发现推荐 ──")
        for item in recommendations[:5]:
            lines.append(f"  @{item['username']} — 被提及 {item['count']} 次")
        lines.append("")
    if keywords:
        lines.append("── 热点关键词 ──")
        lines.append(f"  {', '.join(keywords)}")
    return "\n".join(lines)


def extract_keywords(tweets: list[dict[str, Any]], top_n: int = 10) -> list[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on",
        "at", "for", "of", "and", "or", "but", "not", "with", "this",
        "that", "it", "be", "as", "by", "from", "has", "have", "had",
        "rt", "https", "http", "co", "amp", "just", "will", "can",
        "about", "more", "than", "been", "would", "could", "should",
        "their", "there", "they", "them", "then", "what", "when",
        "your", "you", "its", "all", "very", "much",
    }
    counter = Counter()
    for tweet in tweets:
        text = re.sub(r"https?://\S+", "", tweet.get("text", ""))
        text = re.sub(r"@\w+", "", text)
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
        for word in words:
            if word not in stopwords and len(word) > 2:
                counter[word] += 1
    return [word for word, _ in counter.most_common(top_n)]


def build_llm_prompt(
    raw_report: str,
    discovery_section: str,
    memory_store: MemoryBackend,
    predefined_themes: list[str],
) -> str:
    recent_theme_memories = memory_store.get_recent_theme_memories()
    recent_entity_memories = memory_store.get_recent_entity_memories()
    recent_event_memories = memory_store.get_recent_event_memories()
    recent_macro_memories = memory_store.get_recent_macro_memories()
    account_notes = memory_store.get_account_notes()

    history_context = ""
    if recent_theme_memories:
        history_context += "\n近期主题记忆:\n"
        for item in recent_theme_memories:
            secondaries = item.get("top_secondary_themes") or item.get(
                "latest_secondary_themes", []
            )
            secondary_text = ", ".join(secondaries) if secondaries else "（暂无二级主题）"
            history_context += (
                f"  - {item['primary_theme']}: 二级主题 {secondary_text}；"
                f"出现 {item['run_count']} 次\n"
            )
    if account_notes:
        history_context += "\n各账号历史画像:\n"
        for user, note in account_notes.items():
            history_context += f"  @{user}: {note}\n"
    if recent_entity_memories:
        history_context += "\n近期标的/公司记忆:\n"
        for item in recent_entity_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            changes = "；".join(item.get("recent_changes") or [])
            theses = "；".join(item.get("recent_theses") or [])
            history_context += (
                f"  - {item['display_name'] or item['entity_id']}"
                f" [{item.get('entity_type') or 'unknown'}]: {claims}\n"
            )
            if changes:
                history_context += f"    recent changes: {changes}\n"
            if theses:
                history_context += f"    thesis: {theses}\n"
    if recent_event_memories:
        history_context += "\n近期事件记忆:\n"
        for item in recent_event_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            history_context += f"  - {item['title'] or item['event_id']}: {claims}\n"
            changes = "；".join(item.get("recent_changes") or [])
            if changes:
                history_context += f"    recent changes: {changes}\n"
    if recent_macro_memories:
        history_context += "\n近期宏观记忆:\n"
        for item in recent_macro_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            history_context += f"  - {item['topic'] or item['macro_id']}: {claims}\n"
            changes = "；".join(item.get("recent_changes") or [])
            if changes:
                history_context += f"    recent changes: {changes}\n"

    theme_hint = ""
    if predefined_themes:
        theme_hint = (
            "\n用户关注的主题方向（优先归入这些类别，也可创建新类别）:\n"
            f"  {', '.join(predefined_themes)}\n"
        )

    memory_update_example = """### MEMORY_UPDATE
```json
{
  "primary_themes": ["个股/公司", "地缘政治"],
  "secondary_themes": {
    "个股/公司": ["A股标的", "液冷/温控"],
    "地缘政治": ["伊朗", "霍尔木兹海峡"]
  },
  "account_notes": {
    "example_user": "经常发布半导体和AI基础设施链条观点，需要结合公告和新闻交叉确认。"
  },
  "signal_evaluations": [
    {
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "summary": "多条内容讨论液冷温控链条，但核心增量仍需验证。",
      "signal_type": "new_angle",
      "novelty_level": "medium",
      "evidence_strength": "single_source",
      "memory_action": "write",
      "alert_level": "watch",
      "confidence": 0.55,
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "entity_updates": [
    {
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "entity_id": "cn_equity:英维克",
      "entity_type": "equity",
      "display_name": "英维克",
      "claim": "市场讨论其液冷/温控业务可能受益于算力基础设施扩张。",
      "claim_type": "thesis",
      "verification_status": "plausible",
      "materiality": "medium",
      "what_changed": "相对旧记忆，本次增量是市场开始把液冷业务弹性和算力基础设施扩张联系起来。",
      "changed_since": "last_memory",
      "prior_claim_refs": ["entity_claim:previous-liquid-cooling-demand"],
      "signal_evaluation": {
        "signal_type": "new_angle",
        "novelty_level": "medium",
        "evidence_strength": "single_source",
        "memory_action": "write",
        "alert_level": "watch",
        "confidence": 0.6,
        "evidence_count": 1,
        "source_count": 1
      },
      "thesis_update": {
        "thesis_id": "yingweike_liquid_cooling_growth",
        "title": "液冷/温控业务增长 thesis",
        "direction": "bull",
        "thesis_status": "strengthened",
        "bull_case": ["算力基础设施扩张可能提升液冷/温控需求"],
        "bear_case": ["竞争加剧或项目节奏不及预期可能压缩估值和毛利率"],
        "key_watchpoints": ["订单验证", "毛利率变化", "大客户进展"],
        "invalidation_points": ["订单兑现不及预期", "毛利率持续下滑"],
        "catalysts": ["业绩预告", "大客户招标", "行业政策"],
        "what_changed": "本次新增的是温控业务弹性讨论，不是已验证订单事实。",
        "thesis_impact": "小幅增强多头 thesis，但仍需要公告或产业链数据确认。"
      },
      "why_it_matters": "影响市场对公司收入弹性和估值的预期。",
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "event_updates": [
    {
      "cluster_id": "xcluster:hormuz-20260428",
      "event_id": "geopolitics:iran-hormuz",
      "title": "伊朗-霍尔木兹海峡局势",
      "timestamp": "2026-04-14T10:00:00Z",
      "claim": "社交媒体开始交易海峡航运受阻风险，可能影响原油和航运资产预期。",
      "verification_status": "unverified",
      "importance": "high",
      "what_changed": "相对近期事件记忆，讨论焦点从地缘言论升级为航运受阻和油价影响。",
      "changed_since": "recent_run",
      "prior_claim_refs": [],
      "signal_evaluation": {
        "signal_type": "new_fact",
        "novelty_level": "high",
        "evidence_strength": "single_source",
        "memory_action": "write",
        "alert_level": "important",
        "confidence": 0.4
      },
      "evidence_item_ids": ["x:456"],
      "source_ids": ["x:example_user"]
    }
  ],
  "macro_updates": [],
  "source_assessments": [
    {
      "source_id": "x:example_user",
      "source_type": "commentary",
      "assessment": "对AI基础设施链条有持续观点输出，但需要公告和新闻交叉确认。",
      "source_profile": {
        "topic_strength": {"个股/公司": 0.7},
        "repeat_tendency": "medium",
        "confirmation_required": "high"
      }
    }
  ],
  "alert_candidates": [
    {
      "title": "液冷链条讨论出现中等新增角度",
      "reason": "相对既有记忆，新增关注温控业务弹性，但证据仍是单一社交来源。",
      "alert_level": "watch",
      "related_entity_ids": ["cn_equity:英维克"],
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "contradictions": [
    {
      "claim": "某账号称英维克液冷订单正在加速释放。",
      "conflicts_with": "另一来源称同类项目招标节奏放缓，且公司公告尚未验证订单加速。",
      "conflict_type": "source_conflict",
      "severity": "medium",
      "related_entity_ids": ["cn_equity:英维克"],
      "evidence_item_ids": ["x:123", "x:789"],
      "source_ids": ["x:example_user", "x:other_source"]
    }
  ]
}
```
"""

    return f"""你是一个偏金融与地缘风险的社交信号分析助手。

## 任务
将以下推文按主题归类，用中文输出结构化简报；同时抽取有价值的 claim，用于维护标的、事件、宏观和来源记忆。

## 输出要求
1. 先写可直接发送到 Telegram 的正文
2. 正文结束后，再追加 `### MEMORY_UPDATE`
3. `### MEMORY_UPDATE` 不给最终用户看，只用于提交到当前 memory backend
4. 如果本次没有新推文，明确写“本次无新推文”，不要编造主题

## 正文格式
### 📋 简报标题（一句话概括本次最重要的发现）

**🔖 主题1: [主题名]**
- [要点1] (@作者)
  链接: [推文链接]
  [如有图片，保留图片 URL]

**📊 趋势观察**
- 与上次报告相比的变化或新趋势

**🔍 发现推荐**
- 推荐关注的新账号及理由

## MEMORY_UPDATE 格式
{memory_update_example}

## 规则
1. 同一一级主题下合并不同账号的相关推文
2. 保留推文原始含义，不要过度简化
3. 保留所有图片 URL（用 [图片: URL] 格式）
4. 保留推文链接
5. 高互动推文可标注 🔥
6. `监控源` 与 `作者` 不同时，说明这是转推/转发线索
7. 尽量复用已有一级主题；只有真的出现新方向时再创建新的一级主题
8. 二级主题应该放在所属一级主题下面，不要把事件级名称直接当一级主题
9. 对金融标的、地缘事件、宏观趋势，先抽取 claim，再判断是否值得进入 memory
10. 明显虚假、重复且无增量、或低价值的信息不要写入 `entity_updates` / `event_updates` / `macro_updates`
11. 单一社交媒体来源通常只能标为 `unverified` 或 `plausible`；只有多源或官方信息支持时才标为 `confirmed`
12. `verification_status` 只能使用 `unverified`、`plausible`、`confirmed`、`superseded`、`rejected`
13. `claim_type` 可使用 `fact`、`thesis`、`rumor`、`signal`；观点和推演不要写成事实
14. 每个重要 claim 都应尽量带 `signal_evaluation`：`signal_type` 用 `new_fact`、`new_angle`、`repeat`、`noise`；`novelty_level` 用 `high`、`medium`、`low`、`none`；`evidence_strength` 用 `weak`、`single_source`、`multi_source`、`official`
15. `memory_action` 用 `write`、`merge`、`skip`、`supersede`、`reject`；重复、噪音或无新增价值的信息应该使用 `skip` 或不进入结构化更新
16. 同一事件簇可以共用 `cluster_id`，格式建议为 `xcluster:<主题>-<日期>`；没有把握时可以省略
17. 对写入 `entity_updates` / `event_updates` / `macro_updates` 的重要 claim，尽量填写 `what_changed`、`changed_since`、`prior_claim_refs`，说明相对旧记忆或近期 run 变化在哪里
18. `changed_since` 只能使用 `last_memory`、`recent_run`、`unknown`
19. `alert_candidates` 只表示候选告警，不等于一定发送；只有 `watch`、`important`、`urgent` 才值得写入
20. `contradictions` 只记录疑似冲突，不自动判定真假；`conflict_type` 用 `source_conflict`、`data_conflict`、`official_unverified`，`severity` 用 `low`、`medium`、`high`
21. `entity_updates` 用于股票、公司、行业链条等可命名对象；新标的可以直接创建
22. 如果标的信息会改变投资假设，在对应 `entity_updates` 内嵌 `thesis_update`，维护 `bull_case`、`bear_case`、`key_watchpoints`、`invalidation_points`、`catalysts`、`thesis_status`
23. `thesis_update.thesis_status` 用 `active`、`watch`、`strengthened`、`weakened`、`invalidated`、`superseded`；`direction` 用 `bull`、`bear`、`neutral`、`mixed`
24. `event_updates` 用于会随时间发展的事件，按时间线追加
25. `macro_updates` 用于宏观趋势、经济环境、流动性、能源价格等跨标的背景
26. `source_assessments` 用于记录账号或来源的可信度、偏见和需要确认程度，可带 `source_profile.topic_strength`、`repeat_tendency`、`confirmation_required`
27. `### MEMORY_UPDATE` 后面必须是严格合法的 JSON，JSON 不要写注释，不要写尾逗号，`account_notes` 的 key 使用不带 `@` 的用户名
{theme_hint}
## 历史上下文
{history_context if history_context else "（首次运行，无历史数据）"}

## 发现数据
{discovery_section or "（本次无额外发现）"}

## 本次推文数据
{raw_report}
"""


def build_collection_warning(results: list[FetchResult]) -> str | None:
    if not results:
        return "⚠️ 本次运行没有任何抓取结果。"

    if any(result.visible_tweet_count > 0 for result in results):
        return None

    status_counter = Counter(result.status for result in results)
    detail_lines = [f"  - @{result.username}: {result.status}" for result in results]
    details = "\n".join(detail_lines)

    if status_counter.get(STATUS_LOGIN_WALL) == len(results):
        return (
            "⚠️ 所有账号都落到了 X 登录墙。\n"
            "账号状态:\n"
            f"{details}\n"
            "优先检查 cookies.json 是否过期，并重新导出浏览器 cookies。"
        )

    if status_counter.get(STATUS_ERROR) == len(results):
        return (
            "⚠️ 所有账号抓取都失败了。\n"
            "账号状态:\n"
            f"{details}\n"
            "请检查 Playwright/Chromium、网络连通性，以及 X 页面结构是否变化。"
        )

    return (
        "⚠️ 本次运行没有在任何账号页面看到可见推文。\n"
        "账号状态:\n"
        f"{details}\n"
        "可能原因包括 cookies 失效、页面结构变化、账号受限，或网络异常。"
    )


def empty_memory_update() -> dict[str, Any]:
    return {
        "primary_themes": [],
        "secondary_themes": {},
        "account_notes": {},
        "signal_evaluations": [],
        "entity_updates": [],
        "event_updates": [],
        "macro_updates": [],
        "source_assessments": [],
        "alert_candidates": [],
        "contradictions": [],
    }


def coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique_preserving_order(
        [str(item).strip() for item in value if str(item).strip()]
    )


def coerce_secondary_mapping(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, items in value.items():
        primary_theme = str(key).strip()
        if not primary_theme:
            continue
        normalized[primary_theme] = coerce_string_list(items)
    return normalized


def coerce_account_notes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, note in value.items():
        username = normalize_account_name(str(key))
        note_text = str(note).strip()
        if username and note_text:
            normalized[username] = note_text
    return normalized


def coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def coerce_number_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, raw_number in value.items():
        name = clean_text(key)
        number = coerce_float_or_none(raw_number)
        if name and number is not None:
            normalized[name] = number
    return normalized


def coerce_signal_evaluations(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        if payload.get("cluster_id") is not None:
            payload["cluster_id"] = clean_text(payload.get("cluster_id"))
        normalized.append(payload)
    return normalized


def coerce_alert_candidates(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        payload["title"] = clean_text(payload.get("title"))
        payload["reason"] = clean_text(payload.get("reason"))
        payload["alert_level"] = normalize_alert_level(payload.get("alert_level"))
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        payload["related_entity_ids"] = coerce_string_list(
            payload.get("related_entity_ids")
        )
        payload["related_event_ids"] = coerce_string_list(
            payload.get("related_event_ids")
        )
        payload["evidence_item_ids"] = coerce_string_list(
            payload.get("evidence_item_ids")
        )
        payload["source_ids"] = coerce_string_list(payload.get("source_ids"))
        if payload["title"] or payload["reason"]:
            normalized.append(payload)
    return normalized


def coerce_contradictions(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        payload["claim"] = clean_text(payload.get("claim") or payload.get("summary"))
        payload["conflicts_with"] = clean_text(
            payload.get("conflicts_with") or payload.get("conflict")
        )
        payload["conflict_type"] = normalize_conflict_type(
            payload.get("conflict_type")
        )
        payload["severity"] = normalize_contradiction_severity(
            payload.get("severity")
        )
        payload["evidence_item_ids"] = coerce_string_list(
            payload.get("evidence_item_ids")
        )
        payload["source_ids"] = coerce_string_list(payload.get("source_ids"))
        payload["related_entity_ids"] = coerce_string_list(
            payload.get("related_entity_ids")
        )
        payload["related_event_ids"] = coerce_string_list(
            payload.get("related_event_ids")
        )
        payload["related_macro_ids"] = coerce_string_list(
            payload.get("related_macro_ids")
        )
        payload["related_thesis_ids"] = coerce_string_list(
            payload.get("related_thesis_ids")
        )
        payload["memory_action"] = normalize_memory_action(
            payload.get("memory_action") or payload.get("action")
        )
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        if payload["claim"] and payload["conflicts_with"]:
            normalized.append(payload)
    return normalized


def extract_memory_update_object(summary_text: str) -> dict[str, Any] | None:
    lines = summary_text.splitlines()
    start_index: int | None = None

    for index, line in enumerate(lines):
        if re.match(r"^\s*#{0,6}\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break
        if re.match(r"^\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break

    if start_index is None:
        return None

    block_text = "\n".join(lines[start_index:]).strip()
    if not block_text:
        return None

    fenced_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        block_text,
        re.IGNORECASE | re.DOTALL,
    )
    candidate = fenced_match.group(1).strip() if fenced_match else block_text
    json_start = candidate.find("{")
    if json_start < 0:
        return None

    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(candidate[json_start:])
    if isinstance(parsed, dict):
        return parsed
    return None


def parse_legacy_memory_update(summary_text: str) -> dict[str, Any]:
    lines = summary_text.splitlines()
    start_index = 0

    for index, line in enumerate(lines):
        if re.match(r"^\s*#{0,6}\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break
        if re.match(r"^\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break

    block_lines = lines[start_index:]
    primary_themes: list[str] = []
    secondary_themes: dict[str, list[str]] = {}
    account_notes: dict[str, str] = {}
    in_account_notes = False
    in_secondary_themes = False
    current_user: str | None = None
    current_primary_theme: str | None = None

    def parse_theme_list(theme_text: str) -> list[str]:
        parts = re.split(r"[,，;|｜]+", theme_text)
        return unique_preserving_order(
            [part.strip() for part in parts if part.strip()]
        )

    for raw_line in block_lines:
        line = raw_line.strip()
        if not line:
            current_user = None
            current_primary_theme = None
            continue

        primary_match = re.match(
            r"^(?:PRIMARY_THEMES|THEMES)\s*:\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if primary_match:
            theme_text = primary_match.group(1).strip()
            if theme_text:
                primary_themes = parse_theme_list(theme_text)
            continue

        if re.match(r"^SECONDARY_THEMES\s*:\s*$", line, re.IGNORECASE):
            in_secondary_themes = True
            in_account_notes = False
            current_primary_theme = None
            continue

        if re.match(r"^ACCOUNT_NOTES\s*:\s*$", line, re.IGNORECASE):
            in_account_notes = True
            in_secondary_themes = False
            current_user = None
            continue

        if in_secondary_themes:
            secondary_match = re.match(r"^(.+?)\s*:\s*(.*)$", line)
            if secondary_match:
                current_primary_theme = secondary_match.group(1).strip()
                secondary_text = secondary_match.group(2).strip()
                if current_primary_theme:
                    primary_themes = unique_preserving_order(
                        primary_themes + [current_primary_theme]
                    )
                    secondary_themes[current_primary_theme] = parse_theme_list(
                        secondary_text
                    )
                continue
            bullet_match = re.match(r"^-+\s*(.+)$", line)
            if bullet_match and current_primary_theme:
                existing = secondary_themes.get(current_primary_theme, [])
                extra = parse_theme_list(bullet_match.group(1).strip())
                secondary_themes[current_primary_theme] = unique_preserving_order(
                    existing + extra
                )
                continue

        if not in_account_notes:
            continue

        note_match = re.match(r"^@?([A-Za-z0-9_]{1,15})\s*:\s*(.+)$", line)
        if note_match:
            current_user = normalize_account_name(note_match.group(1))
            account_notes[current_user] = note_match.group(2).strip()
            continue

        if current_user:
            account_notes[current_user] = (
                account_notes[current_user] + " " + line
            ).strip()

    parsed = empty_memory_update()
    parsed.update({
        "primary_themes": primary_themes,
        "secondary_themes": secondary_themes,
        "account_notes": account_notes,
    })
    return parsed


def parse_memory_update(summary_text: str) -> dict[str, Any]:
    try:
        payload = extract_memory_update_object(summary_text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        parsed = empty_memory_update()
        parsed["primary_themes"] = coerce_string_list(payload.get("primary_themes"))
        parsed["secondary_themes"] = coerce_secondary_mapping(
            payload.get("secondary_themes")
        )
        parsed["account_notes"] = coerce_account_notes(payload.get("account_notes"))
        parsed["signal_evaluations"] = coerce_signal_evaluations(
            payload.get("signal_evaluations")
        )
        parsed["entity_updates"] = coerce_dict_list(payload.get("entity_updates"))
        parsed["event_updates"] = coerce_dict_list(payload.get("event_updates"))
        parsed["macro_updates"] = coerce_dict_list(payload.get("macro_updates"))
        parsed["source_assessments"] = coerce_dict_list(
            payload.get("source_assessments")
        )
        parsed["alert_candidates"] = coerce_alert_candidates(
            payload.get("alert_candidates")
        )
        parsed["contradictions"] = coerce_contradictions(
            payload.get("contradictions")
        )
        if (
            parsed["primary_themes"]
            or parsed["secondary_themes"]
            or parsed["account_notes"]
            or parsed["signal_evaluations"]
            or parsed["entity_updates"]
            or parsed["event_updates"]
            or parsed["macro_updates"]
            or parsed["source_assessments"]
            or parsed["alert_candidates"]
            or parsed["contradictions"]
        ):
            return parsed

    return parse_legacy_memory_update(summary_text)


def build_memory_update_id(
    summary_text: str,
    summary_path: Path,
    run_id: str | None = None,
) -> str:
    identity = {
        "summary_sha256": hashlib.sha256(
            summary_text.encode("utf-8")
        ).hexdigest(),
    }
    if run_id:
        identity["run_id"] = run_id
    else:
        identity["summary_path"] = str(summary_path)
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"mu_{digest[:20]}"


async def collect(config_path: str) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "请先安装: pip install playwright pyyaml --break-system-packages "
            "&& playwright install chromium --with-deps"
        )
        return 1

    config = load_config(config_path)
    accounts = config["accounts"]
    if not accounts:
        print("❌ 请在 config.yaml 中配置要监控的账号")
        return 1

    state = StateManager(
        config["state_file"],
        legacy_paths=build_legacy_state_paths(
            config["base_dir"],
            config["state_file"],
        ),
    )
    normalizer = ThemeNormalizer(
        canonical_primary_themes=config.get("themes", []),
        alias_config=config.get("theme_aliases", {}),
        secondary_alias_config=config.get("secondary_theme_aliases", {}),
    )
    memory_store = create_memory_backend(config, normalizer=normalizer)
    with memory_store.lock():
        memory_store.migrate_legacy_state(state)
        if not memory_store.index_path.exists():
            memory_store.rebuild_index()
    output_dir = Path(config["output_dir"])
    latest_run_file = Path(config["latest_run_file"])
    base_dir = Path(config["base_dir"])

    last_run = state.data.get("last_run")
    if last_run:
        print(f"📅 上次运行: {last_run}")

    print(f"🚀 开始监控 {len(accounts)} 个账号: {', '.join('@' + item for item in accounts)}")

    fetch_results: list[FetchResult] = []
    async with async_playwright() as pw:
        fetcher = PlaywrightFetcher(
            cookies_file=Path(config["auth"]["cookies_file"]),
            debug_dir=base_dir,
        )
        await fetcher.start(pw)
        try:
            for index, username in enumerate(accounts):
                result = await fetcher.fetch_user_tweets(
                    username=username,
                    state=state,
                    max_tweets=config["tweets_per_account"],
                    scroll_count=config.get("scroll_count", 5),
                )
                fetch_results.append(result)
                if index < len(accounts) - 1:
                    delay = config.get("delay_between_accounts", 5)
                    print(f"  ⏳ 等待 {delay} 秒...")
                    await asyncio.sleep(delay)
        finally:
            await fetcher.close()

    account_tweets = {result.username: result.tweets for result in fetch_results}
    all_tweets = [
        tweet
        for result in fetch_results
        for tweet in result.tweets
    ]

    warning = build_collection_warning(fetch_results)
    if warning:
        print(f"\n{warning}")

    discovery = DiscoveryEngine(
        accounts,
        config["discovery"]["min_interactions"],
    )
    if config["discovery"]["enabled"]:
        discovery.process(all_tweets)
    recommendations = discovery.get_recommendations()
    keywords = extract_keywords(all_tweets)

    raw_report = format_raw_report(account_tweets)
    discovery_section = format_discovery_section(recommendations, keywords)
    prompt = build_llm_prompt(
        raw_report=raw_report,
        discovery_section=discovery_section,
        memory_store=memory_store,
        predefined_themes=config.get("themes", []),
    )

    now = utc_now()
    run_id = timestamp_slug(now)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    collected_at = now.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = build_artifact_paths(output_dir, run_id)
    collector_batch = build_x_collector_batch(
        run_id=run_id,
        collected_at=collected_at,
        accounts=accounts,
        fetch_results=fetch_results,
        warning=warning,
        config_path=config["config_path"],
    )

    data_payload = {
        "run_id": run_id,
        "timestamp": now_str,
        "config_path": config["config_path"],
        "collector_batch_schema": COLLECTOR_BATCH_SCHEMA_VERSION,
        "collector_item_schema": COLLECTOR_ITEM_SCHEMA_VERSION,
        "collector_batch_path": str(artifact_paths["collector_batch"]),
        "account_results": [asdict(result) for result in fetch_results],
        "account_tweets": account_tweets,
        "recommendations": recommendations,
        "keywords": keywords,
        "warning": warning,
    }
    atomic_write_json(artifact_paths["collector_batch"], collector_batch)
    atomic_write_json(artifact_paths["data"], data_payload)
    atomic_write_text(artifact_paths["prompt"], prompt, encoding="utf-8")
    full_report = f"📊 X 监控报告 — {now_str}\n\n{raw_report}\n{discovery_section}"
    atomic_write_text(artifact_paths["report"], full_report, encoding="utf-8")

    warning_path: str | None = None
    if warning:
        atomic_write_text(artifact_paths["warning"], warning, encoding="utf-8")
        warning_path = str(artifact_paths["warning"])

    state.save(update_last_run=False)

    latest_payload = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "config_path": config["config_path"],
        "paths": {
            "data": str(artifact_paths["data"]),
            "collector_batch": str(artifact_paths["collector_batch"]),
            "prompt": str(artifact_paths["prompt"]),
            "report": str(artifact_paths["report"]),
            "summary": str(artifact_paths["summary"]),
            "memory_update": str(artifact_paths["memory_update"]),
            "memory_index": str(memory_store.index_path),
            "state": config["state_file"],
            "warning": warning_path,
            "memory_dir": config["memory_dir"],
        },
        "memory_backend": config["memory_backend"],
        "summary": {
            "new_tweet_count": len(all_tweets),
            "recommendation_count": len(recommendations),
            "keyword_count": len(keywords),
        },
        "account_results": [asdict(result) for result in fetch_results],
        "memory_update_applied": False,
    }
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"\n{'=' * 60}")
    print(f"📊 X 监控报告 — {now_str}")
    print(f"   新推文: {len(all_tweets)} 条")
    print(
        "   账号: "
        + ", ".join(
            f"@{result.username}({result.new_tweet_count})"
            for result in fetch_results
        )
    )
    if recommendations:
        print(f"   发现: {', '.join('@' + item['username'] for item in recommendations[:3])}")
    if keywords:
        print(f"   关键词: {', '.join(keywords[:5])}")
    print(f"{'=' * 60}")
    print(f"\n📁 数据: {artifact_paths['data']}")
    print(f"📦 Collector Batch: {artifact_paths['collector_batch']}")
    print(f"📝 Prompt: {artifact_paths['prompt']}")
    print(f"📄 报告: {artifact_paths['report']}")
    print(f"🧭 最新索引: {latest_run_file}")
    if warning_path:
        print(f"⚠️ 告警: {warning_path}")

    return 0


def latest(config_path: str, field: str | None) -> int:
    config = load_config(config_path)
    latest_run_file = Path(config["latest_run_file"])
    payload = read_latest_manifest(latest_run_file)
    if payload is None:
        print(f"未找到 latest manifest: {latest_run_file}")
        return 1

    if not field:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if field == "manifest":
        print(str(latest_run_file))
        return 0

    if field == "new_tweet_count":
        print(payload.get("summary", {}).get("new_tweet_count", 0))
        return 0

    if field == "memory_dir":
        print(payload.get("paths", {}).get("memory_dir") or "")
        return 0

    if field == "memory_index":
        print(payload.get("paths", {}).get("memory_index") or "")
        return 0

    if field == "memory_backend":
        print(payload.get("memory_backend") or "file")
        return 0

    if field == "state":
        print(payload.get("paths", {}).get("state") or "")
        return 0

    if field in {
        "data",
        "collector_batch",
        "prompt",
        "report",
        "summary",
        "memory_update",
        "warning",
    }:
        value = payload.get("paths", {}).get(field) or ""
        print(value)
        return 0

    print(f"不支持的 field: {field}")
    return 1


def apply_memory(config_path: str, summary_file: str) -> int:
    config = load_config(config_path)
    base_dir = Path(config["base_dir"])
    summary_path = resolve_path(base_dir, summary_file)
    if not summary_path.exists():
        print(f"summary 文件不存在: {summary_path}")
        return 1

    summary_text = summary_path.read_text(encoding="utf-8")
    parsed = parse_memory_update(summary_text)
    if (
        not parsed["primary_themes"]
        and not parsed["secondary_themes"]
        and not parsed["account_notes"]
        and not parsed["signal_evaluations"]
        and not parsed["entity_updates"]
        and not parsed["event_updates"]
        and not parsed["macro_updates"]
        and not parsed["source_assessments"]
        and not parsed["alert_candidates"]
        and not parsed["contradictions"]
    ):
        print("未在 summary 中找到可解析的 MEMORY_UPDATE")
        return 1

    latest_run_file = Path(config["latest_run_file"])
    latest_payload = read_latest_manifest(latest_run_file) or {}
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    stored_summary_path = summary_path
    preferred_summary_path = (
        Path(latest_payload.get("paths", {}).get("summary"))
        if latest_payload.get("paths", {}).get("summary")
        else None
    )
    if preferred_summary_path:
        should_use_preferred_path = (
            preferred_summary_path.resolve() == summary_path.resolve()
            or not preferred_summary_path.exists()
            or (
                latest_payload.get("run_id")
                and preferred_summary_path.name.startswith(
                    f"summary_{latest_payload['run_id']}"
                )
            )
        )
        if should_use_preferred_path and preferred_summary_path.resolve() != summary_path.resolve():
            atomic_write_text(preferred_summary_path, summary_text, encoding="utf-8")
            stored_summary_path = preferred_summary_path
        elif preferred_summary_path.resolve() == summary_path.resolve():
            stored_summary_path = preferred_summary_path

    update_id = build_memory_update_id(
        summary_text=summary_text,
        summary_path=stored_summary_path.resolve(),
        run_id=(
            str(latest_payload.get("run_id"))
            if latest_payload.get("run_id")
            else None
        ),
    )

    state = StateManager(
        config["state_file"],
        legacy_paths=build_legacy_state_paths(
            config["base_dir"],
            config["state_file"],
        ),
    )
    normalizer = ThemeNormalizer(
        canonical_primary_themes=config.get("themes", []),
        alias_config=config.get("theme_aliases", {}),
        secondary_alias_config=config.get("secondary_theme_aliases", {}),
    )
    memory_store = create_memory_backend(config, normalizer=normalizer)
    seen_at = utc_now().isoformat()
    theme_updates = 0
    account_updates = 0
    entity_updates = 0
    event_updates = 0
    macro_updates = 0
    source_updates = 0
    contradiction_updates = 0
    with memory_store.lock():
        memory_store.migrate_legacy_state(state)

        normalized_secondary_mapping = memory_store.normalizer.normalize_secondary_mapping(
            parsed["secondary_themes"]
        )
        normalized_primary = memory_store.normalizer.normalize_primary_themes(
            parsed["primary_themes"] + list(normalized_secondary_mapping.keys())
        )

        for primary_theme in normalized_primary:
            if memory_store.update_theme_memory(
                primary_theme=primary_theme,
                secondary_themes=normalized_secondary_mapping.get(primary_theme, []),
                seen_at=seen_at,
                update_id=update_id,
            ):
                theme_updates += 1

        for username, note in parsed["account_notes"].items():
            if memory_store.update_account_note(
                username=username,
                note=note,
                seen_at=seen_at,
                update_id=update_id,
                primary_themes=normalized_primary,
                secondary_themes=normalized_secondary_mapping,
            ):
                account_updates += 1

        for update in parsed["entity_updates"]:
            if memory_store.update_entity_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                entity_updates += 1

        for update in parsed["event_updates"]:
            if memory_store.update_event_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                event_updates += 1

        for update in parsed["macro_updates"]:
            if memory_store.update_macro_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                macro_updates += 1

        for update in parsed["source_assessments"]:
            if memory_store.update_source_assessment(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                source_updates += 1

        for update in parsed["contradictions"]:
            if memory_store.update_contradiction_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                contradiction_updates += 1

        if (
            theme_updates
            or account_updates
            or entity_updates
            or event_updates
            or macro_updates
            or source_updates
            or contradiction_updates
            or not memory_store.index_path.exists()
        ):
            memory_store.rebuild_index()

    state.save(update_last_run=False)

    memory_update_path = (
        Path(latest_payload.get("paths", {}).get("memory_update"))
        if latest_payload.get("paths", {}).get("memory_update")
        else output_dir / f"memory_update_{timestamp_slug()}.json"
    )
    memory_update_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "update_id": update_id,
        "applied_at": seen_at,
        "summary_file": str(stored_summary_path),
        "state_file": config["state_file"],
        "primary_themes": normalized_primary,
        "secondary_themes": normalized_secondary_mapping,
        "account_notes": parsed["account_notes"],
        "signal_evaluations": parsed["signal_evaluations"],
        "entity_updates": parsed["entity_updates"],
        "event_updates": parsed["event_updates"],
        "macro_updates": parsed["macro_updates"],
        "source_assessments": parsed["source_assessments"],
        "alert_candidates": parsed["alert_candidates"],
        "alert_candidate_count": len(parsed["alert_candidates"]),
        "contradictions": parsed["contradictions"],
        "contradiction_count": len(parsed["contradictions"]),
        "memory_dir": config["memory_dir"],
        "memory_backend": config["memory_backend"],
        "memory_index": str(memory_store.index_path),
        "theme_updates": theme_updates,
        "account_updates": account_updates,
        "entity_updates_applied": entity_updates,
        "event_updates_applied": event_updates,
        "macro_updates_applied": macro_updates,
        "source_updates_applied": source_updates,
        "contradiction_updates_applied": contradiction_updates,
        "already_applied": (
            theme_updates == 0
            and account_updates == 0
            and entity_updates == 0
            and event_updates == 0
            and macro_updates == 0
            and source_updates == 0
            and contradiction_updates == 0
        ),
    }
    atomic_write_json(memory_update_path, payload)

    latest_payload.setdefault("paths", {})
    latest_payload["paths"]["summary"] = str(stored_summary_path)
    latest_payload["paths"]["memory_update"] = str(memory_update_path)
    latest_payload["paths"]["memory_index"] = str(memory_store.index_path)
    latest_payload["paths"]["state"] = config["state_file"]
    latest_payload["memory_backend"] = config["memory_backend"]
    latest_payload["memory_update_applied"] = True
    latest_payload["memory_update"] = payload
    if "summary" not in latest_payload:
        latest_payload["summary"] = {}
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"🧠 已更新记忆: {config['state_file']}")
    print(f"📝 Summary: {stored_summary_path}")
    print(f"📦 MEMORY_UPDATE: {memory_update_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Signal Radar for Hermes")
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR / "config.yaml"),
        help="配置文件路径",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("collect", help="抓取推文并生成 artifacts")

    latest_parser = subparsers.add_parser("latest", help="读取 latest_run.json")
    latest_parser.add_argument(
        "--field",
        choices=[
            "manifest",
            "data",
            "collector_batch",
            "prompt",
            "report",
            "summary",
            "memory_update",
            "memory_dir",
            "memory_backend",
            "memory_index",
            "state",
            "warning",
            "new_tweet_count",
        ],
        help="仅读取某个字段",
    )

    apply_parser = subparsers.add_parser(
        "apply-memory",
        help="解析 summary 中的 MEMORY_UPDATE 并提交到当前 memory backend",
    )
    apply_parser.add_argument(
        "--summary-file",
        required=True,
        help="包含 MEMORY_UPDATE 的总结文件路径",
    )

    return parser


def parse_cli_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    argv = sys.argv[1:]
    extracted_config: str | None = None
    cleaned_argv: list[str] = []
    index = 0

    while index < len(argv):
        arg = argv[index]
        if arg == "--config":
            if index + 1 >= len(argv):
                parser.error("--config 需要一个路径值")
            extracted_config = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            extracted_config = arg.split("=", 1)[1]
            index += 1
            continue
        cleaned_argv.append(arg)
        index += 1

    args = parser.parse_args(cleaned_argv)
    if extracted_config is not None:
        args.config = extracted_config
    return args


async def async_main(args: argparse.Namespace) -> int:
    if args.command in (None, "collect"):
        return await collect(args.config)
    if args.command == "latest":
        return latest(args.config, args.field)
    if args.command == "apply-memory":
        return apply_memory(args.config, args.summary_file)
    print(f"未知命令: {args.command}")
    return 1


def main() -> int:
    parser = build_parser()
    args = parse_cli_args(parser)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
