from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_config_path(raw_path: str) -> Path:
    path = Path(os.path.expanduser(raw_path))
    if path.is_absolute():
        return path
    return Path.cwd() / path


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(os.path.expanduser(str(raw_path)))
    if path.is_absolute():
        return path
    return base_dir / path


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required for YAML config files. "
            "Use JSON config or install pyyaml."
        ) from exc


def load_config(path: str) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    loaded = load_yaml_or_json(config_path) if config_path.exists() else {}
    config = merge_dicts(DEFAULT_CONFIG, loaded)
    config["config_path"] = str(config_path)
    base_dir = resolve_path(config_path.parent, config.get("base_dir") or ".")
    config["base_dir"] = str(base_dir)
    config["state_file"] = str(resolve_path(base_dir, config["state_file"]))
    config["memory_dir"] = str(resolve_path(base_dir, config["memory_dir"]))
    config["output_dir"] = str(resolve_path(base_dir, config["output_dir"]))
    config["latest_run_file"] = str(
        resolve_path(base_dir, config["latest_run_file"])
    )
    auth = config.setdefault("auth", {})
    if auth.get("cookies_file"):
        auth["cookies_file"] = str(resolve_path(base_dir, auth["cookies_file"]))
    return config


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding=encoding)
    tmp_path.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_legacy_state_paths(base_dir: str, state_file: str) -> list[Path]:
    current = Path(state_file)
    legacy = Path(base_dir) / "state.json"
    candidates = [legacy]
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
        "analysis_input": output_dir / f"analysis_input_{run_id}.json",
        "prompt": output_dir / f"prompt_{run_id}.txt",
        "report": output_dir / f"report_{run_id}.txt",
        "summary": output_dir / f"summary_{run_id}.txt",
        "memory_update": output_dir / f"memory_update_{run_id}.json",
        "run_metrics": output_dir / f"run_metrics_{run_id}.json",
        "warning": output_dir / f"warning_{run_id}.txt",
    }


def read_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return loaded if isinstance(loaded, dict) else dict(default)
