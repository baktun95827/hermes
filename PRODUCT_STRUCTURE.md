# Signal Radar Product Structure

This repository is currently a Hermes skills repository. `signal-radar` is evolving from a Hermes skill into a product-oriented market intelligence system, so the repo now keeps a transitional product skeleton.

## Target Layout

```text
apps/
  signal-radar-web/
    Web UI and API entrypoints, such as POST /ingest-text.
services/
  signal-radar-worker/
    Background jobs that build analysis inputs, run analyzers, and apply memory updates.
packages/
  signal-radar-core/
    Runtime-neutral contracts and business logic shared by Web, worker, and Hermes.
integrations/
  hermes/
    Hermes-specific skill adapter and install notes.
skills/
  signal-radar/
    Current active Hermes skill implementation during the transition.
data/
  Local runtime data for development. Do not commit real runtime state here.
```

## Current Boundary

`skills/signal-radar` remains the active, runnable Hermes skill today. Do not move it until `packages/signal-radar-core` owns the stable contracts and reusable logic.

The durable contracts are:

- `collector_batch/v1`
- `analysis_input/v1`
- strict `MEMORY_UPDATE`
- `MemoryBackend`
- memory audit records

New product code should depend on these contracts, not on Hermes sessions, Hermes memory, or browser crawler internals.

## Migration Sequence

1. Keep `skills/signal-radar` working as the compatibility Hermes entrypoint.
2. Extract runtime-neutral modules from `skills/signal-radar/signal_radar` into `packages/signal-radar-core`.
3. Add Web/API ingestion under `apps/signal-radar-web`; it should create jobs or collector batches, not mutate memory directly.
4. Add background execution under `services/signal-radar-worker`; it may call Hermes or Codex as an analyzer provider.
5. Once the core package is stable, move the Hermes adapter to `integrations/hermes/skills/signal-radar` and keep it thin.

## Deployment Shape

On a VPS, keep runtime credentials and product code separate:

```text
/opt/xradar/              # product code
/opt/hermes/ or ~/.hermes # Hermes runtime, sessions, auth, gateway state
```

If Hermes is used as a worker, expose only the skill adapter to Hermes:

```bash
ln -s /opt/xradar/integrations/hermes/skills/signal-radar \
      ~/.hermes/skills/signal-radar
```

Do not commit or mount Hermes/Codex OAuth state into the Web app. The worker host may use logged-in Hermes/Codex locally, but Web/API should talk to the worker through jobs and structured results.
