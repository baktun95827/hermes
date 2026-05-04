from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
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
from .memory_store import MemoryBackend, StateManager, ThemeNormalizer, create_memory_backend
from .schemas import (
    clean_text,
    coerce_string_list,
    normalize_account_name,
    unique_preserving_order,
)


@dataclass(frozen=True)
class AnalysisInputBuildResult:
    run_id: str
    generated_at: str
    collector_batch_path: Path
    analysis_input_path: Path
    prompt_path: Path
    report_path: Path
    run_metrics_path: Path
    item_count: int
    recommendation_count: int
    keyword_count: int

    def to_stdout(self) -> str:
        return "\n".join(
            [
                f"Analysis Input: {self.analysis_input_path}",
                f"Prompt: {self.prompt_path}",
                f"Report: {self.report_path}",
                f"Run Metrics: {self.run_metrics_path}",
            ]
        ) + "\n"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d_%H%M%S")


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
        self.counter: Counter[str] = Counter()

    def process(self, all_tweets: list[dict[str, Any]]) -> None:
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
    all_tweets = [tweet for tweets in account_tweets.values() for tweet in tweets]

    if not all_tweets:
        return "本次监控无新推文。"

    all_tweets.sort(key=lambda item: item.get("created_at") or "", reverse=True)

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
            engagement.append(f"likes {tweet['like_count']}")
        if tweet.get("retweet_count"):
            engagement.append(f"reposts {tweet['retweet_count']}")
        if tweet.get("reply_count"):
            engagement.append(f"replies {tweet['reply_count']}")
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
    counter: Counter[str] = Counter()
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

    memory_update_contract = """{
  "primary_themes": [],
  "secondary_themes": {},
  "account_notes": {},
  "information_units": [],
  "event_clusters": [],
  "signal_evaluations": [],
  "entity_updates": [],
  "event_updates": [],
  "macro_updates": [],
  "source_assessments": [],
  "alert_candidates": [],
  "contradictions": []
}"""

    return f"""你是一个偏金融与地缘风险的社交信号分析助手。

## 任务
将输入材料按主题归类，用中文输出结构化简报；同时抽取有价值的 claim，用于维护标的、事件、宏观和来源记忆。

## 输出要求
1. 先写可直接阅读的中文简报
2. 正文结束后追加一节 `### MEMORY_UPDATE`
3. `### MEMORY_UPDATE` 后面必须是严格合法 JSON，不要写注释，不要写尾逗号
4. 如果没有值得进入记忆的新信息，保留空数组/空对象

## MEMORY_UPDATE JSON 顶层结构
```json
{memory_update_contract}
```

## 抽取规则
1. 单一社交媒体或手动输入通常只能标为 `unverified` 或 `plausible`，只有多源或官方信息支持时才标为 `confirmed`
2. `verification_status` 使用 `unverified`、`plausible`、`confirmed`、`superseded`、`rejected`
3. `signal_type` 使用 `new_fact`、`new_angle`、`confirmation`、`repeat`、`noise`
4. `novelty_level` 使用 `high`、`medium`、`low`、`none`
5. `evidence_strength` 使用 `weak`、`single_source`、`multi_source`、`official`
6. `memory_action` 使用 `write`、`merge`、`skip`、`supersede`、`reject`
7. 手动输入不是事实来源本身；需要验证的材料应清楚标注验证状态和证据强度
8. 对金融标的、地缘事件、宏观趋势，先抽取 information_units，再决定是否合并为 event_clusters 或写入 entity/event/macro memory
9. 重复、噪音或无新增价值的信息应该使用 `skip` 或不进入结构化更新
10. `account_notes` 的 key 使用不带 `@` 的用户名
{theme_hint}
## 历史上下文
{history_context if history_context else "（首次运行，无历史数据）"}

## 发现数据
{discovery_section or "（本次无额外发现）"}

## 本次输入数据
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
    collector_batch_file: str | Path | None,
) -> Path | None:
    if collector_batch_file:
        return resolve_path(Path(config["base_dir"]), str(collector_batch_file))
    latest_path = clean_text(latest_payload.get("paths", {}).get("collector_batch"))
    if latest_path:
        return Path(latest_path).expanduser().resolve()
    return None


def build_analysis_input(
    *,
    config_path: str,
    collector_batch_path: str | Path | None = None,
) -> AnalysisInputBuildResult:
    config = load_config(config_path)
    latest_run_file = Path(config["latest_run_file"])
    latest_payload = read_latest_manifest(latest_run_file) or {}
    resolved_collector_batch_path = resolve_latest_or_collector_batch_path(
        config=config,
        latest_payload=latest_payload,
        collector_batch_file=collector_batch_path,
    )
    if resolved_collector_batch_path is None or not resolved_collector_batch_path.exists():
        raise FileNotFoundError(
            f"collector_batch file not found: {resolved_collector_batch_path or ''}"
        )

    collector_batch = read_json_file(resolved_collector_batch_path, {})
    if not collector_batch:
        raise ValueError(f"invalid collector_batch file: {resolved_collector_batch_path}")

    latest_paths = (
        latest_payload.get("paths") if isinstance(latest_payload.get("paths"), dict) else {}
    )
    latest_collector_batch = clean_text(latest_paths.get("collector_batch"))
    uses_latest_collector_batch = False
    if latest_collector_batch:
        try:
            uses_latest_collector_batch = (
                Path(latest_collector_batch).expanduser().resolve()
                == resolved_collector_batch_path.resolve()
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
    all_tweets = [tweet for tweets in account_tweets.values() for tweet in tweets]
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
    full_report = f"X 监控报告 — {now_str}\n\n{raw_report}\n{discovery_section}"
    analysis_input_payload = {
        "schema_version": "signal-radar-analysis-input/v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "config_path": config["config_path"],
        "collector_batch_path": str(resolved_collector_batch_path),
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
        "collector_batch_path": str(resolved_collector_batch_path),
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
    latest_payload["paths"]["collector_batch"] = str(resolved_collector_batch_path)
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

    return AnalysisInputBuildResult(
        run_id=run_id,
        generated_at=generated_at,
        collector_batch_path=resolved_collector_batch_path,
        analysis_input_path=artifact_paths["analysis_input"],
        prompt_path=artifact_paths["prompt"],
        report_path=artifact_paths["report"],
        run_metrics_path=run_metrics_path,
        item_count=len(all_tweets),
        recommendation_count=len(recommendations),
        keyword_count=len(keywords),
    )
