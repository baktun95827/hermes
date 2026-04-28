from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import atomic_write_json
from .schemas import *


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

    def update_source_observation(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
        observation_kind: str,
    ) -> int:
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

    def get_recent_source_memories(self, n: int = 8) -> list[dict[str, Any]]:
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

    def default_source_payload(
        self,
        source_id: str,
        seen_at: str,
        update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        update = update or {}
        source_type = normalize_source_type(update.get("source_type"))
        return {
            "schema_version": "source-memory/v1",
            "source_id": source_id,
            "source_type": source_type,
            "display_name": clean_text(update.get("display_name")) or source_id,
            "created_at": seen_at,
            "updated_at": seen_at,
            "latest_assessment": "",
            "assessment_history": [],
            "topic_strength": {},
            "topic_scores": {},
            "topic_counts": {},
            "metrics": normalize_source_metrics({}),
            "rates": calculate_source_rates(normalize_source_metrics({})),
            "style_profile": {
                "marketing_tendency": "unknown",
                "emotion_tendency": "unknown",
                "primary_source_score": None,
            },
            "source_profile": {},
            "contribution_history": [],
            "applied_update_ids": [],
            "applied_observation_ids": [],
            "last_update_id": None,
        }

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
            self.default_source_payload(source_id, seen_at, update),
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
        raw_source_type = profile_field("source_type")
        normalized_source_type = normalize_source_type(raw_source_type)
        if normalized_source_type == "unknown":
            normalized_source_type = payload.get("source_type") or "unknown"
        normalized_confirmation_required = normalize_confirmation_required(
            profile_field("confirmation_required")
        )
        if normalized_confirmation_required == "unknown":
            normalized_confirmation_required = (
                payload.get("confirmation_required") or "unknown"
            )
        normalized_repeat_tendency = normalize_repeat_tendency(
            profile_field("repeat_tendency")
        )
        if normalized_repeat_tendency == "unknown":
            normalized_repeat_tendency = payload.get("repeat_tendency") or "unknown"
        trust_score = (
            coerce_float_or_none(profile_field("trust_score"))
            if profile_field("trust_score") is not None
            else payload.get("trust_score")
        )
        hit_rate = (
            coerce_float_or_none(profile_field("hit_rate"))
            if profile_field("hit_rate") is not None
            else payload.get("hit_rate")
        )
        repeat_rate = (
            coerce_float_or_none(profile_field("repeat_rate"))
            if profile_field("repeat_rate") is not None
            else payload.get("repeat_rate")
        )
        metrics = normalize_source_metrics(
            payload.get("metrics"),
            seed_valuable_count=payload.get("valuable_count"),
        )
        metrics["assessment_count"] += 1
        previous_valuable_count = metrics["valuable_count"]
        explicit_valuable_count = coerce_non_negative_int(
            profile_field("valuable_count")
        )
        valuable_count = (
            max(previous_valuable_count, explicit_valuable_count)
            if explicit_valuable_count is not None
            else previous_valuable_count + (1 if is_valuable_signal(signal_evaluation) else 0)
        )
        metrics["valuable_count"] = valuable_count
        if is_high_novelty_signal(signal_evaluation):
            metrics["high_novelty_count"] += 1
        if signal_evaluation["signal_type"] == "repeat":
            metrics["repeat_count"] += 1
        if signal_evaluation["signal_type"] == "noise":
            metrics["noise_count"] += 1
        if signal_evaluation["memory_action"] in {"skip", "reject"}:
            metrics["skipped_count"] += 1
        if signal_evaluation["alert_level"] in {"watch", "important", "urgent"}:
            metrics["alert_count"] += 1
        rates = calculate_source_rates(metrics)
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
                    "source_type": normalized_source_type,
                    "confirmation_required": normalized_confirmation_required,
                    "repeat_tendency": normalized_repeat_tendency,
                    "trust_score": trust_score,
                    "bias_tags": coerce_string_list(
                        profile_field("bias_tags") or update.get("bias_tags")
                    ),
                    "signal_evaluation": signal_evaluation,
                }
            )

        topic_scores = payload.get("topic_scores") or payload.get("topic_strength", {})
        if not isinstance(topic_scores, dict):
            topic_scores = {}
        topic_scores.update(
            coerce_number_mapping(
                profile_field("topic_scores") or profile_field("topic_strength")
            )
        )
        last_valuable_at = clean_text(profile_field("last_valuable_at"))
        if not last_valuable_at and is_valuable_signal(signal_evaluation):
            last_valuable_at = seen_at

        existing_style_profile = payload.get("style_profile")
        if not isinstance(existing_style_profile, dict):
            existing_style_profile = {}
        marketing_tendency = normalize_style_tendency(
            profile_field("marketing_tendency")
            or existing_style_profile.get("marketing_tendency")
        )
        emotion_tendency = normalize_style_tendency(
            profile_field("emotion_tendency")
            or existing_style_profile.get("emotion_tendency")
        )
        primary_source_score = (
            coerce_float_or_none(profile_field("primary_source_score"))
            if profile_field("primary_source_score") is not None
            else existing_style_profile.get("primary_source_score")
        )
        style_profile_payload = {
            "marketing_tendency": marketing_tendency,
            "emotion_tendency": emotion_tendency,
            "primary_source_score": primary_source_score,
        }

        bias_tags = unique_preserving_order(
            coerce_string_list(payload.get("bias_tags"))
            + coerce_string_list(profile_field("bias_tags") or update.get("bias_tags"))
        )
        source_profile_payload = {
            "source_type": normalized_source_type,
            "topic_scores": topic_scores,
            "repeat_tendency": normalized_repeat_tendency,
            "repeat_rate": repeat_rate,
            "hit_rate": hit_rate,
            "trust_score": trust_score,
            "valuable_count": valuable_count,
            "last_valuable_at": last_valuable_at or payload.get("last_valuable_at"),
            "confirmation_required": normalized_confirmation_required,
            "bias_tags": bias_tags,
            "marketing_tendency": marketing_tendency,
            "emotion_tendency": emotion_tendency,
            "primary_source_score": primary_source_score,
            "style_profile": style_profile_payload,
        }

        payload.update(
            {
                "schema_version": "source-memory/v1",
                "source_id": source_id,
                "source_type": normalized_source_type,
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
                "confirmation_required": normalized_confirmation_required,
                "repeat_tendency": normalized_repeat_tendency,
                "hit_rate": hit_rate,
                "repeat_rate": repeat_rate,
                "trust_score": trust_score,
                "valuable_count": valuable_count,
                "metrics": metrics,
                "rates": rates,
                "topic_strength": topic_scores,
                "topic_scores": topic_scores,
                "bias_tags": bias_tags,
                "style_profile": style_profile_payload,
                "source_profile": source_profile_payload,
                "latest_signal_evaluation": signal_evaluation,
                "assessment_history": history[-20:],
                "applied_update_ids": (applied_update_ids + [entry_update_id])[-100:],
                "last_update_id": update_id,
            }
        )
        self._write_json(path, payload)
        return True

    def update_source_observation(
        self,
        update: dict[str, Any],
        seen_at: str,
        update_id: str,
        observation_kind: str,
    ) -> int:
        source_ids = coerce_string_list(update.get("source_ids"))
        if not source_ids:
            source_id = clean_text(
                update.get("source_id")
                or update.get("canonical_source_id")
                or update.get("username")
            )
            if source_id:
                source_ids = [source_id]
        if not source_ids:
            return 0

        updated_count = 0
        signal_evaluation = build_signal_evaluation(update)
        topic = source_topic_from_update(update)
        cluster_id = clean_text(update.get("cluster_id"))
        claim_id = clean_text(update.get("claim_id") or update.get("id"))
        evidence_item_ids = coerce_string_list(update.get("evidence_item_ids"))
        related_entity_ids = coerce_string_list(update.get("related_entity_ids"))
        related_event_ids = coerce_string_list(update.get("related_event_ids"))
        related_macro_ids = coerce_string_list(update.get("related_macro_ids"))
        should_record_contribution = (
            is_valuable_signal(signal_evaluation)
            or is_high_novelty_signal(signal_evaluation)
            or observation_kind == "contradiction"
            or signal_evaluation["alert_level"] in {"watch", "important", "urgent"}
        )

        for raw_source_id in source_ids:
            source_id = clean_text(raw_source_id)
            if not source_id:
                continue

            observation_id = stable_source_observation_id(
                update_id=update_id,
                observation_kind=observation_kind,
                source_id=source_id,
                update=update,
            )
            path = self.source_path(source_id)
            payload = self._read_json(
                path,
                self.default_source_payload(source_id, seen_at, update),
            )
            applied_observation_ids = payload.get("applied_observation_ids", [])
            if not isinstance(applied_observation_ids, list):
                applied_observation_ids = []
            if observation_id in applied_observation_ids:
                continue

            metrics = normalize_source_metrics(
                payload.get("metrics"),
                seed_valuable_count=payload.get("valuable_count"),
            )
            metrics["observed_count"] += 1
            if is_valuable_signal(signal_evaluation):
                metrics["valuable_count"] += 1
            if is_high_novelty_signal(signal_evaluation):
                metrics["high_novelty_count"] += 1
            if signal_evaluation["signal_type"] == "repeat":
                metrics["repeat_count"] += 1
            if (
                signal_evaluation["signal_type"] == "noise"
                or signal_evaluation["memory_action"] == "reject"
            ):
                metrics["noise_count"] += 1
            if (
                signal_evaluation["memory_action"] in {"skip", "reject"}
                or signal_evaluation["novelty_level"] == "none"
            ):
                metrics["skipped_count"] += 1
            if observation_kind == "contradiction":
                metrics["contradiction_count"] += 1
            if signal_evaluation["alert_level"] in {"watch", "important", "urgent"}:
                metrics["alert_count"] += 1
            rates = calculate_source_rates(metrics)

            topic_counts = payload.get("topic_counts", {})
            if not isinstance(topic_counts, dict):
                topic_counts = {}
            if topic:
                topic_entry = topic_counts.get(topic, {})
                if not isinstance(topic_entry, dict):
                    topic_entry = {}
                topic_entry = {
                    "observed_count": (
                        coerce_non_negative_int(topic_entry.get("observed_count"))
                        or 0
                    )
                    + 1,
                    "valuable_count": (
                        coerce_non_negative_int(topic_entry.get("valuable_count"))
                        or 0
                    )
                    + (1 if is_valuable_signal(signal_evaluation) else 0),
                    "high_novelty_count": (
                        coerce_non_negative_int(
                            topic_entry.get("high_novelty_count")
                        )
                        or 0
                    )
                    + (1 if is_high_novelty_signal(signal_evaluation) else 0),
                    "last_seen": seen_at,
                }
                topic_counts[topic] = topic_entry

            contribution_history = payload.get("contribution_history", [])
            if not isinstance(contribution_history, list):
                contribution_history = []
            if should_record_contribution:
                contribution_history.append(
                    {
                        "time": seen_at,
                        "observation_id": observation_id,
                        "observation_kind": observation_kind,
                        "cluster_id": cluster_id,
                        "claim_id": claim_id,
                        "topic": topic,
                        "novelty_level": signal_evaluation["novelty_level"],
                        "signal_type": signal_evaluation["signal_type"],
                        "memory_action": signal_evaluation["memory_action"],
                        "alert_level": signal_evaluation["alert_level"],
                        "evidence_item_ids": evidence_item_ids,
                        "related_entity_ids": related_entity_ids,
                        "related_event_ids": related_event_ids,
                        "related_macro_ids": related_macro_ids,
                    }
                )

            payload.update(
                {
                    "schema_version": "source-memory/v1",
                    "source_id": source_id,
                    "display_name": payload.get("display_name") or source_id,
                    "updated_at": seen_at,
                    "last_valuable_at": (
                        seen_at
                        if is_valuable_signal(signal_evaluation)
                        else payload.get("last_valuable_at")
                    ),
                    "metrics": metrics,
                    "rates": rates,
                    "valuable_count": metrics["valuable_count"],
                    "repeat_rate": rates["repeat_rate"],
                    "topic_counts": topic_counts,
                    "latest_signal_evaluation": signal_evaluation,
                    "contribution_history": contribution_history[
                        -SOURCE_CONTRIBUTION_HISTORY_LIMIT:
                    ],
                    "applied_observation_ids": (
                        applied_observation_ids + [observation_id]
                    )[-SOURCE_OBSERVATION_ID_LIMIT:],
                    "last_update_id": update_id,
                }
            )
            self._write_json(path, payload)
            updated_count += 1

        return updated_count

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

    def get_recent_source_memories(self, n: int = 8) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        if not self.sources_dir.exists():
            return memories
        for path in self.sources_dir.glob("*.json"):
            payload = self._read_json(path, {})
            source_id = clean_text(payload.get("source_id"))
            if not source_id:
                continue
            topic_scores = payload.get("topic_scores") or payload.get(
                "topic_strength", {}
            )
            if not isinstance(topic_scores, dict):
                topic_scores = {}
            topic_counts = payload.get("topic_counts", {})
            if not isinstance(topic_counts, dict):
                topic_counts = {}
            top_topic_payloads: list[dict[str, Any]] = []
            for topic, raw_entry in topic_counts.items():
                topic_name = clean_text(topic)
                if not topic_name or not isinstance(raw_entry, dict):
                    continue
                top_topic_payloads.append(
                    {
                        "topic": topic_name,
                        "score": coerce_float_or_none(topic_scores.get(topic_name)),
                        "observed_count": coerce_non_negative_int(
                            raw_entry.get("observed_count")
                        )
                        or 0,
                        "valuable_count": coerce_non_negative_int(
                            raw_entry.get("valuable_count")
                        )
                        or 0,
                        "high_novelty_count": coerce_non_negative_int(
                            raw_entry.get("high_novelty_count")
                        )
                        or 0,
                        "last_seen": clean_text(raw_entry.get("last_seen")),
                    }
                )
            scored_topic_names = {item["topic"] for item in top_topic_payloads}
            for topic, score in topic_scores.items():
                topic_name = clean_text(topic)
                normalized_score = coerce_float_or_none(score)
                if not topic_name or topic_name in scored_topic_names:
                    continue
                top_topic_payloads.append(
                    {
                        "topic": topic_name,
                        "score": normalized_score,
                        "observed_count": 0,
                        "valuable_count": 0,
                        "high_novelty_count": 0,
                        "last_seen": "",
                    }
                )
            top_topic_payloads.sort(
                key=lambda item: (
                    item.get("valuable_count") or 0,
                    item.get("high_novelty_count") or 0,
                    item.get("observed_count") or 0,
                    item.get("score") if item.get("score") is not None else -1,
                ),
                reverse=True,
            )
            metrics = normalize_source_metrics(
                payload.get("metrics"),
                seed_valuable_count=payload.get("valuable_count"),
            )
            rates = (
                payload.get("rates")
                if isinstance(payload.get("rates"), dict)
                else calculate_source_rates(metrics)
            )
            style_profile = payload.get("style_profile")
            if not isinstance(style_profile, dict):
                style_profile = {}
            memories.append(
                {
                    "source_id": source_id,
                    "display_name": clean_text(payload.get("display_name")),
                    "source_type": clean_text(payload.get("source_type")),
                    "updated_at": clean_text(payload.get("updated_at")),
                    "last_valuable_at": clean_text(payload.get("last_valuable_at")),
                    "confirmation_required": clean_text(
                        payload.get("confirmation_required")
                    ),
                    "repeat_tendency": clean_text(payload.get("repeat_tendency")),
                    "trust_score": payload.get("trust_score"),
                    "valuable_count": metrics["valuable_count"],
                    "metrics": metrics,
                    "rates": rates,
                    "style_profile": {
                        "marketing_tendency": normalize_style_tendency(
                            style_profile.get("marketing_tendency")
                        ),
                        "emotion_tendency": normalize_style_tendency(
                            style_profile.get("emotion_tendency")
                        ),
                        "primary_source_score": coerce_float_or_none(
                            style_profile.get("primary_source_score")
                        ),
                    },
                    "top_topics": top_topic_payloads[:5],
                    "latest_assessment": clean_text(
                        payload.get("latest_assessment")
                    ),
                }
            )
        memories.sort(
            key=lambda item: item.get("last_valuable_at") or item.get("updated_at", ""),
            reverse=True,
        )
        return memories[:n]

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
            metrics = normalize_source_metrics(
                payload.get("metrics"),
                seed_valuable_count=payload.get("valuable_count"),
            )
            rates = (
                payload.get("rates")
                if isinstance(payload.get("rates"), dict)
                else calculate_source_rates(metrics)
            )
            style_profile = payload.get("style_profile")
            if not isinstance(style_profile, dict):
                style_profile = {}
            sources[source_id] = {
                "file": str(path.relative_to(self.root)),
                "updated_at": payload.get("updated_at"),
                "last_valuable_at": payload.get("last_valuable_at"),
                "source_type": payload.get("source_type"),
                "credibility": payload.get("credibility"),
                "requires_confirmation": payload.get("requires_confirmation"),
                "confirmation_required": payload.get("confirmation_required"),
                "repeat_tendency": payload.get("repeat_tendency"),
                "trust_score": payload.get("trust_score"),
                "valuable_count": metrics["valuable_count"],
                "metrics": metrics,
                "rates": rates,
                "style_profile": {
                    "marketing_tendency": normalize_style_tendency(
                        style_profile.get("marketing_tendency")
                    ),
                    "emotion_tendency": normalize_style_tendency(
                        style_profile.get("emotion_tendency")
                    ),
                    "primary_source_score": coerce_float_or_none(
                        style_profile.get("primary_source_score")
                    ),
                },
                "topic_scores": payload.get("topic_scores")
                or payload.get("topic_strength", {}),
                "topic_counts": payload.get("topic_counts", {}),
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
            "version": 6,
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

