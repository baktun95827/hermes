# Signal Radar Core

This package now contains the TypeScript runtime-neutral Signal Radar logic.

Owned contracts and behavior:

- `collector_batch/v1` and `collector_item/v1`
- manual text ingestion
- `analysis_input/v1` construction
- strict `MEMORY_UPDATE` extraction and normalization
- file-backed memory application
- memory audit records
- artifact path and config handling

Rules:

- no React or Web framework dependency
- no external agent session dependency
- no provider-specific LLM code
- deterministic functions should run in smoke tests without network or credentials

Primary imports:

```ts
import {
  buildAnalysisInput,
  applyMemoryUpdate,
  writeManualCollectorBatch
} from "@/packages/signal-radar-core/src";
```

The product path should call this package directly through TypeScript imports. It should not shell out to legacy compatibility modules.
