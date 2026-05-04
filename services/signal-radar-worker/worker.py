#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_SRC = REPO_ROOT / "packages" / "signal-radar-core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from signal_radar_core.config import (  # noqa: E402
    atomic_write_json,
    atomic_write_text,
    build_artifact_paths,
    load_config,
    read_json_file,
)
from signal_radar_core.manual_ingest import (  # noqa: E402
    timestamp_slug,
    write_manual_collector_batch,
)
from signal_radar_core.pipeline import (  # noqa: E402
    PipelineError,
    apply_memory as pipeline_apply_memory,
    build_analysis_input as pipeline_build_analysis_input,
)


DEFAULT_CONFIG = REPO_ROOT / "skills" / "signal-radar" / "config.yaml"
DEFAULT_JOBS_DIR = REPO_ROOT / "data" / "jobs"


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_text_arg(text: str | None, text_file: str | None) -> str:
    if text_file:
        return Path(text_file).read_text(encoding="utf-8")
    if text is not None:
        return text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("--text, --text-file, or stdin is required")


def write_status(job_dir: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now_iso()
    atomic_write_json(job_dir / "status.json", payload)


def read_status(job_dir: Path) -> dict[str, Any]:
    return read_json_file(job_dir / "status.json", {})


def append_log(job_dir: Path, text: str) -> None:
    log_path = job_dir / "worker.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def run_command(job_dir: Path, command: list[str], *, input_text: str | None = None) -> None:
    append_log(job_dir, f"$ {' '.join(command)}")
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    )
    if result.stdout:
        append_log(job_dir, result.stdout)
    if result.stderr:
        append_log(job_dir, result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def log_pipeline_result(job_dir: Path, action: str, stdout: str, stderr: str) -> None:
    append_log(job_dir, f"$ core.pipeline {action}")
    if stdout:
        append_log(job_dir, stdout)
    if stderr:
        append_log(job_dir, stderr)


def create_manual_job(
    *,
    text: str,
    config_path: str,
    jobs_dir: str,
    title: str | None = None,
    url: str | None = None,
    user_label: str | None = None,
    input_channel: str = "cli",
    content_type: str = "note",
    requires_verification: bool = False,
) -> Path:
    job_id = f"manual_{timestamp_slug()}"
    job_dir = Path(jobs_dir).expanduser().resolve() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    batch, batch_path = write_manual_collector_batch(
        config_path=config_path,
        text=text,
        run_id=job_id,
        title=title,
        url=url,
        user_label=user_label,
        input_channel=input_channel,
        content_type=content_type,
        requires_verification=requires_verification,
    )
    atomic_write_json(job_dir / "collector_batch.json", batch)
    job_input = {
        "schema_version": "signal-radar-job/v1",
        "job_id": job_id,
        "created_at": utc_now_iso(),
        "kind": "manual_text",
        "config_path": str(Path(config_path).expanduser().resolve()),
        "collector_batch_path": str(batch_path),
        "title": title,
        "url": url,
        "user_label": user_label,
        "input_channel": input_channel,
        "content_type": content_type,
        "requires_verification": requires_verification,
    }
    atomic_write_json(job_dir / "input.json", job_input)
    write_status(
        job_dir,
        {
            "job_id": job_id,
            "status": "created",
            "created_at": job_input["created_at"],
            "paths": {
                "job_dir": str(job_dir),
                "collector_batch": str(batch_path),
            },
        },
    )
    return job_dir


class AnalyzerProvider:
    name = "base"

    def generate(
        self,
        *,
        prompt_path: Path,
        output_path: Path,
        job_dir: Path,
        job_input: dict[str, Any],
        collector_batch: dict[str, Any],
        model: str,
    ) -> None:
        raise NotImplementedError


class FixtureProvider(AnalyzerProvider):
    name = "fixture"

    def generate(
        self,
        *,
        prompt_path: Path,
        output_path: Path,
        job_dir: Path,
        job_input: dict[str, Any],
        collector_batch: dict[str, Any],
        model: str,
    ) -> None:
        item = (collector_batch.get("items") or [{}])[0]
        canonical_id = item.get("canonical_id") or "manual:unknown"
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        source_id = author.get("canonical_entity_id") or "manual:user_note"
        text = str(item.get("text") or "").strip()
        preview = text[:240] + ("..." if len(text) > 240 else "")
        memory_update = {
            "primary_themes": [],
            "secondary_themes": {},
            "account_notes": {},
            "information_units": [
                {
                    "event_type": "other",
                    "relation_to_memory": "new_event",
                    "subject": item.get("title") or "手动输入材料",
                    "claim": preview or "手动输入材料需要进一步分析。",
                    "what_changed": "fixture provider 仅用于链路验证，不做真实研究判断。",
                    "changed_dimensions": ["other"],
                    "affected_entities": [],
                    "affected_themes": ["手动输入"],
                    "market_mechanism": "fixture provider 不判断市场机制。",
                    "time_horizon": "unknown",
                    "verification_status": "unverified",
                    "signal_type": "unknown",
                    "novelty_level": "low",
                    "evidence_strength": "weak",
                    "memory_action": "skip",
                    "alert_level": "none",
                    "confidence": 0.0,
                    "evidence_item_ids": [canonical_id],
                    "source_ids": [source_id],
                }
            ],
            "event_clusters": [],
            "signal_evaluations": [],
            "entity_updates": [],
            "event_updates": [],
            "macro_updates": [],
            "source_assessments": [],
            "alert_candidates": [],
            "contradictions": [],
        }
        summary = (
            "手动输入链路 smoke summary。\n\n"
            "这份输出来自 fixture provider，只用于验证 Web/API、worker、"
            "collector_batch、analysis_input 和 apply-memory 链路。\n\n"
            "### MEMORY_UPDATE\n"
            "```json\n"
            f"{json.dumps(memory_update, ensure_ascii=False, indent=2)}\n"
            "```\n"
        )
        atomic_write_text(output_path, summary, encoding="utf-8")


class CodexCliProvider(AnalyzerProvider):
    name = "codex-cli"

    def generate(
        self,
        *,
        prompt_path: Path,
        output_path: Path,
        job_dir: Path,
        job_input: dict[str, Any],
        collector_batch: dict[str, Any],
        model: str,
    ) -> None:
        prompt = prompt_path.read_text(encoding="utf-8")
        instruction = (
            "You are the Signal Radar analyzer. Do not edit files. "
            "Read the prompt below and return only the final Chinese brief followed by "
            "a strict `### MEMORY_UPDATE` JSON block.\n\n"
        )
        command = [
            "codex",
            "exec",
            "--cd",
            str(REPO_ROOT),
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--ephemeral",
            "-m",
            model,
            "--output-last-message",
            str(output_path),
            "-",
        ]
        run_command(job_dir, command, input_text=instruction + prompt)
        if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
            raise RuntimeError("codex-cli provider did not write a summary")


def get_provider(name: str) -> AnalyzerProvider:
    normalized = name.strip().lower()
    if normalized == "fixture":
        return FixtureProvider()
    if normalized in {"codex", "codex-cli", "codex_cli"}:
        return CodexCliProvider()
    raise ValueError(f"unknown analyzer provider: {name}")


def artifact_paths_for_job(job_input: dict[str, Any]) -> dict[str, Path]:
    config = load_config(job_input["config_path"])
    return build_artifact_paths(Path(config["output_dir"]), job_input["job_id"])


def run_job(job_dir: str, *, provider_name: str, model: str, apply_memory: bool = True) -> int:
    job_path = Path(job_dir).expanduser().resolve()
    job_input = read_json_file(job_path / "input.json", {})
    if not job_input:
        raise SystemExit(f"job input not found: {job_path / 'input.json'}")
    status = read_status(job_path)
    started_at = utc_now_iso()
    write_status(
        job_path,
        {
            **status,
            "job_id": job_input["job_id"],
            "status": "running",
            "started_at": started_at,
        },
    )

    try:
        paths = artifact_paths_for_job(job_input)
        collector_batch_path = Path(job_input["collector_batch_path"])
        collector_batch = read_json_file(collector_batch_path, {})
        build_result = pipeline_build_analysis_input(
            config_path=job_input["config_path"],
            collector_batch_path=collector_batch_path,
        )
        log_pipeline_result(
            job_path,
            "build-analysis-input",
            build_result.stdout,
            build_result.stderr,
        )

        prompt_path = paths["prompt"]
        summary_path = job_path / "summary.txt"
        provider = get_provider(provider_name)
        provider.generate(
            prompt_path=prompt_path,
            output_path=summary_path,
            job_dir=job_path,
            job_input=job_input,
            collector_batch=collector_batch,
            model=model,
        )

        if apply_memory:
            apply_result = pipeline_apply_memory(
                config_path=job_input["config_path"],
                summary_path=summary_path,
            )
            log_pipeline_result(
                job_path,
                "apply-memory",
                apply_result.stdout,
                apply_result.stderr,
            )

        final_paths = {
            "job_dir": str(job_path),
            "collector_batch": str(collector_batch_path),
            "analysis_input": str(paths["analysis_input"]),
            "prompt": str(prompt_path),
            "summary": str(summary_path),
            "memory_update": str(paths["memory_update"]),
            "run_metrics": str(paths["run_metrics"]),
            "worker_log": str(job_path / "worker.log"),
        }
        write_status(
            job_path,
            {
                "job_id": job_input["job_id"],
                "status": "done",
                "created_at": job_input.get("created_at"),
                "started_at": started_at,
                "finished_at": utc_now_iso(),
                "provider": provider.name,
                "model": model,
                "paths": final_paths,
            },
        )
        print(json.dumps(read_status(job_path), ensure_ascii=False, indent=2))
        return 0
    except PipelineError as exc:
        log_pipeline_result(job_path, "failed", exc.result.stdout, exc.result.stderr)
        current = read_status(job_path)
        write_status(
            job_path,
            {
                **current,
                "status": "failed",
                "failed_at": utc_now_iso(),
                "error": str(exc),
            },
        )
        append_log(job_path, f"ERROR: {exc}")
        print(json.dumps(read_status(job_path), ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        current = read_status(job_path)
        write_status(
            job_path,
            {
                **current,
                "status": "failed",
                "failed_at": utc_now_iso(),
                "error": str(exc),
            },
        )
        append_log(job_path, f"ERROR: {exc}")
        print(json.dumps(read_status(job_path), ensure_ascii=False, indent=2))
        return 1


def command_ingest_text(args: argparse.Namespace) -> int:
    text = read_text_arg(args.text, args.text_file)
    job_dir = create_manual_job(
        text=text,
        config_path=args.config,
        jobs_dir=args.jobs_dir,
        title=args.title,
        url=args.url,
        user_label=args.user_label,
        input_channel=args.input_channel,
        content_type=args.content_type,
        requires_verification=args.requires_verification,
    )
    if args.run:
        return run_job(
            str(job_dir),
            provider_name=args.provider,
            model=args.model,
            apply_memory=not args.no_apply_memory,
        )
    print(str(job_dir))
    return 0


def command_run_job(args: argparse.Namespace) -> int:
    return run_job(
        args.job_dir,
        provider_name=args.provider,
        model=args.model,
        apply_memory=not args.no_apply_memory,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal Radar product worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest-text", help="create a manual text job")
    ingest.add_argument("--text")
    ingest.add_argument("--text-file")
    ingest.add_argument("--title")
    ingest.add_argument("--url")
    ingest.add_argument("--user-label")
    ingest.add_argument("--input-channel", default="cli")
    ingest.add_argument("--content-type", default="note")
    ingest.add_argument("--requires-verification", action="store_true")
    ingest.add_argument("--config", default=str(DEFAULT_CONFIG))
    ingest.add_argument("--jobs-dir", default=str(DEFAULT_JOBS_DIR))
    ingest.add_argument("--run", action="store_true")
    ingest.add_argument(
        "--provider",
        default=os.environ.get("XRADAR_ANALYZER_PROVIDER", "fixture"),
        choices=["fixture", "codex-cli", "codex"],
    )
    ingest.add_argument("--model", default=os.environ.get("XRADAR_CODEX_MODEL", "gpt-5.4"))
    ingest.add_argument("--no-apply-memory", action="store_true")
    ingest.set_defaults(func=command_ingest_text)

    run = subparsers.add_parser("run-job", help="run an existing job directory")
    run.add_argument("--job-dir", required=True)
    run.add_argument(
        "--provider",
        default=os.environ.get("XRADAR_ANALYZER_PROVIDER", "fixture"),
        choices=["fixture", "codex-cli", "codex"],
    )
    run.add_argument("--model", default=os.environ.get("XRADAR_CODEX_MODEL", "gpt-5.4"))
    run.add_argument("--no-apply-memory", action="store_true")
    run.set_defaults(func=command_run_job)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
