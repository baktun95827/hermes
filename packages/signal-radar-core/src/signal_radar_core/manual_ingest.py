from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import atomic_write_json, build_artifact_paths, load_config
from .schemas import COLLECTOR_BATCH_SCHEMA_VERSION, COLLECTOR_ITEM_SCHEMA_VERSION


MANUAL_SOURCE_ID = "manual"
MANUAL_COLLECTOR_TRANSPORT = "manual"
MANUAL_COLLECTOR_IMPLEMENTATION = "web_or_cli"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d_%H%M%S")


def stable_manual_item_id(
    text: str,
    *,
    title: str | None = None,
    user_label: str | None = None,
    input_channel: str = "cli",
) -> str:
    payload = "\n".join(
        [
            text.strip(),
            title or "",
            user_label or "",
            input_channel,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_manual_collector_item(
    *,
    text: str,
    collected_at: str,
    title: str | None = None,
    url: str | None = None,
    user_label: str | None = None,
    input_channel: str = "cli",
    content_type: str = "note",
    requires_verification: bool = False,
    item_id: str | None = None,
) -> dict[str, Any]:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("manual text cannot be empty")

    normalized_item_id = item_id or stable_manual_item_id(
        clean_text,
        title=title,
        user_label=user_label,
        input_channel=input_channel,
    )
    label = (user_label or "user_note").strip() or "user_note"
    canonical_author = f"{MANUAL_SOURCE_ID}:{label}"
    canonical_id = f"{MANUAL_SOURCE_ID}:{normalized_item_id}"

    return {
        "schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": MANUAL_SOURCE_ID,
        "item_id": normalized_item_id,
        "canonical_id": canonical_id,
        "content_type": content_type,
        "published_at": collected_at,
        "collected_at": collected_at,
        "url": url,
        "title": title,
        "text": clean_text,
        "language": None,
        "author": {
            "source": MANUAL_SOURCE_ID,
            "entity_type": "manual_input",
            "entity_id": label,
            "canonical_entity_id": canonical_author,
            "display_name": label,
            "handle": None,
            "url": None,
        },
        "metrics": {},
        "media": [],
        "relations": {
            "is_repost": False,
            "quoted_item_id": None,
            "reply_to_item_id": None,
            "mentioned_entities": [],
        },
        "source_meta": {
            "input_channel": input_channel,
            "user_label": label,
            "requires_verification": requires_verification,
        },
    }


def build_manual_collector_batch(
    *,
    text: str,
    run_id: str | None = None,
    collected_at: str | None = None,
    title: str | None = None,
    url: str | None = None,
    user_label: str | None = None,
    input_channel: str = "cli",
    content_type: str = "note",
    requires_verification: bool = False,
    config_path: str | None = None,
) -> dict[str, Any]:
    generated_at = collected_at or utc_now().isoformat()
    normalized_run_id = run_id or f"manual_{timestamp_slug()}"
    item = build_manual_collector_item(
        text=text,
        title=title,
        url=url,
        user_label=user_label,
        input_channel=input_channel,
        content_type=content_type,
        requires_verification=requires_verification,
        collected_at=generated_at,
    )
    label = (user_label or "user_note").strip() or "user_note"
    return {
        "schema_version": COLLECTOR_BATCH_SCHEMA_VERSION,
        "item_schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": MANUAL_SOURCE_ID,
        "collector_run_id": normalized_run_id,
        "collected_at": generated_at,
        "target": {
            "kind": "manual_input",
            "id": label,
            "display_name": label,
        },
        "collector": {
            "transport": MANUAL_COLLECTOR_TRANSPORT,
            "implementation": MANUAL_COLLECTOR_IMPLEMENTATION,
            "entrypoint": "services/signal-radar-worker/worker.py ingest-text",
        },
        "item_count": 1,
        "items": [item],
        "warnings": [],
        "raw_meta": {
            "config_path": config_path,
            "input_channel": input_channel,
            "requires_verification": requires_verification,
        },
    }


def write_manual_collector_batch(
    *,
    config_path: str,
    text: str,
    run_id: str | None = None,
    title: str | None = None,
    url: str | None = None,
    user_label: str | None = None,
    input_channel: str = "cli",
    content_type: str = "note",
    requires_verification: bool = False,
    output_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path]:
    config = load_config(config_path)
    batch = build_manual_collector_batch(
        text=text,
        run_id=run_id,
        title=title,
        url=url,
        user_label=user_label,
        input_channel=input_channel,
        content_type=content_type,
        requires_verification=requires_verification,
        config_path=config["config_path"],
    )
    batch_path = (
        Path(output_path)
        if output_path
        else build_artifact_paths(
            Path(config["output_dir"]),
            str(batch["collector_run_id"]),
        )["collector_batch"]
    )
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(batch_path, batch)
    return batch, batch_path
