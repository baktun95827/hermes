---
name: x-monitor
description: Monitor configured X accounts with Playwright, generate Telegram-ready Chinese briefs grouped by topic, and persist MEMORY_UPDATE back into state.json for long-running Hermes workflows.
metadata:
  hermes:
    tags: [x, twitter, monitoring, telegram, playwright, cron, memory]
---

# X Monitor

Use this skill when the user wants Hermes to:

- Monitor one or more X accounts over time
- Summarize new posts in Chinese for Telegram
- Group findings by topic instead of by account
- Keep long-run memory about recurring themes and account behavior
- Run the workflow on a schedule with Hermes cron

Do not use this skill for posting/replying/liking on X. That is a different workflow.

## Files

- `monitor.py`: collects tweets, exposes the latest artifact manifest, and applies `MEMORY_UPDATE`
- `config.yaml`: monitored accounts, output paths, and topic hints
- `claude.md`: deeper architecture notes; read it only when patching selectors or data flow

## Setup

Install the required runtime:

```bash
pip install playwright pyyaml --break-system-packages
playwright install chromium --with-deps
```

Export logged-in X cookies from a real browser and save them to:

```text
~/.hermes/skills/x-monitor/cookies.json
```

Accepted cookie formats:

- simple JSON object: `{ "auth_token": "...", "ct0": "..." }`
- browser-exported cookie array with `name/value/domain/path`

Then update `config.yaml` with the target accounts and theme hints.

## Workflow

Run collection:

```bash
python3 ~/.hermes/skills/x-monitor/monitor.py collect --config ~/.hermes/skills/x-monitor/config.yaml
```

Check whether there is anything new:

```bash
python3 ~/.hermes/skills/x-monitor/monitor.py latest --config ~/.hermes/skills/x-monitor/config.yaml --field new_tweet_count
python3 ~/.hermes/skills/x-monitor/monitor.py latest --config ~/.hermes/skills/x-monitor/config.yaml --field warning
```

Behavior rules:

- If `warning` returns a file path, read that warning and alert the user. This usually means login wall, selector drift, or a broken browser session.
- If `new_tweet_count` is `0` and there is no warning, do not invent a summary. Tell the user there were no new posts and stop.
- If there are new tweets, read the latest prompt path:

```bash
python3 ~/.hermes/skills/x-monitor/monitor.py latest --config ~/.hermes/skills/x-monitor/config.yaml --field prompt
```

Generate a Chinese brief from that prompt with this output discipline:

- Produce a Telegram-ready brief first
- Append `### MEMORY_UPDATE` at the end of the full saved summary
- Send only the content before `### MEMORY_UPDATE` to Telegram

After generating the summary, save the full text to the summary path returned by:

```bash
python3 ~/.hermes/skills/x-monitor/monitor.py latest --config ~/.hermes/skills/x-monitor/config.yaml --field summary
```

Then persist memory:

```bash
python3 ~/.hermes/skills/x-monitor/monitor.py apply-memory --config ~/.hermes/skills/x-monitor/config.yaml --summary-file ~/.hermes/skills/x-monitor/reports/summary_YYYYMMDD_HHMMSS.txt
```

`apply-memory` parses the `MEMORY_UPDATE` block and writes:

- updated `state.json`
- a structured `memory_update_*.json`
- refreshed `latest_run.json`

## Scheduled Use

For Hermes cron, keep the flow deterministic:

1. Run `collect`
2. Read `new_tweet_count` and `warning`
3. If warning exists, send the warning
4. If there are new tweets, read the prompt, generate the summary, send only the user-facing section, save the full summary, then run `apply-memory`

Prefer using the `latest` subcommand instead of guessing filenames or shell-globbing inside `reports/`.

## Guardrails

- Always use absolute paths when Hermes is running from cron or the gateway
- Never commit `cookies.json`, `state.json`, `latest_run.json`, `reports/`, or debug screenshots
- If every account lands on a login wall, ask the user to refresh cookies before retrying
- If pages load but visible tweet count is zero for all accounts, inspect `debug_*.png` and `claude.md` before changing selectors
