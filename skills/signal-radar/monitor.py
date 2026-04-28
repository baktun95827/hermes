#!/usr/bin/env python3
"""
Signal Radar for Hermes.

Commands:
  - collect: scrape configured X accounts and write collector artifacts
  - build-analysis-input: build the prompt and replayable analysis input artifact
  - latest: print the latest artifact manifest or selected fields from it
  - apply-memory: parse a Hermes summary and submit MEMORY_UPDATE to memory backend
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signal_radar.audit import (
    build_memory_audit_record,
    read_memory_audit_record,
    snapshot_memory_tree,
    write_memory_audit_record,
)
from signal_radar.config import (
    atomic_write_json,
    atomic_write_text,
    build_artifact_paths,
    build_legacy_state_paths,
    load_config,
    read_json_file,
    read_latest_manifest,
    resolve_path,
    write_latest_manifest,
)
from signal_radar.memory_update import build_memory_update_id, parse_memory_update
from signal_radar.memory_store import (
    MemoryBackend,
    StateManager,
    ThemeNormalizer,
    create_memory_backend,
)
from signal_radar.schemas import *
from signal_radar.x_collector import (
    FetchResult,
    PlaywrightFetcher,
    build_collect_run_metrics,
    build_collection_warning,
    build_x_collector_batch,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d_%H%M%S")



def count_high_novelty_event_clusters(event_clusters: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in event_clusters
        if build_signal_evaluation(item).get("novelty_level") == "high"
    )


def count_high_novelty_signals(signal_evaluations: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in signal_evaluations
        if build_signal_evaluation(item).get("novelty_level") == "high"
    )


def build_memory_context(memory_store: MemoryBackend) -> dict[str, Any]:
    return {
        "recent_theme_memories": memory_store.get_recent_theme_memories(),
        "recent_entity_memories": memory_store.get_recent_entity_memories(),
        "recent_event_memories": memory_store.get_recent_event_memories(),
        "recent_macro_memories": memory_store.get_recent_macro_memories(),
        "recent_source_memories": memory_store.get_recent_source_memories(),
        "account_notes": memory_store.get_account_notes(),
    }


def format_history_context(memory_context: dict[str, Any]) -> str:
    recent_theme_memories = memory_context.get("recent_theme_memories") or []
    recent_entity_memories = memory_context.get("recent_entity_memories") or []
    recent_event_memories = memory_context.get("recent_event_memories") or []
    recent_macro_memories = memory_context.get("recent_macro_memories") or []
    recent_source_memories = memory_context.get("recent_source_memories") or []
    account_notes = memory_context.get("account_notes") or {}

    history_context = ""
    if recent_theme_memories:
        history_context += "\n近期主题记忆:\n"
        for item in recent_theme_memories:
            secondaries = item.get("top_secondary_themes") or item.get(
                "latest_secondary_themes", []
            )
            secondary_text = ", ".join(secondaries) if secondaries else "（暂无二级主题）"
            history_context += (
                f"  - {item['primary_theme']}: 二级主题 {secondary_text}；"
                f"出现 {item['run_count']} 次\n"
            )
    if account_notes:
        history_context += "\n各账号历史画像:\n"
        for user, note in account_notes.items():
            history_context += f"  @{user}: {note}\n"
    if recent_entity_memories:
        history_context += "\n近期标的/公司记忆:\n"
        for item in recent_entity_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            changes = "；".join(item.get("recent_changes") or [])
            theses = "；".join(item.get("recent_theses") or [])
            history_context += (
                f"  - {item['display_name'] or item['entity_id']}"
                f" [{item.get('entity_type') or 'unknown'}]: {claims}\n"
            )
            if changes:
                history_context += f"    recent changes: {changes}\n"
            if theses:
                history_context += f"    thesis: {theses}\n"
    if recent_event_memories:
        history_context += "\n近期事件记忆:\n"
        for item in recent_event_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            history_context += f"  - {item['title'] or item['event_id']}: {claims}\n"
            changes = "；".join(item.get("recent_changes") or [])
            if changes:
                history_context += f"    recent changes: {changes}\n"
    if recent_macro_memories:
        history_context += "\n近期宏观记忆:\n"
        for item in recent_macro_memories:
            claims = "；".join(item.get("recent_claims") or []) or "（暂无近期 claim）"
            history_context += f"  - {item['topic'] or item['macro_id']}: {claims}\n"
            changes = "；".join(item.get("recent_changes") or [])
            if changes:
                history_context += f"    recent changes: {changes}\n"
    if recent_source_memories:
        history_context += "\n近期来源画像:\n"
        for item in recent_source_memories:
            topic_parts = []
            for topic in item.get("top_topics") or []:
                if not isinstance(topic, dict):
                    continue
                topic_name = clean_text(topic.get("topic"))
                score = topic.get("score")
                observed_count = topic.get("observed_count") or 0
                valuable_count = topic.get("valuable_count") or 0
                if topic_name:
                    if score is not None:
                        topic_parts.append(
                            f"{topic_name}:{score},obs={observed_count},val={valuable_count}"
                        )
                    else:
                        topic_parts.append(
                            f"{topic_name}:obs={observed_count},val={valuable_count}"
                        )
            topic_text = ", ".join(topic_parts) if topic_parts else "（暂无主题评分）"
            trust_score = item.get("trust_score")
            trust_text = f"{trust_score}" if trust_score is not None else "unknown"
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            rates = item.get("rates") if isinstance(item.get("rates"), dict) else {}
            style_profile = (
                item.get("style_profile")
                if isinstance(item.get("style_profile"), dict)
                else {}
            )
            primary_source_score = style_profile.get("primary_source_score")
            primary_text = (
                f"{primary_source_score}"
                if primary_source_score is not None
                else "unknown"
            )
            history_context += (
                f"  - {item['display_name'] or item['source_id']}"
                f" [{item.get('source_type') or 'unknown'}]: "
                f"trust={trust_text}, repeat={item.get('repeat_tendency') or 'unknown'}, "
                f"confirm={item.get('confirmation_required') or 'unknown'}, "
                f"primary_score={primary_text}, "
                f"observed={metrics.get('observed_count', 0)}, "
                f"valuable={metrics.get('valuable_count', 0)}, "
                f"valuable_rate={rates.get('valuable_rate', 0)}, "
                f"repeat_rate={rates.get('repeat_rate', 0)}, "
                f"noise_rate={rates.get('noise_rate', 0)}, "
                f"marketing={style_profile.get('marketing_tendency') or 'unknown'}, "
                f"emotion={style_profile.get('emotion_tendency') or 'unknown'}, "
                f"topics={topic_text}\n"
            )
            if item.get("latest_assessment"):
                history_context += f"    assessment: {item['latest_assessment']}\n"
    return history_context


class DiscoveryEngine:
    def __init__(self, monitored: list[str], min_interactions: int = 3):
        self.monitored = {normalize_account_name(item).lower() for item in monitored}
        self.min_interactions = min_interactions
        self.counter = Counter()

    def process(self, all_tweets: list[dict[str, Any]]):
        for tweet in all_tweets:
            for mention in tweet.get("mentions", []):
                if mention.lower() not in self.monitored:
                    self.counter[mention] += 1

    def get_recommendations(self) -> list[dict[str, Any]]:
        return [
            {"username": username, "count": count}
            for username, count in self.counter.most_common(10)
            if count >= self.min_interactions
        ]


def format_raw_report(account_tweets: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    all_tweets = [
        tweet
        for tweets in account_tweets.values()
        for tweet in tweets
    ]

    if not all_tweets:
        return "本次监控无新推文。"

    all_tweets.sort(
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )

    for tweet in all_tweets:
        lines.append("--- TWEET ---")
        lines.append(f"作者: @{tweet['author']}")
        if tweet.get("source_account") and tweet["source_account"] != tweet["author"]:
            lines.append(f"监控源: @{tweet['source_account']}")
        if tweet.get("created_at"):
            lines.append(f"时间: {tweet['created_at']}")
        if tweet.get("tweet_url"):
            lines.append(f"链接: {tweet['tweet_url']}")
        if tweet.get("is_retweet"):
            lines.append("类型: 转推/转发")
        lines.append("正文:")
        lines.append(tweet["text"])
        if tweet.get("quoted_text"):
            lines.append(f"引用推文: {tweet['quoted_text']}")
        if tweet.get("images"):
            lines.append(f"图片: {', '.join(tweet['images'])}")
        if tweet.get("has_video"):
            lines.append("[包含视频]")
        engagement = []
        if tweet.get("like_count"):
            engagement.append(f"❤️ {tweet['like_count']}")
        if tweet.get("retweet_count"):
            engagement.append(f"🔁 {tweet['retweet_count']}")
        if tweet.get("reply_count"):
            engagement.append(f"💬 {tweet['reply_count']}")
        if engagement:
            lines.append(f"互动: {' | '.join(engagement)}")
        lines.append("")

    return "\n".join(lines)


def format_discovery_section(
    recommendations: list[dict[str, Any]],
    keywords: list[str],
) -> str:
    lines: list[str] = []
    if recommendations:
        lines.append("── 发现推荐 ──")
        for item in recommendations[:5]:
            lines.append(f"  @{item['username']} — 被提及 {item['count']} 次")
        lines.append("")
    if keywords:
        lines.append("── 热点关键词 ──")
        lines.append(f"  {', '.join(keywords)}")
    return "\n".join(lines)


def extract_keywords(tweets: list[dict[str, Any]], top_n: int = 10) -> list[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on",
        "at", "for", "of", "and", "or", "but", "not", "with", "this",
        "that", "it", "be", "as", "by", "from", "has", "have", "had",
        "rt", "https", "http", "co", "amp", "just", "will", "can",
        "about", "more", "than", "been", "would", "could", "should",
        "their", "there", "they", "them", "then", "what", "when",
        "your", "you", "its", "all", "very", "much",
    }
    counter = Counter()
    for tweet in tweets:
        text = re.sub(r"https?://\S+", "", tweet.get("text", ""))
        text = re.sub(r"@\w+", "", text)
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
        for word in words:
            if word not in stopwords and len(word) > 2:
                counter[word] += 1
    return [word for word, _ in counter.most_common(top_n)]


def build_llm_prompt(
    raw_report: str,
    discovery_section: str,
    memory_store: MemoryBackend,
    predefined_themes: list[str],
) -> str:
    history_context = format_history_context(build_memory_context(memory_store))

    theme_hint = ""
    if predefined_themes:
        theme_hint = (
            "\n用户关注的主题方向（优先归入这些类别，也可创建新类别）:\n"
            f"  {', '.join(predefined_themes)}\n"
        )

    memory_update_example = """### MEMORY_UPDATE
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
      "summary": "多条内容讨论液冷温控链条，但核心增量仍需验证。",
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
        "confidence": 0.6,
        "evidence_count": 1,
        "source_count": 1
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
      "claim": "社交媒体开始交易海峡航运受阻风险，可能影响原油和航运资产预期。",
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
"""

    return f"""你是一个偏金融与地缘风险的社交信号分析助手。

## 任务
将以下推文按主题归类，用中文输出结构化简报；同时抽取有价值的 claim，用于维护标的、事件、宏观和来源记忆。

## 输出要求
1. 先写可直接发送到 Telegram 的正文
2. 正文结束后，再追加 `### MEMORY_UPDATE`
3. `### MEMORY_UPDATE` 不给最终用户看，只用于提交到当前 memory backend
4. 如果本次没有新推文，明确写“本次无新推文”，不要编造主题

## 正文格式
### 📋 简报标题（一句话概括本次最重要的发现）

**🔖 主题1: [主题名]**
- [要点1] (@作者)
  链接: [推文链接]
  [如有图片，保留图片 URL]

**📊 趋势观察**
- 与上次报告相比的变化或新趋势

**🔍 发现推荐**
- 推荐关注的新账号及理由

## MEMORY_UPDATE 格式
{memory_update_example}

## 规则
1. 同一一级主题下合并不同账号的相关推文
2. 保留推文原始含义，不要过度简化
3. 保留所有图片 URL（用 [图片: URL] 格式）
4. 保留推文链接
5. 高互动推文可标注 🔥
6. `监控源` 与 `作者` 不同时，说明这是转推/转发线索
7. 尽量复用已有一级主题；只有真的出现新方向时再创建新的一级主题
8. 二级主题应该放在所属一级主题下面，不要把事件级名称直接当一级主题
9. 对金融标的、地缘事件、宏观趋势，先抽取 claim，再判断是否值得进入 memory
10. 明显虚假、重复且无增量、或低价值的信息不要写入 `entity_updates` / `event_updates` / `macro_updates`
11. 单一社交媒体来源通常只能标为 `unverified` 或 `plausible`；只有多源或官方信息支持时才标为 `confirmed`
12. `verification_status` 只能使用 `unverified`、`plausible`、`confirmed`、`superseded`、`rejected`
13. `claim_type` 可使用 `fact`、`thesis`、`rumor`、`signal`；观点和推演不要写成事实
14. 每个重要 claim 都应尽量带 `signal_evaluation`：`signal_type` 用 `new_fact`、`new_angle`、`confirmation`、`repeat`、`noise`；`novelty_level` 用 `high`、`medium`、`low`、`none`；`evidence_strength` 用 `weak`、`single_source`、`multi_source`、`official`
15. `memory_action` 用 `write`、`merge`、`skip`、`supersede`、`reject`；重复、噪音或无新增价值的信息应该使用 `skip` 或不进入结构化更新
16. 先用 `event_clusters` 把同一件事合并成事件簇，再让 `entity_updates` / `event_updates` / `macro_updates` 引用同一个 `cluster_id`
17. `cluster_id` 格式建议为 `xcluster:<主题>-<日期>`；同一事件被多账号转述时只能算一个 cluster
18. 对写入 `entity_updates` / `event_updates` / `macro_updates` 的重要 claim，尽量填写 `what_changed`、`changed_since`、`prior_claim_refs`，说明相对旧记忆或近期 run 变化在哪里
19. `changed_since` 只能使用 `last_memory`、`recent_run`、`unknown`
20. `alert_candidates` 只表示候选告警，不等于一定发送；只有 `watch`、`important`、`urgent` 才值得写入
21. `contradictions` 只记录疑似冲突，不自动判定真假；`conflict_type` 用 `source_conflict`、`data_conflict`、`official_unverified`，`severity` 用 `low`、`medium`、`high`
22. `entity_updates` 用于股票、公司、行业链条等可命名对象；新标的可以直接创建
23. 如果标的信息会改变投资假设，在对应 `entity_updates` 内嵌 `thesis_update`，维护 `bull_case`、`bear_case`、`key_watchpoints`、`invalidation_points`、`catalysts`、`thesis_status`
24. `thesis_update.thesis_status` 用 `active`、`watch`、`strengthened`、`weakened`、`invalidated`、`superseded`；`direction` 用 `bull`、`bear`、`neutral`、`mixed`
25. `event_updates` 用于会随时间发展的事件，按时间线追加
26. `macro_updates` 用于宏观趋势、经济环境、流动性、能源价格等跨标的背景
27. `source_assessments` 用于记录账号或来源的可信度、偏见和需要确认程度；`source_profile` 优先使用 `source_type`、`topic_scores`、`repeat_tendency`、`repeat_rate`、`hit_rate`、`trust_score`、`valuable_count`、`marketing_tendency`、`emotion_tendency`、`primary_source_score`、`confirmation_required`、`bias_tags`
28. `source_type` 用 `primary`、`official`、`analyst`、`aggregator`、`trader`、`media`、`commentary`、`noise`；不确定用 `unknown`
29. 来源画像里的 `metrics`、`rates`、`topic_counts`、`contribution_history` 由系统从 event clusters 和 claim updates 自动维护，不要在 MEMORY_UPDATE 里手工编造
30. `### MEMORY_UPDATE` 后面必须是严格合法的 JSON，JSON 不要写注释，不要写尾逗号，`account_notes` 的 key 使用不带 `@` 的用户名
{theme_hint}
## 历史上下文
{history_context if history_context else "（首次运行，无历史数据）"}

## 发现数据
{discovery_section or "（本次无额外发现）"}

## 本次推文数据
{raw_report}
"""


def collector_item_to_report_tweet(item: dict[str, Any]) -> dict[str, Any]:
    author_payload = item.get("author") if isinstance(item.get("author"), dict) else {}
    source_meta = (
        item.get("source_meta") if isinstance(item.get("source_meta"), dict) else {}
    )
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    relations = item.get("relations") if isinstance(item.get("relations"), dict) else {}
    media = item.get("media") if isinstance(item.get("media"), list) else []

    author = normalize_account_name(
        author_payload.get("entity_id")
        or author_payload.get("handle")
        or author_payload.get("display_name")
        or ""
    )
    source_account = normalize_account_name(source_meta.get("source_account") or author)
    image_urls = [
        clean_text(media_item.get("url"))
        for media_item in media
        if isinstance(media_item, dict)
        and media_item.get("type") == "image"
        and clean_text(media_item.get("url"))
    ]
    mentioned_users = coerce_string_list(source_meta.get("mentioned_users"))
    for entity_id in coerce_string_list(relations.get("mentioned_entities")):
        mentioned_users.append(entity_id.split(":", 1)[-1])

    return {
        "id": clean_text(item.get("item_id")),
        "text": clean_text(item.get("text")),
        "author": author,
        "source_account": source_account,
        "created_at": clean_text(item.get("published_at")),
        "is_retweet": bool(relations.get("is_repost")),
        "mentions": unique_preserving_order(
            [
                normalize_account_name(user)
                for user in mentioned_users
                if normalize_account_name(user)
            ]
        ),
        "images": image_urls,
        "has_video": any(
            isinstance(media_item, dict) and media_item.get("type") == "video"
            for media_item in media
        )
        or bool(source_meta.get("has_video")),
        "quoted_text": clean_text(source_meta.get("quoted_text")),
        "retweet_count": int(metrics.get("reposts") or 0),
        "like_count": int(metrics.get("likes") or 0),
        "reply_count": int(metrics.get("replies") or 0),
        "tweet_url": clean_text(item.get("url")),
    }


def collector_batch_to_account_tweets(
    collector_batch: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    items = collector_batch.get("items")
    if not isinstance(items, list):
        return {}

    account_tweets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        tweet = collector_item_to_report_tweet(item)
        if not tweet.get("text"):
            continue
        source_account = tweet.get("source_account") or tweet.get("author") or "unknown"
        account_tweets.setdefault(source_account, []).append(tweet)
    return account_tweets


def resolve_latest_or_collector_batch_path(
    config: dict[str, Any],
    latest_payload: dict[str, Any],
    collector_batch_file: str | None,
) -> Path | None:
    if collector_batch_file:
        return resolve_path(Path(config["base_dir"]), collector_batch_file)
    latest_path = clean_text(latest_payload.get("paths", {}).get("collector_batch"))
    if latest_path:
        return Path(latest_path).expanduser().resolve()
    return None


def build_analysis_input(config_path: str, collector_batch_file: str | None) -> int:
    config = load_config(config_path)
    latest_run_file = Path(config["latest_run_file"])
    latest_payload = read_latest_manifest(latest_run_file) or {}
    collector_batch_path = resolve_latest_or_collector_batch_path(
        config=config,
        latest_payload=latest_payload,
        collector_batch_file=collector_batch_file,
    )
    if collector_batch_path is None or not collector_batch_path.exists():
        print(f"collector_batch 文件不存在: {collector_batch_path or ''}")
        return 1

    collector_batch = read_json_file(collector_batch_path, {})
    if not collector_batch:
        print(f"collector_batch 格式错误: {collector_batch_path}")
        return 1

    latest_paths = (
        latest_payload.get("paths") if isinstance(latest_payload.get("paths"), dict) else {}
    )
    latest_collector_batch = clean_text(latest_paths.get("collector_batch"))
    uses_latest_collector_batch = False
    if latest_collector_batch:
        try:
            uses_latest_collector_batch = (
                Path(latest_collector_batch).expanduser().resolve()
                == collector_batch_path.resolve()
            )
        except OSError:
            uses_latest_collector_batch = False

    run_id = clean_text(
        collector_batch.get("collector_run_id") or latest_payload.get("run_id")
    ) or timestamp_slug()
    generated_at = utc_now().isoformat()
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = build_artifact_paths(output_dir, run_id)

    account_tweets = collector_batch_to_account_tweets(collector_batch)
    all_tweets = [
        tweet
        for tweets in account_tweets.values()
        for tweet in tweets
    ]
    discovery = DiscoveryEngine(
        config["accounts"],
        config["discovery"]["min_interactions"],
    )
    if config["discovery"]["enabled"]:
        discovery.process(all_tweets)
    recommendations = discovery.get_recommendations()
    keywords = extract_keywords(all_tweets)
    raw_report = format_raw_report(account_tweets)
    discovery_section = format_discovery_section(recommendations, keywords)

    normalizer = ThemeNormalizer(
        canonical_primary_themes=config.get("themes", []),
        alias_config=config.get("theme_aliases", {}),
        secondary_alias_config=config.get("secondary_theme_aliases", {}),
    )
    memory_store = create_memory_backend(config, normalizer=normalizer)
    state = StateManager(
        config["state_file"],
        legacy_paths=build_legacy_state_paths(
            config["base_dir"],
            config["state_file"],
        ),
    )
    with memory_store.lock():
        memory_store.migrate_legacy_state(state)
        if not memory_store.index_path.exists():
            memory_store.rebuild_index()
        memory_context = build_memory_context(memory_store)
        prompt = build_llm_prompt(
            raw_report=raw_report,
            discovery_section=discovery_section,
            memory_store=memory_store,
            predefined_themes=config.get("themes", []),
        )

    now_str = utc_now().strftime("%Y-%m-%d %H:%M UTC")
    full_report = f"📊 X 监控报告 — {now_str}\n\n{raw_report}\n{discovery_section}"
    analysis_input_payload = {
        "schema_version": "signal-radar-analysis-input/v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "config_path": config["config_path"],
        "collector_batch_path": str(collector_batch_path),
        "prompt_path": str(artifact_paths["prompt"]),
        "report_path": str(artifact_paths["report"]),
        "memory_backend": config["memory_backend"],
        "memory_index": str(memory_store.index_path),
        "predefined_themes": config.get("themes", []),
        "collector": {
            "schema_version": collector_batch.get("schema_version"),
            "source": collector_batch.get("source"),
            "collector_run_id": collector_batch.get("collector_run_id"),
            "item_count": len(all_tweets),
        },
        "discovery": {
            "recommendations": recommendations,
            "keywords": keywords,
        },
        "memory_context": memory_context,
        "normalized_items": collector_batch.get("items", []),
    }
    atomic_write_json(artifact_paths["analysis_input"], analysis_input_payload)
    atomic_write_text(artifact_paths["prompt"], prompt, encoding="utf-8")
    atomic_write_text(artifact_paths["report"], full_report, encoding="utf-8")

    run_metrics_path = (
        Path(latest_paths.get("run_metrics"))
        if uses_latest_collector_batch and latest_paths.get("run_metrics")
        else artifact_paths["run_metrics"]
    )
    run_metrics_payload = read_json_file(
        run_metrics_path,
        {
            "schema_version": "signal-radar-run-metrics/v1",
            "run_id": run_id,
            "status": "unknown",
            "collector": {},
            "analysis": {},
            "memory": {},
        },
    )
    run_metrics_payload["schema_version"] = "signal-radar-run-metrics/v1"
    run_metrics_payload["run_id"] = run_metrics_payload.get("run_id") or run_id
    run_metrics_payload["updated_at"] = generated_at
    run_metrics_payload["analysis_input"] = {
        "built": True,
        "built_at": generated_at,
        "item_count": len(all_tweets),
        "recommendation_count": len(recommendations),
        "keyword_count": len(keywords),
        "collector_batch_path": str(collector_batch_path),
        "analysis_input_path": str(artifact_paths["analysis_input"]),
        "prompt_path": str(artifact_paths["prompt"]),
    }
    atomic_write_json(run_metrics_path, run_metrics_payload)

    latest_payload.setdefault("paths", {})
    latest_payload["run_id"] = run_id
    latest_payload["generated_at"] = (
        latest_payload.get("generated_at")
        if uses_latest_collector_batch and latest_payload.get("generated_at")
        else generated_at
    )
    latest_payload["config_path"] = config["config_path"]
    latest_payload["paths"]["collector_batch"] = str(collector_batch_path)
    latest_payload["paths"]["analysis_input"] = str(artifact_paths["analysis_input"])
    latest_payload["paths"]["prompt"] = str(artifact_paths["prompt"])
    latest_payload["paths"]["report"] = str(artifact_paths["report"])
    latest_payload["paths"]["run_metrics"] = str(run_metrics_path)
    latest_payload["paths"]["memory_index"] = str(memory_store.index_path)
    latest_payload["paths"]["state"] = config["state_file"]
    latest_payload["paths"]["memory_dir"] = config["memory_dir"]
    if not uses_latest_collector_batch or not latest_payload["paths"].get("summary"):
        latest_payload["paths"]["summary"] = str(artifact_paths["summary"])
    if not uses_latest_collector_batch or not latest_payload["paths"].get("memory_update"):
        latest_payload["paths"]["memory_update"] = str(artifact_paths["memory_update"])
    if not uses_latest_collector_batch or not latest_payload["paths"].get("data"):
        latest_payload["paths"]["data"] = str(artifact_paths["data"])
    latest_payload["paths"].setdefault("warning", None)
    latest_payload["memory_backend"] = config["memory_backend"]
    latest_payload["analysis_input_built"] = True
    latest_payload["analysis_input"] = {
        "path": str(artifact_paths["analysis_input"]),
        "built_at": generated_at,
        "item_count": len(all_tweets),
        "recommendation_count": len(recommendations),
        "keyword_count": len(keywords),
    }
    latest_payload["run_metrics"] = run_metrics_payload
    if not isinstance(latest_payload.get("summary"), dict):
        latest_payload["summary"] = {}
    latest_payload["summary"]["analysis_input_item_count"] = len(all_tweets)
    latest_payload["summary"]["recommendation_count"] = len(recommendations)
    latest_payload["summary"]["keyword_count"] = len(keywords)
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"🧩 Analysis Input: {artifact_paths['analysis_input']}")
    print(f"📝 Prompt: {artifact_paths['prompt']}")
    print(f"📄 报告: {artifact_paths['report']}")
    print(f"📈 Run Metrics: {run_metrics_path}")
    return 0


async def collect(config_path: str) -> int:
    collect_started_at_dt = utc_now()
    collect_started_at = collect_started_at_dt.isoformat()
    collect_started_monotonic = time.monotonic()
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "请先安装: pip install playwright pyyaml --break-system-packages "
            "&& playwright install chromium --with-deps"
        )
        return 1

    config = load_config(config_path)
    accounts = config["accounts"]
    if not accounts:
        print("❌ 请在 config.yaml 中配置要监控的账号")
        return 1

    state = StateManager(
        config["state_file"],
        legacy_paths=build_legacy_state_paths(
            config["base_dir"],
            config["state_file"],
        ),
    )
    output_dir = Path(config["output_dir"])
    latest_run_file = Path(config["latest_run_file"])
    base_dir = Path(config["base_dir"])

    last_run = state.data.get("last_run")
    if last_run:
        print(f"📅 上次运行: {last_run}")

    print(f"🚀 开始监控 {len(accounts)} 个账号: {', '.join('@' + item for item in accounts)}")

    fetch_results: list[FetchResult] = []
    async with async_playwright() as pw:
        fetcher = PlaywrightFetcher(
            cookies_file=Path(config["auth"]["cookies_file"]),
            debug_dir=base_dir,
        )
        await fetcher.start(pw)
        try:
            for index, username in enumerate(accounts):
                result = await fetcher.fetch_user_tweets(
                    username=username,
                    state=state,
                    max_tweets=config["tweets_per_account"],
                    scroll_count=config.get("scroll_count", 5),
                )
                fetch_results.append(result)
                if index < len(accounts) - 1:
                    delay = config.get("delay_between_accounts", 5)
                    print(f"  ⏳ 等待 {delay} 秒...")
                    await asyncio.sleep(delay)
        finally:
            await fetcher.close()

    account_tweets = {result.username: result.tweets for result in fetch_results}
    all_tweets = [
        tweet
        for result in fetch_results
        for tweet in result.tweets
    ]

    warning = build_collection_warning(fetch_results)
    if warning:
        print(f"\n{warning}")

    now = utc_now()
    run_id = timestamp_slug(now)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    collected_at = now.isoformat()
    runtime_seconds = time.monotonic() - collect_started_monotonic
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = build_artifact_paths(output_dir, run_id)
    collector_batch = build_x_collector_batch(
        run_id=run_id,
        collected_at=collected_at,
        accounts=accounts,
        fetch_results=fetch_results,
        warning=warning,
        config_path=config["config_path"],
    )

    data_payload = {
        "run_id": run_id,
        "timestamp": now_str,
        "config_path": config["config_path"],
        "collector_batch_schema": COLLECTOR_BATCH_SCHEMA_VERSION,
        "collector_item_schema": COLLECTOR_ITEM_SCHEMA_VERSION,
        "collector_batch_path": str(artifact_paths["collector_batch"]),
        "analysis_input_path": str(artifact_paths["analysis_input"]),
        "run_metrics_path": str(artifact_paths["run_metrics"]),
        "account_results": [asdict(result) for result in fetch_results],
        "account_tweets": account_tweets,
        "warning": warning,
    }
    atomic_write_json(artifact_paths["collector_batch"], collector_batch)
    atomic_write_json(artifact_paths["data"], data_payload)
    run_metrics = build_collect_run_metrics(
        run_id=run_id,
        started_at=collect_started_at,
        finished_at=collected_at,
        runtime_seconds=runtime_seconds,
        accounts=accounts,
        fetch_results=fetch_results,
        all_tweets=all_tweets,
        warning=warning,
    )
    atomic_write_json(artifact_paths["run_metrics"], run_metrics)

    warning_path: str | None = None
    if warning:
        atomic_write_text(artifact_paths["warning"], warning, encoding="utf-8")
        warning_path = str(artifact_paths["warning"])

    state.save(update_last_run=False)

    latest_payload = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "config_path": config["config_path"],
        "paths": {
            "data": str(artifact_paths["data"]),
            "collector_batch": str(artifact_paths["collector_batch"]),
            "analysis_input": str(artifact_paths["analysis_input"]),
            "prompt": str(artifact_paths["prompt"]),
            "report": str(artifact_paths["report"]),
            "summary": str(artifact_paths["summary"]),
            "memory_update": str(artifact_paths["memory_update"]),
            "run_metrics": str(artifact_paths["run_metrics"]),
            "memory_index": str(Path(config["memory_dir"]) / "index.json"),
            "state": config["state_file"],
            "warning": warning_path,
            "memory_dir": config["memory_dir"],
        },
        "memory_backend": config["memory_backend"],
        "summary": {
            "new_tweet_count": len(all_tweets),
            "runtime_seconds": round(runtime_seconds, 3),
        },
        "account_results": [asdict(result) for result in fetch_results],
        "run_metrics": run_metrics,
        "analysis_input_built": False,
        "memory_update_applied": False,
    }
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"\n{'=' * 60}")
    print(f"📊 X 监控报告 — {now_str}")
    print(f"   新推文: {len(all_tweets)} 条")
    print(
        "   账号: "
        + ", ".join(
            f"@{result.username}({result.new_tweet_count})"
            for result in fetch_results
        )
    )
    print(f"{'=' * 60}")
    print(f"\n📁 数据: {artifact_paths['data']}")
    print(f"📦 Collector Batch: {artifact_paths['collector_batch']}")
    print(f"📈 Run Metrics: {artifact_paths['run_metrics']}")
    print("🧩 下一步: build-analysis-input 生成 prompt 和 analysis_input")
    print(f"🧭 最新索引: {latest_run_file}")
    if warning_path:
        print(f"⚠️ 告警: {warning_path}")

    return 0


def latest(config_path: str, field: str | None) -> int:
    config = load_config(config_path)
    latest_run_file = Path(config["latest_run_file"])
    payload = read_latest_manifest(latest_run_file)
    if payload is None:
        print(f"未找到 latest manifest: {latest_run_file}")
        return 1

    if not field:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if field == "manifest":
        print(str(latest_run_file))
        return 0

    if field == "new_tweet_count":
        print(payload.get("summary", {}).get("new_tweet_count", 0))
        return 0

    if field == "memory_dir":
        print(payload.get("paths", {}).get("memory_dir") or "")
        return 0

    if field == "memory_index":
        print(payload.get("paths", {}).get("memory_index") or "")
        return 0

    if field == "memory_backend":
        print(payload.get("memory_backend") or "file")
        return 0

    if field == "state":
        print(payload.get("paths", {}).get("state") or "")
        return 0

    if field in {
        "data",
        "collector_batch",
        "analysis_input",
        "prompt",
        "report",
        "summary",
        "memory_update",
        "memory_audit",
        "run_metrics",
        "warning",
    }:
        value = payload.get("paths", {}).get(field) or ""
        print(value)
        return 0

    print(f"不支持的 field: {field}")
    return 1


def apply_memory(config_path: str, summary_file: str) -> int:
    config = load_config(config_path)
    base_dir = Path(config["base_dir"])
    summary_path = resolve_path(base_dir, summary_file)
    if not summary_path.exists():
        print(f"summary 文件不存在: {summary_path}")
        return 1

    summary_text = summary_path.read_text(encoding="utf-8")
    parsed = parse_memory_update(summary_text)
    if (
        not parsed["primary_themes"]
        and not parsed["secondary_themes"]
        and not parsed["account_notes"]
        and not parsed["event_clusters"]
        and not parsed["signal_evaluations"]
        and not parsed["entity_updates"]
        and not parsed["event_updates"]
        and not parsed["macro_updates"]
        and not parsed["source_assessments"]
        and not parsed["alert_candidates"]
        and not parsed["contradictions"]
    ):
        print("未在 summary 中找到可解析的 MEMORY_UPDATE")
        return 1

    latest_run_file = Path(config["latest_run_file"])
    latest_payload = read_latest_manifest(latest_run_file) or {}
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    stored_summary_path = summary_path
    preferred_summary_path = (
        Path(latest_payload.get("paths", {}).get("summary"))
        if latest_payload.get("paths", {}).get("summary")
        else None
    )
    if preferred_summary_path:
        should_use_preferred_path = (
            preferred_summary_path.resolve() == summary_path.resolve()
            or not preferred_summary_path.exists()
            or (
                latest_payload.get("run_id")
                and preferred_summary_path.name.startswith(
                    f"summary_{latest_payload['run_id']}"
                )
            )
        )
        if should_use_preferred_path and preferred_summary_path.resolve() != summary_path.resolve():
            atomic_write_text(preferred_summary_path, summary_text, encoding="utf-8")
            stored_summary_path = preferred_summary_path
        elif preferred_summary_path.resolve() == summary_path.resolve():
            stored_summary_path = preferred_summary_path

    update_id = build_memory_update_id(
        summary_text=summary_text,
        summary_path=stored_summary_path.resolve(),
        run_id=(
            str(latest_payload.get("run_id"))
            if latest_payload.get("run_id")
            else None
        ),
    )

    state = StateManager(
        config["state_file"],
        legacy_paths=build_legacy_state_paths(
            config["base_dir"],
            config["state_file"],
        ),
    )
    normalizer = ThemeNormalizer(
        canonical_primary_themes=config.get("themes", []),
        alias_config=config.get("theme_aliases", {}),
        secondary_alias_config=config.get("secondary_theme_aliases", {}),
    )
    memory_store = create_memory_backend(config, normalizer=normalizer)
    memory_before_snapshot = snapshot_memory_tree(memory_store.root)
    seen_at = utc_now().isoformat()
    theme_updates = 0
    account_updates = 0
    entity_updates = 0
    event_updates = 0
    macro_updates = 0
    source_updates = 0
    source_observation_updates = 0
    contradiction_updates = 0
    with memory_store.lock():
        memory_store.migrate_legacy_state(state)

        normalized_secondary_mapping = memory_store.normalizer.normalize_secondary_mapping(
            parsed["secondary_themes"]
        )
        normalized_primary = memory_store.normalizer.normalize_primary_themes(
            parsed["primary_themes"] + list(normalized_secondary_mapping.keys())
        )

        for primary_theme in normalized_primary:
            if memory_store.update_theme_memory(
                primary_theme=primary_theme,
                secondary_themes=normalized_secondary_mapping.get(primary_theme, []),
                seen_at=seen_at,
                update_id=update_id,
            ):
                theme_updates += 1

        for username, note in parsed["account_notes"].items():
            if memory_store.update_account_note(
                username=username,
                note=note,
                seen_at=seen_at,
                update_id=update_id,
                primary_themes=normalized_primary,
                secondary_themes=normalized_secondary_mapping,
            ):
                account_updates += 1

        for update in parsed["entity_updates"]:
            if memory_store.update_entity_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                entity_updates += 1

        for update in parsed["event_updates"]:
            if memory_store.update_event_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                event_updates += 1

        for update in parsed["macro_updates"]:
            if memory_store.update_macro_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                macro_updates += 1

        for update in parsed["source_assessments"]:
            if memory_store.update_source_assessment(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                source_updates += 1

        observed_cluster_ids: set[str] = set()
        for update in parsed["event_clusters"]:
            cluster_id = clean_text(update.get("cluster_id"))
            if cluster_id and coerce_string_list(update.get("source_ids")):
                observed_cluster_ids.add(cluster_id)
            updated_sources = memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="event_cluster",
            )
            source_observation_updates += updated_sources

        for update in parsed["signal_evaluations"]:
            if clean_text(update.get("cluster_id")) in observed_cluster_ids:
                continue
            source_observation_updates += memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="signal_evaluation",
            )

        for collection_name, updates in (
            ("entity_update", parsed["entity_updates"]),
            ("event_update", parsed["event_updates"]),
            ("macro_update", parsed["macro_updates"]),
        ):
            for update in updates:
                if clean_text(update.get("cluster_id")) in observed_cluster_ids:
                    continue
                source_observation_updates += memory_store.update_source_observation(
                    update=update,
                    seen_at=seen_at,
                    update_id=update_id,
                    observation_kind=collection_name,
                )

        for update in parsed["contradictions"]:
            source_observation_updates += memory_store.update_source_observation(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
                observation_kind="contradiction",
            )
            if memory_store.update_contradiction_memory(
                update=update,
                seen_at=seen_at,
                update_id=update_id,
            ):
                contradiction_updates += 1

        if (
            theme_updates
            or account_updates
            or entity_updates
            or event_updates
            or macro_updates
            or source_updates
            or source_observation_updates
            or contradiction_updates
            or not memory_store.index_path.exists()
        ):
            memory_store.rebuild_index()

    state.save(update_last_run=False)
    memory_after_snapshot = snapshot_memory_tree(memory_store.root)

    memory_update_path = (
        Path(latest_payload.get("paths", {}).get("memory_update"))
        if latest_payload.get("paths", {}).get("memory_update")
        else output_dir / f"memory_update_{timestamp_slug()}.json"
    )
    memory_update_path.parent.mkdir(parents=True, exist_ok=True)
    run_metrics_path = (
        Path(latest_payload.get("paths", {}).get("run_metrics"))
        if latest_payload.get("paths", {}).get("run_metrics")
        else output_dir / f"run_metrics_{timestamp_slug()}.json"
    )
    run_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    memory_updates_total = (
        theme_updates
        + account_updates
        + entity_updates
        + event_updates
        + macro_updates
        + source_updates
        + source_observation_updates
        + contradiction_updates
    )
    update_counts = {
        "memory_updates": memory_updates_total,
        "theme_updates": theme_updates,
        "account_updates": account_updates,
        "entity_updates": entity_updates,
        "event_updates": event_updates,
        "macro_updates": macro_updates,
        "source_updates": source_updates,
        "source_observation_updates": source_observation_updates,
        "contradiction_updates": contradiction_updates,
    }
    already_applied = memory_updates_total == 0

    payload = {
        "update_id": update_id,
        "applied_at": seen_at,
        "summary_file": str(stored_summary_path),
        "state_file": config["state_file"],
        "primary_themes": normalized_primary,
        "secondary_themes": normalized_secondary_mapping,
        "account_notes": parsed["account_notes"],
        "event_clusters": parsed["event_clusters"],
        "event_cluster_count": len(parsed["event_clusters"]),
        "signal_evaluations": parsed["signal_evaluations"],
        "entity_updates": parsed["entity_updates"],
        "event_updates": parsed["event_updates"],
        "macro_updates": parsed["macro_updates"],
        "source_assessments": parsed["source_assessments"],
        "alert_candidates": parsed["alert_candidates"],
        "alert_candidate_count": len(parsed["alert_candidates"]),
        "contradictions": parsed["contradictions"],
        "contradiction_count": len(parsed["contradictions"]),
        "memory_dir": config["memory_dir"],
        "memory_backend": config["memory_backend"],
        "memory_index": str(memory_store.index_path),
        "theme_updates": theme_updates,
        "account_updates": account_updates,
        "entity_updates_applied": entity_updates,
        "event_updates_applied": event_updates,
        "macro_updates_applied": macro_updates,
        "source_updates_applied": source_updates,
        "source_observation_updates_applied": source_observation_updates,
        "contradiction_updates_applied": contradiction_updates,
        "already_applied": already_applied,
    }

    audit_record = build_memory_audit_record(
        update_id=update_id,
        status="already_applied" if already_applied else "auto_applied",
        applied_at=seen_at,
        memory_dir=memory_store.root,
        memory_backend=config["memory_backend"],
        before_snapshot=memory_before_snapshot,
        after_snapshot=memory_after_snapshot,
        parsed_memory_update=parsed,
        update_counts=update_counts,
        latest_payload=latest_payload,
        summary_file=str(stored_summary_path),
        memory_update_file=str(memory_update_path),
        run_metrics_file=str(run_metrics_path),
        config_path=config["config_path"],
    )
    memory_audit_path = write_memory_audit_record(memory_store.root, audit_record)
    effective_audit_record = read_memory_audit_record(memory_audit_path) or audit_record
    payload["memory_audit"] = str(memory_audit_path)
    payload["memory_audit_changed_file_count"] = effective_audit_record[
        "changed_file_count"
    ]
    atomic_write_json(memory_update_path, payload)

    run_metrics_payload = read_json_file(
        run_metrics_path,
        {
            "schema_version": "signal-radar-run-metrics/v1",
            "run_id": latest_payload.get("run_id"),
            "status": "unknown",
            "collector": {},
        },
    )
    run_metrics_payload["schema_version"] = "signal-radar-run-metrics/v1"
    run_metrics_payload["run_id"] = run_metrics_payload.get(
        "run_id"
    ) or latest_payload.get("run_id")
    run_metrics_payload["updated_at"] = seen_at
    run_metrics_payload["analysis"] = {
        "memory_update_id": update_id,
        "event_clusters": len(parsed["event_clusters"]),
        "high_novelty_events": count_high_novelty_event_clusters(
            parsed["event_clusters"]
        ),
        "signal_evaluations": len(parsed["signal_evaluations"]),
        "high_novelty_signals": count_high_novelty_signals(
            parsed["signal_evaluations"]
        ),
        "alert_candidates": len(parsed["alert_candidates"]),
        "contradictions": len(parsed["contradictions"]),
    }
    run_metrics_payload["memory"] = {
        **update_counts,
        "already_applied": payload["already_applied"],
        "memory_audit": str(memory_audit_path),
        "memory_audit_changed_file_count": effective_audit_record[
            "changed_file_count"
        ],
    }
    atomic_write_json(run_metrics_path, run_metrics_payload)

    latest_payload.setdefault("paths", {})
    latest_payload["paths"]["summary"] = str(stored_summary_path)
    latest_payload["paths"]["memory_update"] = str(memory_update_path)
    latest_payload["paths"]["memory_audit"] = str(memory_audit_path)
    latest_payload["paths"]["run_metrics"] = str(run_metrics_path)
    latest_payload["paths"]["memory_index"] = str(memory_store.index_path)
    latest_payload["paths"]["state"] = config["state_file"]
    latest_payload["memory_backend"] = config["memory_backend"]
    latest_payload["memory_update_applied"] = True
    latest_payload["memory_update"] = payload
    latest_payload["memory_audit"] = {
        "path": str(memory_audit_path),
        "status": effective_audit_record["status"],
        "changed_file_count": effective_audit_record["changed_file_count"],
    }
    latest_payload["run_metrics"] = run_metrics_payload
    if not isinstance(latest_payload.get("summary"), dict):
        latest_payload["summary"] = {}
    latest_payload["summary"]["event_cluster_count"] = len(parsed["event_clusters"])
    latest_payload["summary"]["high_novelty_event_count"] = (
        count_high_novelty_event_clusters(parsed["event_clusters"])
    )
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"🧠 已更新记忆: {config['state_file']}")
    print(f"📝 Summary: {stored_summary_path}")
    print(f"📦 MEMORY_UPDATE: {memory_update_path}")
    print(f"📈 Run Metrics: {run_metrics_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Signal Radar for Hermes")
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR / "config.yaml"),
        help="配置文件路径",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("collect", help="抓取推文并生成采集 artifacts")

    analysis_input_parser = subparsers.add_parser(
        "build-analysis-input",
        help="基于 collector_batch 和 memory 生成 analysis_input/prompt",
    )
    analysis_input_parser.add_argument(
        "--collector-batch",
        help="collector_batch JSON 路径；默认使用 latest_run.json",
    )

    latest_parser = subparsers.add_parser("latest", help="读取 latest_run.json")
    latest_parser.add_argument(
        "--field",
        choices=[
            "manifest",
            "data",
            "collector_batch",
            "analysis_input",
            "prompt",
            "report",
            "summary",
            "memory_update",
            "memory_audit",
            "run_metrics",
            "memory_dir",
            "memory_backend",
            "memory_index",
            "state",
            "warning",
            "new_tweet_count",
        ],
        help="仅读取某个字段",
    )

    apply_parser = subparsers.add_parser(
        "apply-memory",
        help="解析 summary 中的 MEMORY_UPDATE 并提交到当前 memory backend",
    )
    apply_parser.add_argument(
        "--summary-file",
        required=True,
        help="包含 MEMORY_UPDATE 的总结文件路径",
    )

    return parser


def parse_cli_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    argv = sys.argv[1:]
    extracted_config: str | None = None
    cleaned_argv: list[str] = []
    index = 0

    while index < len(argv):
        arg = argv[index]
        if arg == "--config":
            if index + 1 >= len(argv):
                parser.error("--config 需要一个路径值")
            extracted_config = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            extracted_config = arg.split("=", 1)[1]
            index += 1
            continue
        cleaned_argv.append(arg)
        index += 1

    args = parser.parse_args(cleaned_argv)
    if extracted_config is not None:
        args.config = extracted_config
    return args


async def async_main(args: argparse.Namespace) -> int:
    if args.command in (None, "collect"):
        return await collect(args.config)
    if args.command == "build-analysis-input":
        return build_analysis_input(args.config, args.collector_batch)
    if args.command == "latest":
        return latest(args.config, args.field)
    if args.command == "apply-memory":
        return apply_memory(args.config, args.summary_file)
    print(f"未知命令: {args.command}")
    return 1


def main() -> int:
    parser = build_parser()
    args = parse_cli_args(parser)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
