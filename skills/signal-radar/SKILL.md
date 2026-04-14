---
name: signal-radar
description: Collect remote social signals starting with configured X accounts via Playwright, generate Telegram-ready Chinese briefs grouped by topic, and persist MEMORY_UPDATE into per-account and per-theme memory files for long-running Hermes workflows.
metadata:
  hermes:
    tags: [x, twitter, monitoring, telegram, playwright, cron, memory]
---

# Signal Radar

This file is the deployment and runtime contract for Hermes operators. It assumes the skill is installed under `~/.hermes/skills/signal-radar/` on a VPS or another Hermes host.

If you are patching this skill inside the repo, start with `references/local-codex-intro.md` first. That document is the repo-local development entrypoint and uses local paths such as `skills/signal-radar/...`.

Use this skill when the user wants Hermes to:

- Monitor one or more X accounts over time
- Summarize new posts in Chinese for Telegram
- Group findings by topic instead of by account
- Keep long-run memory about recurring themes and account behavior
- Run the workflow on a schedule with Hermes cron

Do not use this skill for posting/replying/liking on X. That is a different workflow.

## Files

- `monitor.py`: collects tweets, exposes the latest artifact manifest, and applies `MEMORY_UPDATE`
- `config.yaml`: monitored accounts, synced state path, topic hints, and alias normalization
- `collectors/registry.yaml`: multi-source collector registry; contract-first for future sources like Reddit or 雪球
- `collectors/x/source.yaml`: source definition template for the current X collector
- `memory/state.json`: synced dedupe state (`seen_ids`, reliable `updated_at`, compatibility `last_run`)
- `memory/index.json`: synced index of all account/theme memory files
- `references/local-codex-intro.md`: first-stop intro for a local Codex session; read this before patching if you need the project in one page
- `references/architecture.md`: stable layer boundaries and contracts; read it before moving logic between collector, store, analyzer, and digest
- `references/collector-schema.md`: unified collector batch/item contract for future multi-source ingestion
- `claude.md`: implementation notes and debugging detail; read it when patching selectors, manifests, or memory schemas

## Layered Design

Treat `signal-radar` as four layers:

1. `collector`: `monitor.py collect` opens X with Playwright and writes raw artifacts
2. `local store`: `reports/`, `latest_run.json`, and `memory/` persist raw outputs and synced memory
3. `analyzer`: the LLM reads the prompt and memory, writes the digest, and emits strict JSON `MEMORY_UPDATE`
4. `digest / alerts`: Hermes or another downstream workflow decides whether to alert, send a digest, or no-op

Boundary rules:

- the collector may use a browser, but it must not make final editorial judgments
- the analyzer must not open webpages or mutate memory files directly
- the digest should read `latest` output and summary files, not scrape directories or guess paths
- `apply-memory` is the only bridge that writes analyzer output back into `memory/`

Multi-source note:

- `registry.yaml` and `collectors/x/source.yaml` now define the source contract
- current runtime is still X-first and enters through `monitor.py collect`
- `collect` now also writes `collector_batch_<run_id>.json` in `collector-batch/v1` format
- these files are preparation for adding Reddit, 雪球, and other sources without rewriting the analyzer layer

## Setup

The commands in this document use the deployed Hermes layout under `~/.hermes/skills/signal-radar/`. For repo-local development commands, see `references/local-codex-intro.md`.

Install the required runtime:

```bash
pip install playwright pyyaml --break-system-packages
playwright install chromium --with-deps
```

Export logged-in X cookies from a real browser and save them to:

```text
~/.hermes/skills/signal-radar/cookies.json
```

Accepted cookie formats:

- simple JSON object: `{ "auth_token": "...", "ct0": "..." }`
- browser-exported cookie array with `name/value/domain/path`

Then update `config.yaml` with the target accounts and theme hints.

## Workflow

Run collection:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py collect --config ~/.hermes/skills/signal-radar/config.yaml
```

Check whether there is anything new:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field new_tweet_count
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field warning
```

Read the normalized collector batch when you want source-agnostic input:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field collector_batch
```

Behavior rules:

- If `warning` returns a file path, read that warning and alert the user. This usually means login wall, selector drift, or a broken browser session.
- If `new_tweet_count` is `0` and there is no warning, do not invent a summary. Tell the user there were no new posts and stop.
- If there are new tweets, read the latest prompt path:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field prompt
```

Generate a Chinese brief from that prompt with this output discipline:

- Produce a Telegram-ready brief first
- Append `### MEMORY_UPDATE` at the end of the full saved summary
- `### MEMORY_UPDATE` must be a strict JSON object, ideally inside a `json` fenced block
- Use `primary_themes` for stable一级主题
- Use `secondary_themes` to map each一级主题 to more specific二级主题
- Use `account_notes` with usernames as keys and no leading `@`
- Send only the content before `### MEMORY_UPDATE` to Telegram

Expected `MEMORY_UPDATE` shape:

```json
{
  "primary_themes": ["AI/人工智能", "Space/航天"],
  "secondary_themes": {
    "AI/人工智能": ["Grok", "AI监管"],
    "Space/航天": ["Starship"]
  },
  "account_notes": {
    "elonmusk": "持续围绕火箭、AI 产品和政策发言。"
  }
}
```

After generating the summary, save the full text to the summary path returned by:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field summary
```

Then persist memory:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py apply-memory --config ~/.hermes/skills/signal-radar/config.yaml --summary-file ~/.hermes/skills/signal-radar/reports/summary_YYYYMMDD_HHMMSS.txt
```

`apply-memory` parses the `MEMORY_UPDATE` block and writes:

- updated `memory/state.json` for dedupe; treat `updated_at` as the reliable write timestamp and `last_run` as a compatibility field
- updated `memory/index.json`
- `memory/accounts/<username>.json`
- `memory/themes/<primary-theme>.json`
- a structured `memory_update_*.json`
- refreshed `latest_run.json`

Behavior notes:

- `apply-memory` is idempotent for the same summary input; rerunning it does not inflate theme counts
- 一级主题和二级主题都会先经过 alias 归一化再写入 memory
- `latest --field state` returns the synced state file path
- when reading `memory/state.json`, prefer `updated_at` for the latest successful write time; `last_run` is kept for compatibility with older state consumers

## Scheduled Use

For Hermes cron, keep the flow deterministic:

1. Run `collect`
2. Read `new_tweet_count` and `warning`
3. If warning exists, send the warning
4. If there are new tweets, read the prompt, generate the summary, send only the user-facing section, save the full summary, then run `apply-memory`

Prefer using the `latest` subcommand instead of guessing filenames or shell-globbing inside `reports/`.

If you need the full rationale for these boundaries, read `references/architecture.md` before changing the workflow shape.

## Guardrails

- Always use absolute paths when Hermes is running from cron or the gateway
- Commit `memory/` when you want memory and dedupe state to move with the repo across VPS hosts
- Never commit `cookies.json`, legacy root `state.json`, `latest_run.json`, `reports/`, or debug screenshots
- If every account lands on a login wall, ask the user to refresh cookies before retrying
- If pages load but visible tweet count is zero for all accounts, inspect `debug_*.png` and `claude.md` before changing selectors
