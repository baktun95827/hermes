# Signal Radar Worker

This directory is reserved for background execution.

The worker owns:

- reading queued ingestion jobs
- building `analysis_input/v1`
- invoking the analyzer provider
- validating strict `MEMORY_UPDATE`
- applying memory through `MemoryBackend`
- writing audit records and job results

For MVP, the analyzer provider is either `fixture` or `codex-cli`. Hermes is intentionally not in the product mainline; it remains a separate compatibility/debug integration.

Boundary rules:

- The worker can access local Hermes/Codex credentials if the host is logged in.
- The Web app should not access those credentials directly.
- The worker should return structured artifacts, not untracked agent state.
- Memory writes must go through the same apply/audit path as Hermes runs.

## Current MVP

Create and run a manual text job with the fixture provider:

```bash
python3 services/signal-radar-worker/worker.py ingest-text \
  --text "英维克液冷业务被市场重新讨论，但需要公告或订单验证。" \
  --config skills/signal-radar/config.yaml \
  --run \
  --provider fixture
```

Run with Codex CLI when you intentionally want a real analysis call:

```bash
python3 services/signal-radar-worker/worker.py ingest-text \
  --text-file /path/to/input.txt \
  --config skills/signal-radar/config.yaml \
  --run \
  --provider codex-cli \
  --model gpt-5.4
```

The worker writes:

- job state under `data/jobs/<job_id>/`
- `collector_batch_<job_id>.json` under the configured report directory
- `analysis_input`, `prompt`, `summary`, `memory_update`, `run_metrics`
- memory audit records through the existing `apply-memory` path
