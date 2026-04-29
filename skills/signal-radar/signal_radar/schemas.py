from __future__ import annotations

import hashlib
import json
import re
from typing import Any


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
    "confirmation",
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
INFORMATION_EVENT_TYPES = {
    "material_price_change",
    "supply_disruption",
    "company_order",
    "geopolitical_update",
    "policy_signal",
    "macro_data",
    "market_rumor",
    "official_disclosure",
    "market_price_action",
    "fund_flow",
    "earnings_update",
    "industry_chain_signal",
    "other",
    "unknown",
}
RELATION_TO_MEMORY_VALUES = {
    "new_event",
    "event_update",
    "confirmation",
    "contradiction",
    "repeat",
    "noise",
    "unknown",
}
CHANGED_DIMENSIONS = {
    "price",
    "supply",
    "demand",
    "orders",
    "capacity",
    "policy",
    "risk_level",
    "liquidity",
    "rates",
    "earnings",
    "valuation",
    "sentiment",
    "positioning",
    "timeline",
    "official_status",
    "market_expectation",
    "other",
}
TIME_HORIZONS = {
    "intraday",
    "days",
    "weeks",
    "months",
    "quarters",
    "years",
    "unknown",
}
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
SOURCE_TYPES = {
    "primary",
    "official",
    "analyst",
    "aggregator",
    "trader",
    "media",
    "commentary",
    "noise",
    "unknown",
}
CONFIRMATION_REQUIRED_LEVELS = {
    "none",
    "low",
    "medium",
    "high",
    "multi_source",
    "official",
    "unknown",
}
REPEAT_TENDENCIES = {"low", "medium", "high", "unknown"}
STYLE_TENDENCIES = {"low", "medium", "high", "unknown"}
SOURCE_METRIC_KEYS = {
    "assessment_count",
    "observed_count",
    "valuable_count",
    "high_novelty_count",
    "repeat_count",
    "noise_count",
    "skipped_count",
    "contradiction_count",
    "alert_count",
}
SOURCE_CONTRIBUTION_HISTORY_LIMIT = 50
SOURCE_OBSERVATION_ID_LIMIT = 200
SKIP_MEMORY_ACTIONS = {"ignore", "ignored", "reject", "rejected", "skip", "no_op", "noop"}
SKIP_NOVELTY_VALUES = {"duplicate", "duplicated", "none", "low_value", "no_value"}
SKIP_SIGNAL_TYPES = {"noise"}


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


def coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique_preserving_order(
        [str(item).strip() for item in value if str(item).strip()]
    )


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
        "confirm": "confirmation",
        "confirmed_signal": "confirmation",
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


def normalize_information_event_type(value: Any) -> str:
    event_type = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "material_price": "material_price_change",
        "raw_material_price": "material_price_change",
        "commodity_price": "material_price_change",
        "price_change": "material_price_change",
        "mine_shutdown": "supply_disruption",
        "production_halt": "supply_disruption",
        "factory_shutdown": "supply_disruption",
        "supply_cut": "supply_disruption",
        "order": "company_order",
        "contract": "company_order",
        "customer_order": "company_order",
        "geopolitics": "geopolitical_update",
        "war": "geopolitical_update",
        "conflict": "geopolitical_update",
        "tweet": "policy_signal",
        "trump_tweet": "policy_signal",
        "fed": "policy_signal",
        "fomc": "policy_signal",
        "policy": "policy_signal",
        "data": "macro_data",
        "economic_data": "macro_data",
        "rumor": "market_rumor",
        "official": "official_disclosure",
        "announcement": "official_disclosure",
        "price_action": "market_price_action",
        "flow": "fund_flow",
        "earnings": "earnings_update",
        "industry_chain": "industry_chain_signal",
        "supply_chain": "industry_chain_signal",
    }
    event_type = aliases.get(event_type, event_type)
    return event_type if event_type in INFORMATION_EVENT_TYPES else "unknown"


def normalize_relation_to_memory(value: Any) -> str:
    relation = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "new": "new_event",
        "new_fact": "new_event",
        "new_angle": "new_event",
        "update": "event_update",
        "same_event_update": "event_update",
        "follow_up": "event_update",
        "confirm": "confirmation",
        "confirmed": "confirmation",
        "conflict": "contradiction",
        "source_conflict": "contradiction",
        "duplicate": "repeat",
        "duplicated": "repeat",
        "low_value": "noise",
    }
    relation = aliases.get(relation, relation)
    return relation if relation in RELATION_TO_MEMORY_VALUES else "unknown"


def normalize_changed_dimension(value: Any) -> str:
    dimension = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "material_price": "price",
        "commodity_price": "price",
        "raw_material_price": "price",
        "supply_cut": "supply",
        "production": "capacity",
        "production_capacity": "capacity",
        "order": "orders",
        "contract": "orders",
        "fed_rate": "rates",
        "interest_rate": "rates",
        "risk": "risk_level",
        "geopolitical_risk": "risk_level",
        "expectation": "market_expectation",
        "official": "official_status",
    }
    dimension = aliases.get(dimension, dimension)
    if dimension in CHANGED_DIMENSIONS:
        return dimension
    return dimension if dimension else ""


def normalize_changed_dimensions(value: Any) -> list[str]:
    return unique_preserving_order(
        [
            dimension
            for dimension in (
                normalize_changed_dimension(item) for item in coerce_string_list(value)
            )
            if dimension
        ]
    )


def normalize_time_horizon(value: Any) -> str:
    horizon = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "day": "days",
        "daily": "days",
        "week": "weeks",
        "weekly": "weeks",
        "month": "months",
        "monthly": "months",
        "quarter": "quarters",
        "quarterly": "quarters",
        "year": "years",
        "yearly": "years",
    }
    horizon = aliases.get(horizon, horizon)
    return horizon if horizon in TIME_HORIZONS else "unknown"


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


def normalize_source_type(value: Any) -> str:
    source_type = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "first_hand": "primary",
        "first_party": "primary",
        "company": "official",
        "gov": "official",
        "government": "official",
        "news": "media",
        "journalist": "media",
        "commentator": "commentary",
        "opinion": "commentary",
        "pump": "noise",
        "spam": "noise",
    }
    source_type = aliases.get(source_type, source_type)
    return source_type if source_type in SOURCE_TYPES else "unknown"


def normalize_confirmation_required(value: Any) -> str:
    level = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "no": "none",
        "false": "none",
        "single": "low",
        "some": "medium",
        "strong": "high",
        "multi": "multi_source",
        "multiple": "multi_source",
        "official_confirmation": "official",
    }
    level = aliases.get(level, level)
    return level if level in CONFIRMATION_REQUIRED_LEVELS else "unknown"


def normalize_repeat_tendency(value: Any) -> str:
    tendency = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "rare": "low",
        "little": "low",
        "normal": "medium",
        "often": "high",
        "frequent": "high",
    }
    tendency = aliases.get(tendency, tendency)
    return tendency if tendency in REPEAT_TENDENCIES else "unknown"


def normalize_style_tendency(value: Any) -> str:
    tendency = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "no": "low",
        "false": "low",
        "rare": "low",
        "little": "low",
        "normal": "medium",
        "some": "medium",
        "yes": "high",
        "true": "high",
        "often": "high",
        "frequent": "high",
    }
    tendency = aliases.get(tendency, tendency)
    return tendency if tendency in STYLE_TENDENCIES else "unknown"


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


def is_high_novelty_signal(signal_evaluation: dict[str, Any]) -> bool:
    return signal_evaluation.get("novelty_level") == "high"


def normalize_source_metrics(
    value: Any,
    seed_valuable_count: Any = None,
) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    metrics: dict[str, int] = {}
    for key in sorted(SOURCE_METRIC_KEYS):
        metrics[key] = coerce_non_negative_int(raw.get(key)) or 0

    seed_count = coerce_non_negative_int(seed_valuable_count)
    if seed_count is not None:
        metrics["valuable_count"] = max(metrics["valuable_count"], seed_count)
    return metrics


def calculate_source_rates(metrics: dict[str, int]) -> dict[str, float]:
    observed_count = max(0, coerce_non_negative_int(metrics.get("observed_count")) or 0)
    if observed_count == 0:
        return {
            "valuable_rate": 0.0,
            "high_novelty_rate": 0.0,
            "repeat_rate": 0.0,
            "noise_rate": 0.0,
            "skipped_rate": 0.0,
        }

    def rate(key: str) -> float:
        return round((coerce_non_negative_int(metrics.get(key)) or 0) / observed_count, 4)

    return {
        "valuable_rate": rate("valuable_count"),
        "high_novelty_rate": rate("high_novelty_count"),
        "repeat_rate": rate("repeat_count"),
        "noise_rate": rate("noise_count"),
        "skipped_rate": rate("skipped_count"),
    }


def source_topic_from_update(update: dict[str, Any]) -> str:
    for key in ("theme", "topic", "primary_theme", "sector", "industry"):
        topic = clean_text(update.get(key))
        if topic:
            return topic
    affected_themes = coerce_string_list(update.get("affected_themes"))
    if affected_themes:
        return affected_themes[0]
    related_entities = coerce_string_list(update.get("related_entity_ids"))
    if related_entities:
        return related_entities[0]
    affected_entities = coerce_string_list(update.get("affected_entities"))
    if affected_entities:
        return affected_entities[0]
    entity_id = clean_text(update.get("entity_id") or update.get("symbol"))
    if entity_id:
        return entity_id
    event_id = clean_text(update.get("event_id") or update.get("title"))
    if event_id:
        return event_id
    macro_id = clean_text(update.get("macro_id"))
    return macro_id


def stable_source_observation_id(
    update_id: str,
    observation_kind: str,
    source_id: str,
    update: dict[str, Any],
) -> str:
    identity = {
        "update_id": update_id,
        "observation_kind": observation_kind,
        "source_id": source_id,
        "information_unit_id": clean_text(
            update.get("information_unit_id") or update.get("unit_id")
        ),
        "cluster_id": clean_text(update.get("cluster_id")),
        "claim_id": clean_text(update.get("claim_id") or update.get("id")),
        "event_type": clean_text(update.get("event_type")),
        "subject": clean_text(update.get("subject")),
        "title": clean_text(update.get("title")),
        "claim": clean_text(
            update.get("claim") or update.get("summary") or update.get("observation")
        ),
        "evidence_item_ids": coerce_string_list(update.get("evidence_item_ids")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{update_id}:source-observation:{digest[:16]}"


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
    raw_id = clean_text(update.get("contradiction_id") or update.get("id"))
    if raw_id:
        return safe_filename(raw_id)
    identity = {
        "claim": clean_text(update.get("claim")),
        "conflicts_with": clean_text(update.get("conflicts_with")),
        "related_entity_ids": coerce_string_list(update.get("related_entity_ids")),
        "related_event_ids": coerce_string_list(update.get("related_event_ids")),
        "related_macro_ids": coerce_string_list(update.get("related_macro_ids")),
        "source_ids": coerce_string_list(update.get("source_ids")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"contradiction_{digest[:16]}"


def stable_event_cluster_id(update: dict[str, Any]) -> str:
    raw_id = clean_text(update.get("cluster_id") or update.get("id"))
    if raw_id:
        return raw_id

    identity = {
        "title": clean_text(update.get("title")),
        "summary": clean_text(update.get("summary")),
        "theme": clean_text(update.get("theme") or update.get("primary_theme")),
        "source_ids": coerce_string_list(update.get("source_ids")),
        "evidence_item_ids": coerce_string_list(
            update.get("evidence_item_ids") or update.get("tweet_ids")
        ),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"xcluster:{digest[:16]}"


def stable_information_unit_id(update: dict[str, Any]) -> str:
    raw_id = clean_text(
        update.get("information_unit_id") or update.get("unit_id") or update.get("id")
    )
    if raw_id:
        return raw_id

    identity = {
        "event_type": clean_text(update.get("event_type") or update.get("type")),
        "relation_to_memory": clean_text(
            update.get("relation_to_memory") or update.get("relation")
        ),
        "subject": clean_text(update.get("subject") or update.get("target")),
        "claim": clean_text(
            update.get("claim") or update.get("summary") or update.get("observation")
        ),
        "what_changed": clean_text(update.get("what_changed")),
        "source_ids": coerce_string_list(update.get("source_ids")),
        "evidence_item_ids": coerce_string_list(update.get("evidence_item_ids")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"info:{digest[:16]}"


def stable_thesis_id(
    update: dict[str, Any],
    entity_id: str,
    claim: str,
) -> str:
    thesis_update = (
        update.get("thesis_update")
        if isinstance(update.get("thesis_update"), dict)
        else {}
    )
    raw_id = clean_text(
        thesis_update.get("thesis_id")
        or update.get("thesis_id")
        or update.get("thesis_title")
        or thesis_update.get("title")
    )
    if raw_id:
        return safe_filename(raw_id)
    identity = {
        "entity_id": entity_id,
        "direction": normalize_thesis_direction(
            thesis_update.get("direction") or update.get("direction")
        ),
        "title": clean_text(thesis_update.get("title")),
        "claim": claim,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"thesis_{digest[:16]}"


def has_embedded_thesis_update(update: dict[str, Any]) -> bool:
    thesis_update = (
        update.get("thesis_update")
        if isinstance(update.get("thesis_update"), dict)
        else {}
    )
    keys = {
        "bull_case",
        "bear_case",
        "key_watchpoints",
        "invalidation_points",
        "catalysts",
        "thesis_status",
        "direction",
        "title",
        "thesis_id",
    }
    return any(clean_text(thesis_update.get(key)) or thesis_update.get(key) for key in keys)


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
    raw_thesis_update = (
        update.get("thesis_update")
        if isinstance(update.get("thesis_update"), dict)
        else {}
    )
    if not has_embedded_thesis_update(update):
        return None

    thesis_id = stable_thesis_id(update, entity_id, claim)
    direction = normalize_thesis_direction(
        raw_thesis_update.get("direction") or update.get("direction")
    )
    status = normalize_thesis_status(
        raw_thesis_update.get("thesis_status")
        or raw_thesis_update.get("status")
        or update.get("thesis_status")
    )
    title = clean_text(
        raw_thesis_update.get("title")
        or update.get("thesis_title")
        or claim
    )
    return {
        "thesis_id": thesis_id,
        "entity_id": entity_id,
        "title": title,
        "direction": direction,
        "thesis_status": status,
        "bull_case": coerce_string_list(raw_thesis_update.get("bull_case")),
        "bear_case": coerce_string_list(raw_thesis_update.get("bear_case")),
        "key_watchpoints": coerce_string_list(
            raw_thesis_update.get("key_watchpoints")
        ),
        "invalidation_points": coerce_string_list(
            raw_thesis_update.get("invalidation_points")
        ),
        "catalysts": coerce_string_list(raw_thesis_update.get("catalysts")),
        "what_changed": clean_text(
            raw_thesis_update.get("what_changed") or update.get("what_changed")
        ),
        "thesis_impact": clean_text(raw_thesis_update.get("thesis_impact")),
        "claim_ids": [claim_id],
        "evidence_item_ids": evidence_item_ids,
        "source_ids": source_ids,
        "latest_signal_evaluation": signal_evaluation,
        "first_seen": seen_at,
        "last_seen": seen_at,
        "last_update_id": update_id,
    }


def merge_embedded_thesis(
    existing: dict[str, Any],
    thesis_update: dict[str, Any],
    seen_at: str,
) -> dict[str, Any]:
    merged = dict(existing)
    for key in (
        "bull_case",
        "bear_case",
        "key_watchpoints",
        "invalidation_points",
        "catalysts",
        "claim_ids",
        "evidence_item_ids",
        "source_ids",
    ):
        merged[key] = unique_preserving_order(
            coerce_string_list(merged.get(key))
            + coerce_string_list(thesis_update.get(key))
        )

    for key in (
        "thesis_id",
        "entity_id",
        "title",
        "direction",
        "thesis_status",
        "what_changed",
        "thesis_impact",
        "last_update_id",
    ):
        value = thesis_update.get(key)
        if value not in (None, "", [], {}):
            merged[key] = value

    merged["first_seen"] = merged.get("first_seen") or thesis_update.get("first_seen")
    merged["last_seen"] = seen_at
    merged["latest_signal_evaluation"] = thesis_update.get(
        "latest_signal_evaluation"
    ) or merged.get("latest_signal_evaluation")
    return merged
