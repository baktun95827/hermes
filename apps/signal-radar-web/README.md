# Signal Radar Web

This directory is reserved for the product Web UI and API.

Initial responsibility:

- accept manual text, URL, or research note input
- create a source-agnostic ingestion job or `collector_batch/v1`
- show job status, summary, `MEMORY_UPDATE`, and memory audit result

Boundary rules:

- Web/API must not directly edit memory files or database rows.
- Web/API must not hold Hermes/Codex OAuth state.
- Web/API should submit work to `services/signal-radar-worker`.
- Manual input is a normal source, not a side channel.

The first useful endpoint should be:

```text
POST /ingest-text
```

Expected flow:

```text
manual text
-> collector_batch/v1
-> analysis input
-> analyzer worker
-> MEMORY_UPDATE proposal
-> MemoryBackend commit
-> audit/result shown in Web
```
