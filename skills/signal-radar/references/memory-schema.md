# Signal Radar Memory Schema

This document defines the current memory model used by `apply-memory`.

The older memory model only tracked account notes and broad themes. The current model keeps that compatibility layer, then adds claim-driven memory for financial and geopolitical analysis.

Current implementation uses `memory_backend: file`, backed by `FileMemoryStore`. The contract in this document is backend-facing: analyzer output should stay stable if a future `PostgresMemoryStore` replaces the file implementation.

## Principle

Do not store every post. Store claims that are useful, traceable, and tagged with verification status.

For social media signals, a claim is usually not confirmed. It should normally be written as `unverified` or `plausible` unless it is supported by official or multi-source evidence.

Accepted `verification_status` values:

- `unverified`: interesting but not independently checked
- `plausible`: logically consistent or supported by weak/partial evidence
- `confirmed`: supported by official, primary, or strong multi-source evidence
- `superseded`: previously useful but replaced by a newer claim
- `rejected`: likely false; `apply-memory` ignores these updates

Accepted `claim_type` values:

- `fact`: verifiable statement
- `thesis`: investment or causal interpretation
- `rumor`: unverified report or market chatter
- `signal`: weak but potentially useful early indicator

## MEMORY_UPDATE Contract

`MEMORY_UPDATE` remains strict JSON. Existing keys are still supported:

- `primary_themes`
- `secondary_themes`
- `account_notes`

New keys:

- `entity_updates`: stocks, companies, sectors, supply-chain objects
- `event_updates`: time-evolving events such as Iran/Hormuz or wars
- `macro_updates`: macro environment, liquidity, rates, energy, commodities
- `source_assessments`: agent-maintained source notes

Example:

```json
{
  "primary_themes": ["个股/公司", "地缘政治"],
  "secondary_themes": {
    "个股/公司": ["A股标的", "液冷/温控"],
    "地缘政治": ["伊朗", "霍尔木兹海峡"]
  },
  "account_notes": {
    "example_user": "经常发布半导体和AI基础设施链条观点，需要交叉确认。"
  },
  "entity_updates": [
    {
      "entity_id": "cn_equity:英维克",
      "entity_type": "equity",
      "display_name": "英维克",
      "claim": "市场讨论其液冷/温控业务可能受益于算力基础设施扩张。",
      "claim_type": "thesis",
      "verification_status": "plausible",
      "confidence": 0.6,
      "novelty": "high",
      "materiality": "medium",
      "why_it_matters": "影响市场对公司收入弹性和估值的预期。",
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"],
      "action": "create_or_update"
    }
  ],
  "event_updates": [
    {
      "event_id": "geopolitics:iran-hormuz",
      "title": "伊朗-霍尔木兹海峡局势",
      "timestamp": "2026-04-14T10:00:00Z",
      "claim": "市场开始交易海峡航运受阻风险，可能影响原油和航运资产预期。",
      "verification_status": "unverified",
      "confidence": 0.4,
      "importance": "high",
      "evidence_item_ids": ["x:456"],
      "source_ids": ["x:example_user"],
      "timeline_action": "append"
    }
  ],
  "macro_updates": [],
  "source_assessments": []
}
```

## Backend Boundary

`apply-memory` is the only component that turns analyzer output into memory writes. The analyzer proposes `MEMORY_UPDATE`; the configured backend commits it after validation, normalization, skip rules, and idempotency checks.

Current status:

- implemented backend: `file`
- implementation class: `FileMemoryStore`
- configuration: `memory_backend: file`
- future backend idea: `PostgresMemoryStore`, after real memory claims prove the schema

## File Backend Layout

When using `memory_backend: file`, committed long-run memory lives under `memory/`:

- `memory/accounts/`: social account behavior and notes
- `memory/themes/`: broad recurring topics
- `memory/entities/`: one file per stock, company, sector, or supply-chain object
- `memory/events/`: one file per evolving event timeline
- `memory/macro/`: one file per macro trend
- `memory/sources/`: agent-maintained notes about accounts and sources
- `memory/index.json`: rebuilt index of all memory files

## Write Rules

`apply-memory` skips structured updates when:

- `verification_status` is `rejected`
- `action` is `ignore`, `reject`, `skip`, or `no_op`
- `novelty` says the update is duplicate or low value

For accepted updates, `apply-memory` derives a stable `claim_id` when the analyzer does not provide one. This gives idempotent writes and prevents one summary retry from inflating memory.

## Human vs Agent Ownership

Manual source policy should live in configuration or future profile files, not in generated memory. Examples:

- source trust tier
- source bias tags
- required confirmation level
- whether a source is official

Generated memory in `memory/sources/` is for observed behavior and agent notes. It should not overwrite human policy.
