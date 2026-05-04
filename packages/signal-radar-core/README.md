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

still contains the active Hermes implementation. The current MVP has copied runtime-neutral modules into `src/signal_radar_core/` so Web and worker can start depending on core instead of depending on Hermes. Continue extracting gradually; do not copy large logic into Web or worker directly.

Currently included:

- `schemas.py`
- `config.py`
- `memory_update.py`
- `memory_store.py`
- `audit.py`
- `manual_ingest.py`

Rules for this package:

- no Hermes imports
- no browser automation
- no Web framework dependency
- no provider-specific LLM code
- deterministic functions should be testable without network or credentials
