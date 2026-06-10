# Signal Radar Core

This package now contains the TypeScript runtime-neutral Signal Radar logic.

Owned contracts and behavior:

- `collector_batch/v1` and `collector_item/v1`
- manual text ingestion
- `analysis_input/v1` construction
- strict `MEMORY_UPDATE` extraction and normalization
- useful evidence snapshot and source quality helpers
- agent quality gates for hard evidence, weak evidence, rumors, speculation, and contradictions
- Postgres-backed memory application
- memory record versioning and JSON diff generation
- Postgres queue claim, job payload, job logs, memory record browsing, target read projection, and version history queries
- memory audit records
- artifact path and config handling

Rules:

- no React or Web framework dependency
- no external agent session dependency
- no provider-specific LLM code
- deterministic functions should run in smoke tests without network or credentials
- product runtime state should be Postgres-backed; local files are only a compatibility/debug bridge
- crawler scheduling is intentionally outside the current foundation
- memory is agent-written; do not add manual edit workflows to core contracts

Primary imports:

```ts
import {
  buildAnalysisInput,
  applyMemoryUpdateToPostgres,
  writeManualCollectorBatch
} from "@/packages/signal-radar-core/src";
```

The product path should call this package directly through TypeScript imports. It should not shell out to legacy compatibility modules.
