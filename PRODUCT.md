# Product

## Register

product

## Users

Signal Radar is ultimately a consumer-facing market intelligence product. The end user wants a TradingView-like research surface for public-market targets: fundamentals, business segments, industry-chain position, related concepts, key timeline, market awareness, and the current macro, geopolitical, central-bank, and policy context affecting the target.

The near-term user is an internal operator using the admin surface to supervise ingestion, agent runs, memory writes, diffs, failures, and quality gates while the product is still in early development.

## Product Purpose

The product builds and maintains the most precise, detailed public-information fundamental memory possible for thousands of market targets. It should continuously process public information, update target memory, and expose what changed with evidence, source quality, version history, and diffable audit trails.

The current product accepts manual research input, normalizes it into durable collector contracts, runs an analyzer provider, applies strict `MEMORY_UPDATE` output, and exposes the resulting summary, memory update, audit, and logs in one inspection surface. This is the seed of the larger information processing system, not the final consumer experience.

Success means the system can automatically maintain real-time memory at scale while humans inspect exceptions, edit memory when needed, compare versions, and trust that every change remains traceable.

## Product Direction

- Consumer product surface: target-centric pages with tabs for fundamentals, business segments, industry and supply-chain position, related concepts, key events, market consensus, source evidence, and current macro/policy context.
- Admin surface first: ingestion, queue state, provider output, memory update, audit, logs, version history, and diff review. The current UI should be treated as this admin surface.
- Agent automation first: thousands of targets cannot be maintained by manual approval. Agents should collect, analyze, update, and reconcile memory automatically, escalating low-confidence, contradictory, or high-impact changes.
- Memory versioning: every memory write should be append-only, attributable, reversible, and inspectable with a Git-diff-like UI across historical versions.
- Data backend: move from local file artifacts to Postgres for targets, source items, jobs, memory snapshots, memory patches, audit events, provider runs, and version diffs.
- Provider strategy: Codex CLI can be the temporary analyzer provider. The architecture should support Claude, GPT APIs, and future providers through narrow provider adapters.
- Input strategy: start small by making the information processing and memory system correct, then expand collectors for URLs, feeds, filings, news, social sources, and market-specific data.

## Brand Personality

Calm, technical, evidence-led. The interface should feel like an analyst workstation rather than a marketing page.

## Anti-references

Avoid landing-page hero sections, oversized decorative cards, glass effects, cream-and-forest generic AI palettes, and playful consumer-app styling. Avoid hiding raw artifacts behind friendly abstractions; the operator needs access to status, JSON, logs, and audit trails.

## Design Principles

- Put the active workflow first: input, run state, result, audit.
- Keep contracts visible: show job IDs, provider, paths, and structured payloads.
- Treat uncertainty as data: verification flags, skipped memory actions, weak evidence, and failures must stay inspectable.
- Optimize admin flows for supervision and exception handling, not manual approval of every memory write.
- Optimize consumer flows around a target's live fundamental picture and how that picture changed.
- Prefer dense but legible surfaces over promotional composition.
- Keep runtime credentials and analyzer execution behind server-side code.

## Accessibility & Inclusion

Target WCAG AA contrast, keyboard-accessible forms and links, visible focus states, reduced-motion-safe transitions, and clear state labels for loading, failed, and empty job states.
