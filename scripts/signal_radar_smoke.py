#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "packages" / "signal-radar-core" / "src"
WORKER = REPO_ROOT / "services" / "signal-radar-worker" / "worker.py"
WEB_SERVER = REPO_ROOT / "apps" / "signal-radar-web" / "server.py"

if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))
if str(WORKER.parent) not in sys.path:
    sys.path.insert(0, str(WORKER.parent))

from signal_radar_core.memory_application import apply_memory_update  # noqa: E402
from worker import create_manual_job  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert_true(isinstance(loaded, dict), f"expected object JSON at {path}")
    return loaded


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "command failed:\n"
            f"  {' '.join(command)}\n"
            f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_config(root: Path) -> Path:
    config_path = root / "config.json"
    write_json(
        config_path,
        {
            "base_dir": str(root),
            "accounts": [],
            "discovery": {"enabled": False, "min_interactions": 3},
            "memory_backend": "file",
            "state_file": "memory/state.json",
            "memory_dir": "memory",
            "output_dir": "reports",
            "latest_run_file": "latest_run.json",
            "themes": ["manual research", "AI infrastructure"],
            "theme_aliases": {},
            "secondary_theme_aliases": {},
        },
    )
    return config_path


def py_compile_check() -> None:
    paths: list[str] = []
    for base in [
        REPO_ROOT / "packages" / "signal-radar-core" / "src" / "signal_radar_core",
        REPO_ROOT / "services" / "signal-radar-worker",
        REPO_ROOT / "apps" / "signal-radar-web",
        REPO_ROOT / "scripts",
    ]:
        paths.extend(str(path) for path in sorted(base.glob("*.py")))
    run_command([sys.executable, "-m", "py_compile", *paths])
    print("ok py_compile")


def unique_job_id_check(root: Path, config_path: Path) -> None:
    jobs_dir = root / "jobs-ids"
    first = create_manual_job(
        text="Manual note one for unique id smoke.",
        config_path=str(config_path),
        jobs_dir=str(jobs_dir),
        title="unique one",
    )
    second = create_manual_job(
        text="Manual note two for unique id smoke.",
        config_path=str(config_path),
        jobs_dir=str(jobs_dir),
        title="unique two",
    )
    assert_true(first.name != second.name, "manual job IDs must be unique")
    assert_true(first.parent == jobs_dir.resolve(), "first job escaped jobs dir")
    assert_true(second.parent == jobs_dir.resolve(), "second job escaped jobs dir")
    print("ok unique job ids")


def assert_memory_artifacts(status: dict[str, Any], temp_root: Path) -> None:
    paths = status.get("paths") if isinstance(status.get("paths"), dict) else {}
    memory_update_path = Path(paths.get("memory_update", ""))
    memory_audit_path = Path(paths.get("memory_audit", ""))
    assert_true(memory_update_path.exists(), f"missing memory_update: {memory_update_path}")
    assert_true(memory_audit_path.exists(), f"missing memory_audit: {memory_audit_path}")
    assert_true(
        str(memory_update_path.resolve()).startswith(str(temp_root.resolve())),
        "memory_update was not written under temp root",
    )
    assert_true(
        str(memory_audit_path.resolve()).startswith(str(temp_root.resolve())),
        "memory_audit was not written under temp root",
    )
    memory_status = status.get("memory_update")
    audit_status = status.get("memory_audit")
    assert_true(isinstance(memory_status, dict), "status.memory_update missing")
    assert_true(isinstance(audit_status, dict), "status.memory_audit missing")
    assert_true(memory_status.get("path") == str(memory_update_path), "memory update path not exposed")
    assert_true(audit_status.get("path") == str(memory_audit_path), "audit path not exposed")


def worker_fixture_smoke(root: Path, config_path: Path) -> dict[str, Any]:
    jobs_dir = root / "jobs-worker"
    result = run_command(
        [
            sys.executable,
            str(WORKER),
            "ingest-text",
            "--config",
            str(config_path),
            "--jobs-dir",
            str(jobs_dir),
            "--text",
            "Manual note: SampleCo liquid cooling demand is being discussed, but it needs primary-source verification.",
            "--title",
            "SampleCo liquid cooling discussion",
            "--user-label",
            "worker_smoke",
            "--requires-verification",
            "--run",
            "--provider",
            "fixture",
        ]
    )
    status = json.loads(result.stdout)
    assert_true(status.get("status") == "done", "worker fixture job did not finish")
    assert_memory_artifacts(status, root)
    report_path = Path(status["paths"]["report"])
    report_text = report_path.read_text(encoding="utf-8")
    assert_true(
        report_text.startswith("手动输入研究报告"),
        f"manual report has source-specific title: {report_text.splitlines()[:1]}",
    )
    assert_true("--- MANUAL INPUT ---" in report_text, "manual report body is not source-neutral")
    print(f"ok worker fixture {status['job_id']}")
    return status


def create_codex_shim(path: Path) -> Path:
    shim = path / "codex"
    shim.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
unsupported = {"--ask-for-approval"}
for flag in unsupported:
    if flag in args:
        raise SystemExit(f"unsupported codex shim arg: {flag}")
required_flags = ["exec", "--cd", "--sandbox", "read-only", "--ephemeral", "-m", "--output-last-message", "-"]
for flag in required_flags:
    if flag not in args:
        raise SystemExit(f"missing codex shim arg: {flag}")
try:
    output_path = Path(args[args.index("--output-last-message") + 1])
except (ValueError, IndexError):
    raise SystemExit("missing --output-last-message")
_ = sys.stdin.read()
payload = {
    "primary_themes": ["AI infrastructure"],
    "secondary_themes": {"AI infrastructure": ["liquid cooling"]},
    "account_notes": {},
    "information_units": [
        {
            "event_type": "other",
            "relation_to_memory": "new_event",
            "subject": "SampleCo cooling note",
            "claim": "A manual note says SampleCo cooling demand is being discussed.",
            "what_changed": "User-supplied material introduced a new unverified demand discussion.",
            "changed_dimensions": ["demand"],
            "affected_entities": ["entity:sampleco"],
            "affected_themes": ["AI infrastructure"],
            "market_mechanism": "Potential capex sentiment, pending verification.",
            "time_horizon": "near_term",
            "verification_status": "unverified",
            "signal_type": "new_angle",
            "novelty_level": "medium",
            "evidence_strength": "single_source",
            "memory_action": "write",
            "alert_level": "watch",
            "confidence": 0.35,
            "evidence_item_ids": ["manual:codex-shim"],
            "source_ids": ["manual:codex_shim"]
        }
    ],
    "event_clusters": [],
    "signal_evaluations": [],
    "entity_updates": [],
    "event_updates": [],
    "macro_updates": [],
    "source_assessments": [],
    "alert_candidates": [],
    "contradictions": []
}
summary = "Codex CLI shim summary. Manual material remains unverified.\\n\\n### MEMORY_UPDATE\\n```json\\n"
summary += json.dumps(payload, ensure_ascii=False, indent=2)
summary += "\\n```\\n"
output_path.write_text(summary, encoding="utf-8")
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def codex_cli_provider_smoke(root: Path, config_path: Path) -> dict[str, Any]:
    shim_dir = root / "codex-shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = create_codex_shim(shim_dir)
    env = os.environ.copy()
    env["XRADAR_CODEX_BIN"] = str(shim)
    result = run_command(
        [
            sys.executable,
            str(WORKER),
            "ingest-text",
            "--config",
            str(config_path),
            "--jobs-dir",
            str(root / "jobs-codex-cli"),
            "--text",
            "Manual note for codex-cli provider smoke. Treat it as unverified.",
            "--title",
            "codex-cli smoke",
            "--user-label",
            "codex_smoke",
            "--requires-verification",
            "--run",
            "--provider",
            "codex-cli",
            "--model",
            "smoke-model",
        ],
        env=env,
    )
    status = json.loads(result.stdout)
    assert_true(status.get("status") == "done", "codex-cli provider job did not finish")
    assert_true(status.get("provider") == "codex-cli", "provider not recorded as codex-cli")
    summary_path = Path(status["paths"]["summary"])
    summary_text = summary_path.read_text(encoding="utf-8")
    assert_true("Codex CLI shim summary" in summary_text, "codex output was not saved as summary")
    assert_memory_artifacts(status, root)
    print(f"ok codex-cli provider shim {status['job_id']}")
    return status


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_fixture_smoke(root: Path, config_path: Path) -> dict[str, Any]:
    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "XRADAR_CONFIG": str(config_path),
            "XRADAR_JOBS_DIR": str(root / "jobs-api"),
            "XRADAR_ANALYZER_PROVIDER": "fixture",
            "XRADAR_WEB_HOST": "127.0.0.1",
            "XRADAR_WEB_PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(WEB_SERVER)],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"web server exited early:\n{output}")
            try:
                with urllib.request.urlopen(f"{base_url}/api/healthz", timeout=1) as response:
                    if response.read() == b"ok\n":
                        break
            except Exception:
                if time.monotonic() >= deadline:
                    raise TimeoutError("web server did not become healthy")
                time.sleep(0.2)

        created = http_json(
            f"{base_url}/api/ingest-text",
            method="POST",
            payload={
                "title": "API fixture smoke",
                "text": "Manual API note: SampleCo demand discussion needs verification.",
                "user_label": "api_smoke",
                "requires_verification": True,
            },
        )
        job_id = created["job_id"]
        assert_true("../" not in job_id and "/" not in job_id, "API returned unsafe job_id")

        status_payload: dict[str, Any] = {}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status_payload = http_json(f"{base_url}{created['status_url']}")
            job_status = status_payload.get("status", {}).get("status")
            if job_status == "done":
                break
            if job_status == "failed":
                raise RuntimeError(json.dumps(status_payload, ensure_ascii=False, indent=2))
            time.sleep(0.4)
        assert_true(
            status_payload.get("status", {}).get("status") == "done",
            "API fixture job did not finish",
        )
        assert_true(status_payload.get("memory_update"), "API did not expose memory_update")
        assert_true(
            status_payload.get("memory_audit", {}).get("exists") is True,
            "API did not expose memory audit result",
        )
        try:
            urllib.request.urlopen(f"{base_url}/api/jobs/..%2Fconfig.yaml", timeout=3)
        except urllib.error.HTTPError as exc:
            assert_true(exc.code == 400, f"path traversal job_id returned {exc.code}")
        else:
            raise AssertionError("path traversal job_id was accepted")
        print(f"ok API fixture {job_id}")
        return status_payload
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def memory_update_sample_smoke(root: Path, config_path: Path) -> None:
    summary_path = root / "sample_summary.txt"
    payload = {
        "primary_themes": ["AI infrastructure"],
        "secondary_themes": {"AI infrastructure": ["liquid cooling"]},
        "account_notes": {},
        "information_units": [
            {
                "event_type": "other",
                "relation_to_memory": "new_event",
                "subject": "SampleCo cooling demand",
                "claim": "A manual sample says SampleCo liquid cooling demand is being discussed.",
                "what_changed": "New user-supplied material introduced an unverified demand signal.",
                "changed_dimensions": ["demand"],
                "affected_entities": ["entity:sampleco"],
                "affected_themes": ["AI infrastructure"],
                "market_mechanism": "Potential data-center capex sentiment if later verified.",
                "time_horizon": "near_term",
                "verification_status": "unverified",
                "signal_type": "new_angle",
                "novelty_level": "medium",
                "evidence_strength": "single_source",
                "memory_action": "write",
                "alert_level": "watch",
                "confidence": 0.35,
                "evidence_item_ids": ["manual:sample-memory-update"],
                "source_ids": ["manual:sample_user"],
            }
        ],
        "event_clusters": [],
        "signal_evaluations": [],
        "entity_updates": [
            {
                "entity_id": "entity:sampleco",
                "entity_type": "company",
                "display_name": "SampleCo",
                "claim": "Manual sample reports renewed discussion of SampleCo cooling demand.",
                "what_changed": "A new unverified demand discussion appeared in user-supplied material.",
                "verification_status": "unverified",
                "confidence": 0.35,
                "signal_type": "new_angle",
                "novelty_level": "medium",
                "evidence_strength": "single_source",
                "memory_action": "write",
                "evidence_item_ids": ["manual:sample-memory-update"],
                "source_ids": ["manual:sample_user"],
            }
        ],
        "event_updates": [
            {
                "event_id": "event:sampleco-cooling-discussion",
                "title": "SampleCo cooling discussion",
                "claim": "Manual sample introduced a named discussion event around cooling demand.",
                "what_changed": "A trackable event was created from user-supplied material.",
                "verification_status": "unverified",
                "confidence": 0.35,
                "signal_type": "new_angle",
                "novelty_level": "medium",
                "evidence_strength": "single_source",
                "memory_action": "write",
                "evidence_item_ids": ["manual:sample-memory-update"],
                "source_ids": ["manual:sample_user"],
            }
        ],
        "macro_updates": [
            {
                "macro_id": "macro:ai-datacenter-cooling",
                "topic": "AI datacenter cooling",
                "observation": "Manual sample links liquid cooling discussion to AI datacenter capex.",
                "what_changed": "A new unverified macro/sector angle was introduced.",
                "verification_status": "unverified",
                "confidence": 0.35,
                "time_horizon": "near_term",
                "signal_type": "new_angle",
                "novelty_level": "medium",
                "evidence_strength": "single_source",
                "memory_action": "write",
                "evidence_item_ids": ["manual:sample-memory-update"],
                "source_ids": ["manual:sample_user"],
            }
        ],
        "source_assessments": [
            {
                "source_id": "manual:sample_user",
                "assessment": "Manual input should be treated as user-supplied unverified material.",
                "what_changed": "Source profile records that this material needs confirmation.",
                "verification_status": "unverified",
                "confidence": 0.35,
                "source_type": "manual_input",
                "confirmation_required": "high",
                "signal_type": "new_angle",
                "novelty_level": "medium",
                "evidence_strength": "single_source",
                "memory_action": "write",
                "evidence_item_ids": ["manual:sample-memory-update"],
                "source_ids": ["manual:sample_user"],
            }
        ],
        "alert_candidates": [],
        "contradictions": [],
    }
    summary = "Manual MEMORY_UPDATE sample.\n\n### MEMORY_UPDATE\n```json\n"
    summary += json.dumps(payload, ensure_ascii=False, indent=2)
    summary += "\n```\n"
    summary_path.write_text(summary, encoding="utf-8")
    result = apply_memory_update(config_path=str(config_path), summary_path=summary_path)
    assert_true(result.memory_updates >= 4, "sample MEMORY_UPDATE did not update memory files")
    assert_true(result.memory_update_path.exists(), "sample memory_update artifact missing")
    assert_true(result.memory_audit_path.exists(), "sample memory audit missing")
    memory_dir = root / "memory"
    for dirname in ["entities", "events", "macro", "sources", "audit"]:
        assert_true(any((memory_dir / dirname).glob("*.json")), f"no files in memory/{dirname}")
    print("ok MEMORY_UPDATE sample apply")


def product_path_monitor_independence_check() -> None:
    forbidden = [
        "skills/signal-radar/monitor.py",
        "import_skill_monitor",
        "MONITOR =",
    ]
    roots = [
        REPO_ROOT / "apps" / "signal-radar-web",
        REPO_ROOT / "services" / "signal-radar-worker",
        REPO_ROOT / "packages" / "signal-radar-core" / "src" / "signal_radar_core",
    ]
    hits: list[str] = []
    for root in roots:
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)} contains {needle}")
    assert_true(not hits, "product path depends on monitor.py:\n" + "\n".join(hits))
    print("ok product path monitor independence")


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal Radar regression smoke checks")
    parser.add_argument("--keep-temp", action="store_true", help="print and keep temp artifacts")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="signal-radar-smoke-"))
    config_path = write_config(root)
    print(f"temp_root={root}")
    try:
        py_compile_check()
        unique_job_id_check(root, config_path)
        worker_fixture_smoke(root, config_path)
        codex_cli_provider_smoke(root, config_path)
        api_fixture_smoke(root, config_path)
        memory_update_sample_smoke(root, config_path)
        product_path_monitor_independence_check()
    finally:
        if args.keep_temp:
            print(f"kept_temp_root={root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
