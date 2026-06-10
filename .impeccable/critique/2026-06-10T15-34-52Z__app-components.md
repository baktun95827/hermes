---
target: app components
total_score: 22
p0_count: 0
p1_count: 2
timestamp: 2026-06-10T15-34-52Z
slug: app-components
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Jobs and status pills exist, but active nav, worker state, queue health, evidence health, and refresh state are not surfaced as a coherent operations state. |
| 2 | Match System / Real World | 2 | The surface speaks both old runtime language ("durable job directory") and current Postgres/agent language, which weakens trust. |
| 3 | User Control and Freedom | 2 | Back/reset/refresh exist, but there is no retry, cancel, re-run, copy payload, or jump-to-target flow. |
| 4 | Consistency and Standards | 3 | Panels, buttons, tables, badges, and pills are consistent; the main inconsistency is language and navigation state. |
| 5 | Error Prevention | 2 | The ingest form validates required text only; URL, target code, provider, and verification context are not constrained or previewed. |
| 6 | Recognition Rather Than Recall | 2 | Core routes are obvious, but evidence, quality gates, target projection, and job-to-memory lineage require the operator to infer where to look. |
| 7 | Flexibility and Efficiency | 2 | Status filters help, but search, sort, keyboard acceleration, direct target lookup, and common operator shortcuts are missing. |
| 8 | Aesthetic and Minimalist Design | 3 | Restrained, readable, and not overdecorated; the issue is not visual noise but flat operational hierarchy. |
| 9 | Error Recovery | 1 | Failed DB/job states explain that something is wrong, but do not provide recovery actions or direct next commands. |
| 10 | Help and Documentation | 1 | Empty states and errors are too short for an early operator product; they do not teach the pipeline or expected setup. |
| **Total** | | **22/40** | **Usable foundation, not yet an analyst workstation** |

## Anti-Patterns Verdict

This does not immediately look AI-generated. The palette is restrained, the layout is conventional in a good product-UI way, and the detector found no slop patterns in `app` or `components`.

The weakness is different: the interface feels like a technically tidy scaffold, not yet like the control surface for an evidence-led memory system. It shows jobs and JSON, but it does not yet express the product's core promise: what changed, why we believe it, what is uncertain, and what needs agent recheck.

Deterministic scan: clean. `detect.mjs --json app components` returned `[]` with exit code 0. No detector false positives.

Visual overlays: no reliable overlay was produced. The Browser injection tool was not exposed in this session, so the run used Playwright CLI snapshots as fallback evidence. Snapshot succeeded for `/` and `/jobs`; screenshot writing hung in the wrapper and was cleaned up. `/memory` browser/curl inspection timed out, so memory-page observations are source-review based. The only console error on `/` was a missing `favicon.ico`, not a design issue.

## Overall Impression

The admin UI is clean enough to keep building on. Its biggest opportunity is to reorganize around operator decisions instead of raw artifacts: target, evidence, quality gate, memory diff, and next action should become the primary hierarchy.

## What's Working

- The visual system is restrained and credible. Moss primary, white background, simple borders, and native form controls fit the "analyst workstation" direction.
- Core operational objects are visible: jobs, queue status, provider/model, memory updates, audit, logs, and version history are not hidden behind friendly abstractions.
- The implementation avoids most common product-UI slop: no decorative gradients, no oversized hero, no glass cards, no sketch SVGs, no overanimated page load.

## Priority Issues

**[P1] Evidence and quality gates are not first-class navigation.**

Why it matters: The product direction is evidence-led, but the top nav only exposes Ingest, Jobs, Memory, and Health. An operator cannot start from "what evidence did we accept/reject?" or "which quality gates are dangerous?" without knowing the backend tables.

Fix: Add first-class Evidence and Quality surfaces, or at least integrate them into target/job detail as top-level sections. The default admin workflow should be: ingest/run -> evidence snapshot -> quality gate -> memory diff -> target projection.

Suggested command: `$impeccable shape app components`

**[P1] Empty and error states are not operationally actionable.**

Why it matters: Early operators will hit missing `DATABASE_URL`, empty jobs, empty memory, and worker-not-running states constantly. Current copy says what is missing, but not what to do next or what state is expected.

Fix: Turn empty states into compact setup/run checklists with exact next actions: migrate DB, enqueue sample, run worker once, inspect job, open memory. Add distinct states for DB missing, DB connected but no jobs, queued jobs but no worker, failed job, and no memory records.

Suggested command: `$impeccable onboard app components`

**[P2] Job detail is a JSON artifact wall, not a decision surface.**

Why it matters: Summary, Status JSON, Memory Update, Memory Audit, and Worker Log all have similar visual weight. The operator's actual questions are "Did it finish?", "What changed?", "What evidence supported it?", "What was skipped?", "What needs recheck?"

Fix: Promote a job outcome header with status, target, provider, run duration, memory writes, evidence counts, and quality flags. Keep raw JSON, but move it behind clearly labeled artifact panels after the human-readable outcome.

Suggested command: `$impeccable layout app/jobs/[jobId] components/job-detail.tsx`

**[P2] Manual ingest does not support the target-centric product direction.**

Why it matters: The backend and product direction support `target_code`, but the form does not expose it. That means new operator runs can easily create general jobs detached from the target read model.

Fix: Add target code as a primary field and make provider/model/verification context visible. A target-aware ingest form should route directly to the target projection after processing.

Suggested command: `$impeccable polish components/manual-ingest-form.tsx app/page.tsx`

**[P2] Copy and language are inconsistent.**

Why it matters: Chinese labels, English buttons, English headings, and stale file-runtime text are mixed in a way that feels accidental. For an internal admin this is tolerable, but for a trust-heavy market intelligence product it reads unfinished.

Fix: Choose an admin language for now. Since the operator/user is Chinese-speaking, use Chinese for labels and actions while keeping technical identifiers in English/mono. Remove stale "durable job directory" copy now that Postgres is the durable runtime.

Suggested command: `$impeccable clarify app components`

## Persona Red Flags

**Alex, power operator:** Alex can submit and refresh, but cannot quickly find exceptions. There is no dedicated quality-gate queue, no evidence filter, no job search, no target lookup, no retry action, and no keyboard-speed workflow. High risk: they leave the UI and query Postgres directly.

**Jordan, first-time operator:** Jordan sees `DATABASE_URL is not set` and `No jobs found`, but the UI does not tell them the exact local sequence to create a first successful run. They may not know whether they need Postgres, a worker, a provider key, or a manual ingest first.

**Mina, trust-focused analyst:** Mina needs to know why a memory changed. The current surface exposes raw memory/audit JSON, but does not foreground source quality, accepted/rejected evidence, rumor/speculation state, or contradiction flags. High risk: she treats the system as a black-box summarizer.

## Minor Observations

- Top nav has no active state, so orientation relies on page title.
- `/api/healthz` is exposed as a nav link; useful for developers, but it breaks the product-nav vocabulary.
- Status pills are clear, but `created`, `queued`, and `running` share the same warning-like visual treatment.
- The memory collection segmented control has too many equal choices for a first admin pass; grouping by "Core / Evidence / Alerts / Sources" would scan better.
- The missing favicon creates a dev-console 404 on the homepage.

## Questions to Consider

- Should the admin UI be organized around database objects, or around the operator's investigation path: target -> evidence -> quality gate -> memory diff?
- If an agent writes memory automatically, what is the one screen that lets you trust the write without reading raw JSON?
- Is "manual ingest" still the first screen once target pages and evidence queues exist, or should the default landing page become an operations dashboard?
