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

still contains the active implementation. Extract into this package gradually; do not copy large logic into Web or worker directly.

Rules for this package:

- no Hermes imports
- no browser automation
- no Web framework dependency
- no provider-specific LLM code
- deterministic functions should be testable without network or credentials
