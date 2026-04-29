from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .schemas import (
    build_signal_evaluation,
    clean_text,
    coerce_dict_list,
    coerce_string_list,
    normalize_account_name,
    normalize_alert_level,
    normalize_changed_dimensions,
    normalize_conflict_type,
    normalize_contradiction_severity,
    normalize_information_event_type,
    normalize_memory_action,
    normalize_relation_to_memory,
    normalize_time_horizon,
    normalize_verification_status,
    stable_event_cluster_id,
    stable_information_unit_id,
    unique_preserving_order,
)


def empty_memory_update() -> dict[str, Any]:
    return {
        "primary_themes": [],
        "secondary_themes": {},
        "account_notes": {},
        "information_units": [],
        "event_clusters": [],
        "signal_evaluations": [],
        "entity_updates": [],
        "event_updates": [],
        "macro_updates": [],
        "source_assessments": [],
        "alert_candidates": [],
        "contradictions": [],
    }


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


def coerce_signal_evaluations(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        if payload.get("cluster_id") is not None:
            payload["cluster_id"] = clean_text(payload.get("cluster_id"))
        normalized.append(payload)
    return normalized


def coerce_event_clusters(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        payload["cluster_id"] = stable_event_cluster_id(payload)
        payload["title"] = clean_text(payload.get("title"))
        payload["summary"] = clean_text(payload.get("summary"))
        payload["theme"] = clean_text(
            payload.get("theme") or payload.get("primary_theme")
        )
        payload["secondary_themes"] = coerce_string_list(
            payload.get("secondary_themes")
        )
        payload["source_quality"] = clean_text(payload.get("source_quality"))
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        payload["evidence_item_ids"] = coerce_string_list(
            payload.get("evidence_item_ids")
            or payload.get("tweet_ids")
            or payload.get("item_ids")
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
        payload["what_changed"] = clean_text(payload.get("what_changed"))
        if payload["title"] or payload["summary"] or payload["evidence_item_ids"]:
            normalized.append(payload)
    return normalized


def coerce_information_units(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in coerce_dict_list(value):
        payload = dict(item)
        affected_entities = coerce_string_list(
            payload.get("affected_entities") or payload.get("related_entity_ids")
        )
        affected_themes = coerce_string_list(
            payload.get("affected_themes") or payload.get("secondary_themes")
        )
        payload["information_unit_id"] = stable_information_unit_id(payload)
        payload["cluster_id"] = clean_text(payload.get("cluster_id"))
        payload["event_type"] = normalize_information_event_type(
            payload.get("event_type") or payload.get("type")
        )
        payload["relation_to_memory"] = normalize_relation_to_memory(
            payload.get("relation_to_memory")
            or payload.get("memory_relation")
            or payload.get("relation")
        )
        payload["subject"] = clean_text(
            payload.get("subject")
            or payload.get("target")
            or payload.get("entity")
            or payload.get("topic")
        )
        payload["claim"] = clean_text(
            payload.get("claim") or payload.get("summary") or payload.get("observation")
        )
        payload["what_changed"] = clean_text(payload.get("what_changed"))
        payload["changed_dimensions"] = normalize_changed_dimensions(
            payload.get("changed_dimensions") or payload.get("dimensions")
        )
        payload["affected_entities"] = affected_entities
        payload["affected_themes"] = affected_themes
        payload["related_entity_ids"] = coerce_string_list(
            payload.get("related_entity_ids") or affected_entities
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
        payload["market_mechanism"] = clean_text(payload.get("market_mechanism"))
        payload["time_horizon"] = normalize_time_horizon(payload.get("time_horizon"))
        payload["verification_status"] = normalize_verification_status(
            payload.get("verification_status")
        )
        payload["evidence_item_ids"] = coerce_string_list(
            payload.get("evidence_item_ids")
            or payload.get("tweet_ids")
            or payload.get("item_ids")
        )
        payload["source_ids"] = coerce_string_list(payload.get("source_ids"))
        payload["signal_evaluation"] = build_signal_evaluation(payload)
        if payload["claim"] or payload["subject"] or payload["evidence_item_ids"]:
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
        parsed["information_units"] = coerce_information_units(
            payload.get("information_units")
        )
        parsed["event_clusters"] = coerce_event_clusters(payload.get("event_clusters"))
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
            or parsed["information_units"]
            or parsed["event_clusters"]
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
        "summary_path": str(summary_path),
        "run_id": run_id or "",
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"mu_{digest[:20]}"
