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

- `information_units`: concrete market/geopolitical claim units before cluster-level or memory-level decisions
- `event_clusters`: run-level grouping of multiple posts about the same event; clusters are recorded in artifacts and metrics, not as long-run memory by themselves
- `signal_evaluations`: run-level or cluster-level value judgments, including skipped signals
- `entity_updates`: stocks, companies, sectors, supply-chain objects; may include embedded `thesis_update`
- `event_updates`: time-evolving events such as Iran/Hormuz or wars
- `macro_updates`: macro environment, liquidity, rates, energy, commodities
- `source_assessments`: agent-maintained source notes
- `alert_candidates`: possible content alerts for the digest layer to decide on
- `contradictions`: suspected conflicts between claims, sources, data, or missing official verification

`signal_evaluation` is the shared value-judgment shape. It may appear inside `information_units`, `event_clusters`, `signal_evaluations`, claim updates, and alert candidates:

```json
{
  "signal_type": "new_fact",
  "novelty_level": "high",
  "evidence_strength": "single_source",
  "memory_action": "write",
  "alert_level": "important",
  "confidence": 0.6,
  "evidence_count": 1,
  "source_count": 1
}
```

Accepted values:

- `signal_type`: `new_fact`, `new_angle`, `confirmation`, `repeat`, `noise`
- `novelty_level`: `high`, `medium`, `low`, `none`
- `evidence_strength`: `weak`, `single_source`, `multi_source`, `official`
- `memory_action`: `write`, `merge`, `skip`, `supersede`, `reject`
- `alert_level`: `none`, `watch`, `important`, `urgent`

`information_units` should be emitted before `event_clusters` when individual posts contain distinct claims or when a same event has a meaningful update:

```json
{
  "information_unit_id": "info:ccl-price-20260428",
  "cluster_id": "xcluster:ccl-price-20260428",
  "event_type": "material_price_change",
  "relation_to_memory": "event_update",
  "subject": "CCL 上游材料价格",
  "claim": "社交媒体称部分 CCL 上游材料报价继续上调。",
  "what_changed": "相对旧记忆，本次新增的是涨价范围可能从单点扩散到多个材料环节。",
  "changed_dimensions": ["price", "supply", "market_expectation"],
  "affected_entities": ["cn_equity:沪电股份"],
  "affected_themes": ["PCB材料", "AI算力链"],
  "market_mechanism": "上游材料涨价可能改变 PCB 链条利润分配，并影响市场对相关标的毛利率的预期。",
  "time_horizon": "weeks",
  "verification_status": "plausible",
  "signal_type": "new_fact",
  "novelty_level": "medium",
  "evidence_strength": "single_source",
  "memory_action": "write",
  "alert_level": "watch",
  "confidence": 0.55,
  "evidence_item_ids": ["x:123"],
  "source_ids": ["x:example_user"]
}
```

Accepted values:

- `event_type`: `material_price_change`, `supply_disruption`, `company_order`, `geopolitical_update`, `policy_signal`, `macro_data`, `market_rumor`, `official_disclosure`, `market_price_action`, `fund_flow`, `earnings_update`, `industry_chain_signal`, `other`
- `relation_to_memory`: `new_event`, `event_update`, `confirmation`, `contradiction`, `repeat`, `noise`
- `changed_dimensions`: common values include `price`, `supply`, `demand`, `orders`, `capacity`, `policy`, `risk_level`, `liquidity`, `rates`, `earnings`, `valuation`, `sentiment`, `positioning`, `timeline`, `official_status`, `market_expectation`
- `time_horizon`: `intraday`, `days`, `weeks`, `months`, `quarters`, `years`

`information_units` are recorded in `memory_update_*.json`, `run_metrics_*.json`, audit, and source observations. They do not create long-run entity/event/macro files by themselves; accepted long-run memory still comes from `entity_updates`, `event_updates`, and `macro_updates`.

`event_clusters` should be emitted before claim updates when multiple posts discuss the same event:

```json
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
```

Claim updates should reuse the cluster's `cluster_id`. `event_clusters` are not written to `memory/events/` unless a corresponding `event_updates` item is accepted.

Accepted claim updates in `entity_updates`, `event_updates`, and `macro_updates` should include diff fields when the analyzer can infer them:

```json
{
  "what_changed": "相对旧记忆，本次增量是市场开始把液冷业务弹性和算力基础设施扩张联系起来。",
  "changed_since": "last_memory",
  "prior_claim_refs": ["entity_claim:previous-liquid-cooling-demand"]
}
```

Accepted values:

- `changed_since`: `last_memory`, `recent_run`, `unknown`

`entity_updates.thesis_update` is the first thesis-memory layer. It is embedded in entity memory instead of using a separate `memory/theses/` directory for now:

```json
{
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
}
```

Accepted thesis values:

- `direction`: `bull`, `bear`, `neutral`, `mixed`
- `thesis_status`: `active`, `watch`, `strengthened`, `weakened`, `invalidated`, `superseded`

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
  "information_units": [
    {
      "information_unit_id": "info:yingweike-liquid-cooling-angle",
      "cluster_id": "xcluster:liquid-cooling-20260428",
      "event_type": "industry_chain_signal",
      "relation_to_memory": "new_event",
      "subject": "英维克液冷/温控业务",
      "claim": "市场开始把英维克液冷/温控业务弹性和算力基础设施扩张联系起来。",
      "what_changed": "相对旧记忆，本次新增的是产业链需求传导角度，不是已验证订单。",
      "changed_dimensions": ["market_expectation", "demand"],
      "affected_entities": ["cn_equity:英维克"],
      "affected_themes": ["AI/算力", "液冷/温控"],
      "market_mechanism": "算力基础设施扩张可能提升液冷需求，从而影响收入弹性和估值预期。",
      "time_horizon": "quarters",
      "verification_status": "plausible",
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
      "why_it_matters": "影响市场对公司收入弹性和估值的预期。",
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
  "event_updates": [
    {
      "cluster_id": "xcluster:hormuz-20260428",
      "event_id": "geopolitics:iran-hormuz",
      "title": "伊朗-霍尔木兹海峡局势",
      "timestamp": "2026-04-14T10:00:00Z",
      "claim": "市场开始交易海峡航运受阻风险，可能影响原油和航运资产预期。",
      "verification_status": "unverified",
      "importance": "high",
      "what_changed": "相对近期事件记忆，讨论焦点从地缘言论升级为航运受阻和油价影响。",
      "changed_since": "recent_run",
      "prior_claim_refs": [],
      "signal_evaluation": {
        "signal_type": "new_fact",
        "novelty_level": "high",
        "evidence_strength": "single_source",
        "memory_action": "write",
        "alert_level": "important",
        "confidence": 0.4
      },
      "evidence_item_ids": ["x:456"],
      "source_ids": ["x:example_user"]
    }
  ],
  "macro_updates": [],
  "source_assessments": [
    {
      "source_id": "x:example_user",
      "source_type": "commentary",
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
  "alert_candidates": [
    {
      "title": "液冷链条讨论出现中等新增角度",
      "reason": "相对既有记忆，新增关注温控业务弹性，但证据仍是单一社交来源。",
      "alert_level": "watch",
      "related_entity_ids": ["cn_equity:英维克"],
      "evidence_item_ids": ["x:123"],
      "source_ids": ["x:example_user"]
    }
  ],
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
- `memory/contradictions/`: one file per suspected contradiction
- `memory/audit/`: one audit record per memory update id
- `memory/index.json`: rebuilt index of all memory files

## Memory Audit

`apply-memory` writes or reuses `memory/audit/<update-id>.json` for every parsed memory update. This is the file-backend version of a future `memory_updates` table.

Each audit record includes:

- update status: `auto_applied` or `already_applied`
- linked artifacts: summary, memory update JSON, run metrics, analysis input, prompt, collector batch, and raw data when available
- input evidence ids and event cluster ids
- update counts by memory type
- changed memory files, before/after hashes, before/after content snapshots, and unified diffs
- `user_feedback`, currently null and reserved for later correction workflows

The audit directory is excluded from memory diff snapshots, and rerunning the same summary does not overwrite the first audit record for that `update_id`.

## Write Rules

`apply-memory` skips structured updates when:

- `verification_status` is `rejected`
- `action` is `ignore`, `reject`, `skip`, or `no_op`
- `novelty` says the update is duplicate or low value
- `signal_evaluation.memory_action` is `skip` or `reject`
- `signal_evaluation.signal_type` is `noise`
- `signal_evaluation.novelty_level` is `none`

For accepted updates, `apply-memory` derives a stable `claim_id` when the analyzer does not provide one. This gives idempotent writes and prevents one summary retry from inflating memory.

Accepted claim updates store `cluster_id`, `signal_evaluation`, `what_changed`, `changed_since`, `prior_claim_refs`, `last_valuable_at`, `status`, and optional `decay_score` in the file backend. These fields are the first layer of diff tracking and memory pollution control; they do not yet implement automatic decay.

When an accepted `entity_updates` item includes `thesis_update`, the file backend also updates `memory/entities/<entity-id>.json`:

- `claims.<claim_id>.thesis_ids`: links the claim to one or more thesis records
- `theses.<thesis_id>`: stores title, direction, status, bull/bear cases, watchpoints, invalidation points, catalysts, related claims, and update history
- `recent_thesis_ids`: keeps recent thesis context available to the next analyzer prompt

This intentionally keeps thesis memory inside entity memory for the current stage. A separate thesis backend can be introduced later only if cross-entity thesis queries become a real bottleneck.

Accepted `source_assessments.source_profile` updates are normalized into `memory/sources/<source-id>.json`:

- `source_type`: `primary`, `official`, `analyst`, `aggregator`, `trader`, `media`, `commentary`, `noise`, `unknown`
- `topic_scores`: topic-to-score map from 0 to 1; `topic_strength` remains a backward-compatible alias
- `repeat_tendency`: `low`, `medium`, `high`, `unknown`
- `repeat_rate`, `hit_rate`, `trust_score`: floats from 0 to 1
- `valuable_count`: non-negative count, incremented for valuable source updates when no explicit count is supplied
- `marketing_tendency`, `emotion_tendency`: `low`, `medium`, `high`, `unknown`
- `primary_source_score`: float from 0 to 1; use it as a soft score, not a boolean
- `confirmation_required`: `none`, `low`, `medium`, `high`, `multi_source`, `official`, `unknown`
- `bias_tags`: observed stance or behavior tags

The system also maintains source observation fields from parsed analysis units:

- `metrics`: deterministic counters such as `observed_count`, `valuable_count`, `high_novelty_count`, `repeat_count`, `noise_count`, `skipped_count`, `contradiction_count`, and `alert_count`
- `rates`: derived from `metrics`, including `valuable_rate`, `high_novelty_rate`, `repeat_rate`, `noise_rate`, and `skipped_rate`
- `topic_counts`: per-topic observed / valuable / high-novelty counters
- `contribution_history`: bounded history of valuable, high-novelty, alert-worthy, or contradictory source contributions

Analyzer output should not manually invent `metrics`, `rates`, `topic_counts`, or `contribution_history`. `apply-memory` updates those fields from `event_clusters`, `signal_evaluations`, accepted claim updates, and `contradictions`.

`contradictions` are written to `memory/contradictions/<contradiction-id>.json` and indexed. They are deliberately observational:

- `conflict_type`: `source_conflict`, `data_conflict`, `official_unverified`
- `severity`: `low`, `medium`, `high`
- required semantic fields: `claim`, `conflicts_with`
- optional links: `related_entity_ids`, `related_event_ids`, `related_macro_ids`, `related_thesis_ids`

Recording a contradiction does not automatically mark any related claim as false, rejected, or superseded. That decision should remain a later verification step.

## Human vs Agent Ownership

Manual source policy should live in configuration or future profile files, not in generated memory. Examples:

- source trust tier
- source bias tags
- required confirmation level
- whether a source is official

Generated memory in `memory/sources/` is for observed behavior and agent notes. It should not overwrite human policy.
