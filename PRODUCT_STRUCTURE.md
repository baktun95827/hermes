# Signal Radar Product Structure

This repository is currently a Hermes skills repository. `signal-radar` is evolving from a Hermes skill into a product-oriented market intelligence system, so the repo now keeps a product-first skeleton next to the existing Hermes skill.

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

The product mainline is now:

```text
apps/signal-radar-web
-> services/signal-radar-worker
-> packages/signal-radar-core
-> CodexCliProvider or fixture provider
-> existing apply-memory compatibility path
```

`skills/signal-radar` remains the active, runnable Hermes skill and compatibility CLI, but new product work should not be built inside the skill directory.

The durable contracts are:

- `collector_batch/v1`
- `analysis_input/v1`
- strict `MEMORY_UPDATE`
- `MemoryBackend`
- memory audit records

New product code should depend on these contracts, not on Hermes sessions, Hermes memory, or browser crawler internals.

## Migration Sequence

1. Keep `skills/signal-radar` working as the compatibility Hermes entrypoint.
2. Keep runtime-neutral modules in `packages/signal-radar-core` and continue moving shared logic there.
3. Use `apps/signal-radar-web` for manual input and future UI/API work.
4. Use `services/signal-radar-worker` for jobs, analyzer provider calls, memory apply, and audit.
5. Prefer `CodexCliProvider` for the product worker when using the Codex subscription.
6. Keep Hermes as an optional integration and debugging path, not the default product runtime.
7. Once the core package is stable, move the Hermes adapter to `integrations/hermes/skills/signal-radar` and keep it thin.

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

For the current MVP, direct Codex CLI execution is the preferred product path:

```bash
XRADAR_ANALYZER_PROVIDER=codex-cli python3 apps/signal-radar-web/server.py
```
