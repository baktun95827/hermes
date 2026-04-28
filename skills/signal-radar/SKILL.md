---
name: signal-radar
description: Collect remote social signals starting with configured X accounts via Playwright, build replayable analysis inputs, generate Telegram-ready Chinese briefs grouped by topic, and submit MEMORY_UPDATE to the configured memory backend for long-running Hermes workflows.
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

- `monitor.py`: collects tweets, builds analysis input artifacts, exposes the latest artifact manifest, and applies `MEMORY_UPDATE`
- `config.yaml`: monitored accounts, memory backend, synced state path, topic hints, and alias normalization
- `collectors/registry.yaml`: multi-source collector registry; contract-first for future sources like Reddit or 雪球
- `collectors/x/source.yaml`: source definition template for the current X collector
- `memory/state.json`: synced dedupe state (`seen_ids`, reliable `updated_at`, compatibility `last_run`)
- `memory/index.json`: synced index of account/theme/entity/event/macro/source/contradiction memory files
- `reports/analysis_input_<run-id>.json`: replayable analyzer input built from collector output plus memory context
- `reports/run_metrics_<run-id>.json`: per-run health and analysis metrics, updated by `collect`, `build-analysis-input`, and `apply-memory`
- `references/local-codex-intro.md`: first-stop intro for a local Codex session; read this before patching if you need the project in one page
- `references/architecture.md`: stable layer boundaries and contracts; read it before moving logic between collector, store, analyzer, and digest
- `references/collector-schema.md`: unified collector batch/item contract for future multi-source ingestion
- `references/memory-schema.md`: claim-driven memory contract for financial entities, events, macro trends, and source assessments
- `claude.md`: implementation notes and debugging detail; read it when patching selectors, manifests, or memory schemas

## Layered Design

Treat `signal-radar` as explicit file-boundary layers:

1. `collector`: `monitor.py collect` opens X with Playwright and writes raw artifacts
2. `analysis input builder`: `monitor.py build-analysis-input` combines collector output, discovery hints, and memory context into `analysis_input` plus prompt
3. `local store`: `reports/`, `latest_run.json`, and the configured memory backend persist raw outputs and synced memory
4. `analyzer`: the LLM reads the prompt, writes the digest, and emits strict JSON `MEMORY_UPDATE`
5. `digest / alerts`: Hermes or another downstream workflow decides whether to alert, send a digest, or no-op

Boundary rules:

- the collector may use a browser, but it must not make final editorial judgments
- the collector must not read long-run memory or build the LLM prompt
- `build-analysis-input` is the only local bridge from normalized collector output to analyzer prompt
- the analyzer must not open webpages or mutate memory backend state directly
- the digest should read `latest` output and summary files, not scrape directories or guess paths
- `apply-memory` is the only bridge that submits analyzer output to the configured memory backend

Multi-source note:

- `registry.yaml` and `collectors/x/source.yaml` now define the source contract
- current runtime is still X-first and enters through `monitor.py collect`
- `collect` now also writes `collector_batch_<run_id>.json` in `collector-batch/v1` format
- `build-analysis-input` writes `analysis_input_<run_id>.json` and `prompt_<run_id>.txt`
- `collect` writes `run_metrics_<run_id>.json`; `build-analysis-input` adds input-build metrics; `apply-memory` adds event cluster and memory write counts
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
- If there are new tweets, build the analyzer input first:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py build-analysis-input --config ~/.hermes/skills/signal-radar/config.yaml
```

Then read the replayable analysis input or prompt path:

```bash
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field analysis_input
python3 ~/.hermes/skills/signal-radar/monitor.py latest --config ~/.hermes/skills/signal-radar/config.yaml --field prompt
```

Generate a Chinese brief from that prompt with this output discipline:

- Produce a Telegram-ready brief first
- Append `### MEMORY_UPDATE` at the end of the full saved summary
- `### MEMORY_UPDATE` must be a strict JSON object, ideally inside a `json` fenced block
- Use `primary_themes` for stable一级主题
- Use `secondary_themes` to map each一级主题 to more specific二级主题
- Use `account_notes` with usernames as keys and no leading `@`
- Use `event_clusters` to group multiple posts about the same event before writing claim updates
- Use `signal_evaluations` and per-claim `signal_evaluation` to decide whether a signal is new, repeated, noise, worth writing, or worth alerting
- Use `what_changed`, `changed_since`, and `prior_claim_refs` on accepted claim updates to explain the actual diff versus memory or the recent run
- Use `entity_updates` for stocks, companies, sectors, and supply-chain objects; include `thesis_update` when a signal changes an investment thesis
- Use `event_updates` for time-evolving events such as Iran/Hormuz
- Use `macro_updates` for macro environment, liquidity, energy, and commodity trends
- Use `source_assessments` for agent-maintained source notes and structured `source_profile`
- Use `alert_candidates` for content alerts; the digest layer decides whether to send them
- Use `contradictions` for suspected conflicts; record them as observations, not final truth decisions
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
  "event_clusters": [
    {
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "title": "液冷温控链条讨论升温",
      "summary": "多个账号开始把英维克等温控标的与算力基础设施扩张联系起来，但仍缺少订单级验证。",
      "theme": "个股/公司",
      "secondary_themes": ["A股标的", "液冷/温控"],
      "source_quality": "single_social_source",
      "signal_type": "new_angle",
      "novelty_level": "medium",
      "evidence_strength": "single_source",
      "memory_action": "write",
      "alert_level": "watch",
      "confidence": 0.55,
      "what_changed": "相对旧记忆，本次新增的是温控业务弹性讨论开始和算力基础设施扩张绑定。",
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"],
      "related_entity_ids": ["cn_equity:英维克"]
    }
  ],
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
      "what_changed": "相对旧记忆，本次增量是市场开始把液冷业务弹性和算力基础设施扩张联系起来。",
      "changed_since": "last_memory",
      "prior_claim_refs": ["entity_claim:previous-liquid-cooling-demand"],
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
  "source_assessments": [
    {
      "source_id": "x:example_user",
      "assessment": "对AI基础设施链条有持续观点输出，但需要公告和新闻交叉确认。",
      "source_profile": {
        "source_type": "analyst",
        "topic_scores": {"个股/公司": 0.7, "AI/算力": 0.6},
        "repeat_tendency": "medium",
        "repeat_rate": 0.4,
        "hit_rate": 0.3,
        "trust_score": 0.62,
        "valuable_count": 3,
        "marketing_tendency": "low",
        "emotion_tendency": "medium",
        "primary_source_score": 0.3,
        "confirmation_required": "high",
        "bias_tags": ["产业链多头", "需公告验证"]
      }
    }
  ],
  "alert_candidates": [],
  "contradictions": [
    {
      "claim": "某账号称英维克液冷订单正在加速释放。",
      "conflicts_with": "另一来源称同类项目招标节奏放缓，且公司公告尚未验证订单加速。",
      "conflict_type": "source_conflict",
      "severity": "medium",
      "related_entity_ids": ["cn_equity:英维克"],
      "evidence_item_ids": ["x:123", "x:789"],
      "source_ids": ["x:example_user", "x:other_source"]
    }
  ]
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
- `memory/contradictions/<contradiction-id>.json`
- a structured `memory_update_*.json`
- updated `run_metrics_*.json`
- refreshed `latest_run.json`

Behavior notes:

- `apply-memory` is idempotent for the same summary input; rerunning it does not inflate theme counts
- 一级主题和二级主题都会先经过 alias 归一化再写入 memory
- `event_clusters` are recorded in `memory_update_*.json` and `run_metrics_*.json`; they group same-event posts but do not create long-run memory by themselves
- structured updates with `verification_status: rejected`, explicit skip actions, `signal_type: noise`, `memory_action: skip|reject`, or no novelty are ignored
- accepted claim updates store `cluster_id`, `signal_evaluation`, `what_changed`, `changed_since`, `prior_claim_refs`, `last_valuable_at`, `status`, and optional `decay_score` in the file backend
- accepted `entity_updates.thesis_update` entries are merged into the entity file's `theses` map; this keeps bull/bear cases, watchpoints, invalidation points, catalysts, and thesis status next to the related claims
- accepted `source_assessments.source_profile` entries update structured source memory: `source_type`, `topic_scores`, `repeat_tendency`, `repeat_rate`, `hit_rate`, `trust_score`, `valuable_count`, `marketing_tendency`, `emotion_tendency`, `primary_source_score`, `confirmation_required`, and `bias_tags`
- event clusters, signal evaluations, accepted claim updates, and contradictions automatically update source `metrics`, `rates`, `topic_counts`, and `contribution_history`; do not ask the analyzer to manually invent those counters
- `alert_candidates` are recorded in `memory_update_*.json`; sending them is a downstream digest/alert decision
- `contradictions` are recorded under `memory/contradictions/` and indexed, but they do not automatically rewrite related entity, event, or macro memory conclusions
- `latest --field memory_backend` returns the active memory backend; currently this should be `file`
- `latest --field analysis_input` returns the replayable analyzer input artifact
- `latest --field run_metrics` returns the per-run metrics artifact
- `latest --field state` returns the synced state file path
- when reading `memory/state.json`, prefer `updated_at` for the latest successful write time; `last_run` is kept for compatibility with older state consumers

## Scheduled Use

For Hermes cron, keep the flow deterministic:

1. Run `collect`
2. Read `new_tweet_count` and `warning`
3. If warning exists, send the warning
4. If there are new tweets, run `build-analysis-input`
5. Read the prompt, generate the summary, send only the user-facing section, save the full summary, then run `apply-memory`

Prefer using the `latest` subcommand instead of guessing filenames or shell-globbing inside `reports/`.

If you need the full rationale for these boundaries, read `references/architecture.md` before changing the workflow shape.

## Guardrails

- Always use absolute paths when Hermes is running from cron or the gateway
- Commit `memory/` when you want memory and dedupe state to move with the repo across VPS hosts
- Never commit `cookies.json`, legacy root `state.json`, `latest_run.json`, `reports/`, or debug screenshots
- If every account lands on a login wall, ask the user to refresh cookies before retrying
- If pages load but visible tweet count is zero for all accounts, inspect `debug_*.png` and `claude.md` before changing selectors
