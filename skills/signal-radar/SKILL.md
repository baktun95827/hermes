---
name: signal-radar
description: Collect remote social signals starting with configured X accounts via Playwright, generate Telegram-ready Chinese briefs grouped by topic, and submit MEMORY_UPDATE to the configured memory backend for long-running Hermes workflows.
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
- `config.yaml`: monitored accounts, memory backend, synced state path, topic hints, and alias normalization
- `collectors/registry.yaml`: multi-source collector registry; contract-first for future sources like Reddit or 雪球
- `collectors/x/source.yaml`: source definition template for the current X collector
- `memory/state.json`: synced dedupe state (`seen_ids`, reliable `updated_at`, compatibility `last_run`)
- `memory/index.json`: synced index of account/theme/entity/event/macro/source memory files
- `references/local-codex-intro.md`: first-stop intro for a local Codex session; read this before patching if you need the project in one page
- `references/architecture.md`: stable layer boundaries and contracts; read it before moving logic between collector, store, analyzer, and digest
- `references/collector-schema.md`: unified collector batch/item contract for future multi-source ingestion
- `references/memory-schema.md`: claim-driven memory contract for financial entities, events, macro trends, and source assessments
- `claude.md`: implementation notes and debugging detail; read it when patching selectors, manifests, or memory schemas

## Layered Design

Treat `signal-radar` as four layers:

1. `collector`: `monitor.py collect` opens X with Playwright and writes raw artifacts
2. `local store`: `reports/`, `latest_run.json`, and the configured memory backend persist raw outputs and synced memory
3. `analyzer`: the LLM reads the prompt and memory, writes the digest, and emits strict JSON `MEMORY_UPDATE`
4. `digest / alerts`: Hermes or another downstream workflow decides whether to alert, send a digest, or no-op

Boundary rules:

- the collector may use a browser, but it must not make final editorial judgments
- the analyzer must not open webpages or mutate memory backend state directly
- the digest should read `latest` output and summary files, not scrape directories or guess paths
- `apply-memory` is the only bridge that submits analyzer output to the configured memory backend

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

Current memory backend:

- `memory_backend: file` is the only implemented backend
- `memory_dir: memory` controls the file-backed memory directory
- keep the `MEMORY_UPDATE` contract stable so a future backend, such as Postgres, can replace the file implementation without changing analyzer output

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
- Use `signal_evaluations` and per-claim `signal_evaluation` to decide whether a signal is new, repeated, noise, worth writing, or worth alerting
- Use `entity_updates` for stocks, companies, sectors, and supply-chain objects; include `thesis_update` when a signal changes an investment thesis
- Use `event_updates` for time-evolving events such as Iran/Hormuz
- Use `macro_updates` for macro environment, liquidity, energy, and commodity trends
- Use `source_assessments` for agent-maintained source notes
- Use `alert_candidates` for content alerts; the digest layer decides whether to send them
- Send only the content before `### MEMORY_UPDATE` to Telegram

Expected `MEMORY_UPDATE` shape:

```json
{
  "primary_themes": ["个股/公司", "地缘政治"],
  "secondary_themes": {
    "个股/公司": ["A股标的", "液冷/温控"],
    "地缘政治": ["伊朗", "霍尔木兹海峡"]
  },
  "account_notes": {
    "example_user": "经常发布半导体和AI基础设施链条观点，需要结合公告和新闻交叉确认。"
  },
  "signal_evaluations": [
    {
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "summary": "液冷温控链条讨论出现中等新增角度，但仍是单一社交来源。",
      "signal_type": "new_angle",
      "novelty_level": "medium",
      "evidence_strength": "single_source",
      "memory_action": "write",
      "alert_level": "watch",
      "confidence": 0.55,
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "entity_updates": [
    {
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "entity_id": "cn_equity:英维克",
      "entity_type": "equity",
      "display_name": "英维克",
      "claim": "市场讨论其液冷/温控业务可能受益于算力基础设施扩张。",
      "claim_type": "thesis",
      "verification_status": "plausible",
      "materiality": "medium",
      "signal_evaluation": {
        "signal_type": "new_angle",
        "novelty_level": "medium",
        "evidence_strength": "single_source",
        "memory_action": "write",
        "alert_level": "watch",
        "confidence": 0.6
      },
      "thesis_update": {
        "thesis_id": "yingweike_liquid_cooling_growth",
        "title": "液冷/温控业务增长 thesis",
        "direction": "bull",
        "thesis_status": "strengthened",
        "bull_case": ["算力基础设施扩张可能提升液冷/温控需求"],
        "bear_case": ["竞争加剧或项目节奏不及预期可能压缩估值和毛利率"],
        "key_watchpoints": ["订单验证", "毛利率变化", "大客户进展"],
        "invalidation_points": ["订单兑现不及预期", "毛利率持续下滑"],
        "catalysts": ["业绩预告", "大客户招标", "行业政策"],
        "what_changed": "本次新增的是温控业务弹性讨论，不是已验证订单事实。",
        "thesis_impact": "小幅增强多头 thesis，但仍需要公告或产业链数据确认。"
      },
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "event_updates": [],
  "macro_updates": [],
  "source_assessments": [],
  "alert_candidates": []
}
```

For the full claim-driven memory contract, read `references/memory-schema.md`.

After generating the summary, save the full text to the summary path returned by:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field summary
```

Then persist memory:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py apply-memory --config ~/.hermes/skills/signal-radar/config.yaml --summary-file ~/.hermes/skills/signal-radar/reports/summary_YYYYMMDD_HHMMSS.txt
```

`apply-memory` parses the `MEMORY_UPDATE` block and submits it to the configured memory backend. Current `memory_backend: file` writes:

- updated `memory/state.json` for dedupe; treat `updated_at` as the reliable write timestamp and `last_run` as a compatibility field
- updated `memory/index.json`
- `memory/accounts/<username>.json`
- `memory/themes/<primary-theme>.json`
- `memory/entities/<entity-id>.json`
- `memory/events/<event-id>.json`
- `memory/macro/<macro-id>.json`
- `memory/sources/<source-id>.json`
- a structured `memory_update_*.json`
- refreshed `latest_run.json`

Behavior notes:

- `apply-memory` is idempotent for the same summary input; rerunning it does not inflate theme counts
- 一级主题和二级主题都会先经过 alias 归一化再写入 memory
- structured updates with `verification_status: rejected`, explicit skip actions, `signal_type: noise`, `memory_action: skip|reject`, or no novelty are ignored
- accepted claim updates store `cluster_id`, `signal_evaluation`, `last_valuable_at`, `status`, and optional `decay_score` in the file backend
- accepted `entity_updates.thesis_update` entries are merged into the entity file's `theses` map; this keeps bull/bear cases, watchpoints, invalidation points, catalysts, and thesis status next to the related claims
- `alert_candidates` are recorded in `memory_update_*.json`; sending them is a downstream digest/alert decision
- `latest --field memory_backend` returns the active memory backend; currently this should be `file`
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
