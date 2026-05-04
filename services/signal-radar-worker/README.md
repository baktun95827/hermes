# Signal Radar Worker

This directory is reserved for background execution.

The worker owns:

- reading queued ingestion jobs
- building `analysis_input/v1`
- invoking the analyzer provider
- validating strict `MEMORY_UPDATE`
- applying memory through `MemoryBackend`
- writing audit records and job results

For MVP, the analyzer provider may be Hermes or Codex CLI running on the VPS host. That is acceptable as long as the provider is behind a replaceable interface.

Boundary rules:

- The worker can access local Hermes/Codex credentials if the host is logged in.
- The Web app should not access those credentials directly.
- The worker should return structured artifacts, not untracked agent state.
- Memory writes must go through the same apply/audit path as Hermes runs.
