from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit import (
    build_memory_audit_record,
    read_memory_audit_record,
    snapshot_memory_tree,
    write_memory_audit_record,
)
from .config import (
    atomic_write_json,
    atomic_write_text,
    build_legacy_state_paths,
    load_config,
    read_json_file,
    read_latest_manifest,
    resolve_path,
    write_latest_manifest,
)
from .memory_store import StateManager, ThemeNormalizer, create_memory_backend
from .memory_update import build_memory_update_id, parse_memory_update
from .schemas import build_signal_evaluation, clean_text, coerce_string_list


MEMORY_UPDATE_KEYS = (
    "primary_themes",
    "secondary_themes",
    "account_notes",
    "information_units",
    "event_clusters",
    "signal_evaluations",
    "entity_updates",
    "event_updates",
    "macro_updates",
    "source_assessments",
    "alert_candidates",
    "contradictions",
)


@dataclass(frozen=True)
class MemoryApplicationResult:
    update_id: str
    applied_at: str
    summary_path: Path
    memory_update_path: Path
    run_metrics_path: Path
    memory_audit_path: Path
    memory_updates: int
    already_applied: bool

    def to_stdout(self) -> str:
        return "\n".join(
            [
                f"Memory updated: {self.memory_updates}",
                f"Summary: {self.summary_path}",
                f"MEMORY_UPDATE: {self.memory_update_path}",
                f"Run Metrics: {self.run_metrics_path}",
                f"Memory Audit: {self.memory_audit_path}",
            ]
        ) + "\n"


def has_parseable_memory_update(parsed: dict[str, Any]) -> bool:
    return any(bool(parsed.get(key)) for key in MEMORY_UPDATE_KEYS)


def count_high_novelty_information_units(
    information_units: list[dict[str, Any]],
) -> int:
    return sum(
        1
        for item in information_units
        if build_signal_evaluation(item).get("novelty_level") == "high"
    )


def count_high_novelty_event_clusters(event_clusters: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in event_clusters
        if build_signal_evaluation(item).get("novelty_level") == "high"
    )


def count_high_novelty_signals(signal_evaluations: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in signal_evaluations
        if build_signal_evaluation(item).get("novelty_level") == "high"
    )


def apply_memory_update(
    *,
    config_path: str,
    summary_path: str | Path,
) -> MemoryApplicationResult:
    config = load_config(config_path)
    base_dir = Path(config["base_dir"])
    resolved_summary_path = resolve_path(base_dir, str(summary_path))
    if not resolved_summary_path.exists():
        raise FileNotFoundError(f"summary file not found: {resolved_summary_path}")

    summary_text = resolved_summary_path.read_text(encoding="utf-8")
    parsed = parse_memory_update(summary_text)
    if not has_parseable_memory_update(parsed):
        raise ValueError("no parseable MEMORY_UPDATE found in summary")

    latest_run_file = Path(config["latest_run_file"])
    latest_payload = read_latest_manifest(latest_run_file) or {}
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    stored_summary_path = resolved_summary_path
    preferred_summary_path = (
        Path(latest_payload.get("paths", {}).get("summary"))
        if latest_payload.get("paths", {}).get("summary")
        else None
    )
    if preferred_summary_path:
        should_use_preferred_path = (
            preferred_summary_path.resolve() == resolved_summary_path.resolve()
            or not preferred_summary_path.exists()
            or (
                latest_payload.get("run_id")
                and preferred_summary_path.name.startswith(
                    f"summary_{latest_payload['run_id']}"
                )
            )
        )
        if (
            should_use_preferred_path
            and preferred_summary_path.resolve() != resolved_summary_path.resolve()
        ):
            atomic_write_text(preferred_summary_path, summary_text, encoding="utf-8")
            stored_summary_path = preferred_summary_path
        elif preferred_summary_path.resolve() == resolved_summary_path.resolve():
            stored_summary_path = preferred_summary_path

    update_id = build_memory_update_id(
        summary_text=summary_text,
        summary_path=stored_summary_path.resolve(),
        run_id=str(latest_payload.get("run_id")) if latest_payload.get("run_id") else None,
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
    memory_before_snapshot = snapshot_memory_tree(memory_store.root)
    seen_at = datetime.now(timezone.utc).isoformat()
    theme_updates = 0
    account_updates = 0
    entity_updates = 0
    event_updates = 0
    macro_updates = 0
    source_updates = 0
    source_observation_updates = 0
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

        observed_cluster_ids: set[str] = set()
        for update in parsed["event_clusters"]:
            cluster_id = clean_text(update.get("cluster_id"))
            if cluster_id and coerce_string_list(update.get("source_ids")):
                observed_cluster_ids.add(cluster_id)
            updated_sources = memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="event_cluster",
            )
            source_observation_updates += updated_sources

        for update in parsed["information_units"]:
            cluster_id = clean_text(update.get("cluster_id"))
            if cluster_id in observed_cluster_ids:
                continue
            if cluster_id and coerce_string_list(update.get("source_ids")):
                observed_cluster_ids.add(cluster_id)
            source_observation_updates += memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="information_unit",
            )

        for update in parsed["signal_evaluations"]:
            if clean_text(update.get("cluster_id")) in observed_cluster_ids:
                continue
            source_observation_updates += memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="signal_evaluation",
            )

        for collection_name, updates in (
            ("entity_update", parsed["entity_updates"]),
            ("event_update", parsed["event_updates"]),
            ("macro_update", parsed["macro_updates"]),
        ):
            for update in updates:
                if clean_text(update.get("cluster_id")) in observed_cluster_ids:
                    continue
                source_observation_updates += memory_store.update_source_observation(
                    update=update,
                    seen_at=seen_at,
                    update_id=update_id,
                    observation_kind=collection_name,
                )

        for update in parsed["contradictions"]:
            source_observation_updates += memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="contradiction",
            )
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
            or source_observation_updates
            or contradiction_updates
            or not memory_store.index_path.exists()
        ):
            memory_store.rebuild_index()

    state.save(update_last_run=False)
    memory_after_snapshot = snapshot_memory_tree(memory_store.root)

    memory_update_path = (
        Path(latest_payload.get("paths", {}).get("memory_update"))
        if latest_payload.get("paths", {}).get("memory_update")
        else output_dir / f"memory_update_{seen_at.replace(':', '').replace('.', '_')}.json"
    )
    memory_update_path.parent.mkdir(parents=True, exist_ok=True)
    run_metrics_path = (
        Path(latest_payload.get("paths", {}).get("run_metrics"))
        if latest_payload.get("paths", {}).get("run_metrics")
        else output_dir / f"run_metrics_{seen_at.replace(':', '').replace('.', '_')}.json"
    )
    run_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    memory_updates_total = (
        theme_updates
        + account_updates
        + entity_updates
        + event_updates
        + macro_updates
        + source_updates
        + source_observation_updates
        + contradiction_updates
    )
    update_counts = {
        "memory_updates": memory_updates_total,
        "theme_updates": theme_updates,
        "account_updates": account_updates,
        "entity_updates": entity_updates,
        "event_updates": event_updates,
        "macro_updates": macro_updates,
        "source_updates": source_updates,
        "source_observation_updates": source_observation_updates,
        "contradiction_updates": contradiction_updates,
    }
    already_applied = memory_updates_total == 0

    payload = {
        "update_id": update_id,
        "applied_at": seen_at,
        "summary_file": str(stored_summary_path),
        "state_file": config["state_file"],
        "primary_themes": normalized_primary,
        "secondary_themes": normalized_secondary_mapping,
        "account_notes": parsed["account_notes"],
        "information_units": parsed["information_units"],
        "information_unit_count": len(parsed["information_units"]),
        "event_clusters": parsed["event_clusters"],
        "event_cluster_count": len(parsed["event_clusters"]),
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
        "source_observation_updates_applied": source_observation_updates,
        "contradiction_updates_applied": contradiction_updates,
        "already_applied": already_applied,
    }

    audit_record = build_memory_audit_record(
        update_id=update_id,
        status="already_applied" if already_applied else "auto_applied",
        applied_at=seen_at,
        memory_dir=memory_store.root,
        memory_backend=config["memory_backend"],
        before_snapshot=memory_before_snapshot,
        after_snapshot=memory_after_snapshot,
        parsed_memory_update=parsed,
        update_counts=update_counts,
        latest_payload=latest_payload,
        summary_file=str(stored_summary_path),
        memory_update_file=str(memory_update_path),
        run_metrics_file=str(run_metrics_path),
        config_path=config["config_path"],
    )
    memory_audit_path = write_memory_audit_record(memory_store.root, audit_record)
    effective_audit_record = read_memory_audit_record(memory_audit_path) or audit_record
    payload["memory_audit"] = str(memory_audit_path)
    payload["memory_audit_changed_file_count"] = effective_audit_record[
        "changed_file_count"
    ]
    atomic_write_json(memory_update_path, payload)

    run_metrics_payload = read_json_file(
        run_metrics_path,
        {
            "schema_version": "signal-radar-run-metrics/v1",
            "run_id": latest_payload.get("run_id"),
            "status": "unknown",
            "collector": {},
        },
    )
    run_metrics_payload["schema_version"] = "signal-radar-run-metrics/v1"
    run_metrics_payload["run_id"] = run_metrics_payload.get(
        "run_id"
    ) or latest_payload.get("run_id")
    run_metrics_payload["updated_at"] = seen_at
    run_metrics_payload["analysis"] = {
        "memory_update_id": update_id,
        "information_units": len(parsed["information_units"]),
        "high_novelty_information_units": count_high_novelty_information_units(
            parsed["information_units"]
        ),
        "event_clusters": len(parsed["event_clusters"]),
        "high_novelty_events": count_high_novelty_event_clusters(
            parsed["event_clusters"]
        ),
        "signal_evaluations": len(parsed["signal_evaluations"]),
        "high_novelty_signals": count_high_novelty_signals(
            parsed["signal_evaluations"]
        ),
        "alert_candidates": len(parsed["alert_candidates"]),
        "contradictions": len(parsed["contradictions"]),
    }
    run_metrics_payload["memory"] = {
        **update_counts,
        "already_applied": payload["already_applied"],
        "memory_audit": str(memory_audit_path),
        "memory_audit_changed_file_count": effective_audit_record[
            "changed_file_count"
        ],
    }
    atomic_write_json(run_metrics_path, run_metrics_payload)

    latest_payload.setdefault("paths", {})
    latest_payload["paths"]["summary"] = str(stored_summary_path)
    latest_payload["paths"]["memory_update"] = str(memory_update_path)
    latest_payload["paths"]["memory_audit"] = str(memory_audit_path)
    latest_payload["paths"]["run_metrics"] = str(run_metrics_path)
    latest_payload["paths"]["memory_index"] = str(memory_store.index_path)
    latest_payload["paths"]["state"] = config["state_file"]
    latest_payload["memory_backend"] = config["memory_backend"]
    latest_payload["memory_update_applied"] = True
    latest_payload["memory_update"] = payload
    latest_payload["memory_audit"] = {
        "path": str(memory_audit_path),
        "status": effective_audit_record["status"],
        "changed_file_count": effective_audit_record["changed_file_count"],
    }
    latest_payload["run_metrics"] = run_metrics_payload
    if not isinstance(latest_payload.get("summary"), dict):
        latest_payload["summary"] = {}
    latest_payload["summary"]["information_unit_count"] = len(
        parsed["information_units"]
    )
    latest_payload["summary"]["high_novelty_information_unit_count"] = (
        count_high_novelty_information_units(parsed["information_units"])
    )
    latest_payload["summary"]["event_cluster_count"] = len(parsed["event_clusters"])
    latest_payload["summary"]["high_novelty_event_count"] = (
        count_high_novelty_event_clusters(parsed["event_clusters"])
    )
    write_latest_manifest(latest_run_file, latest_payload)

    return MemoryApplicationResult(
        update_id=update_id,
        applied_at=seen_at,
        summary_path=stored_summary_path,
        memory_update_path=memory_update_path,
        run_metrics_path=run_metrics_path,
        memory_audit_path=memory_audit_path,
        memory_updates=memory_updates_total,
        already_applied=already_applied,
    )
