# Signal Radar Core

This directory is reserved for runtime-neutral Signal Radar logic.

It should eventually own:

- `collector_batch/v1` and `collector_item/v1` schemas
- `analysis_input/v1` construction
- strict `MEMORY_UPDATE` parsing and validation
- `MemoryBackend` interfaces
- file-backed memory implementation for MVP
- audit record generation
- source/entity/event/thesis normalization helpers

Current state:

```text
skills/signal-radar/signal_radar/
```

still contains the legacy Hermes skill CLI and crawler-facing implementation. The
current MVP has copied runtime-neutral modules into `src/signal_radar_core/`, and
the product Web/API and worker now build analysis input and apply memory through
core instead of the skill monitor. Continue extracting gradually; do not copy
large logic into Web or worker directly.

Currently included:

- `schemas.py`
- `config.py`
- `memory_update.py`
- `memory_store.py`
- `audit.py`
- `manual_ingest.py`
- `analysis_input.py` for native collector batch -> analysis input/prompt/report builds
- `memory_application.py` for native `MEMORY_UPDATE` application into `MemoryStore` and audit files
- `pipeline.py` as a small compatibility facade for worker logging/status semantics

Rules for this package:

- no Hermes imports
- no browser automation
- no Web framework dependency
- no provider-specific LLM code
- deterministic functions should be testable without network or credentials

The product path should not import or shell out to `skills/signal-radar/monitor.py`.
That file remains available for the legacy Hermes skill CLI, but Web/API and worker
code should call core modules directly.
