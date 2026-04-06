#!/usr/bin/env python3
"""
X Monitor for Hermes.

Commands:
  - collect: scrape configured X accounts and write prompt/report artifacts
  - latest: print the latest artifact manifest or selected fields from it
  - apply-memory: parse a Hermes summary and persist MEMORY_UPDATE into state
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "accounts": [],
    "tweets_per_account": 15,
    "auth": {"cookies_file": "cookies.json"},
    "discovery": {"enabled": True, "min_interactions": 3},
    "scroll_count": 5,
    "delay_between_accounts": 5,
    "state_file": "state.json",
    "output_dir": "reports",
    "latest_run_file": "latest_run.json",
    "themes": [],
}

STATUS_OK = "ok"
STATUS_LOGIN_WALL = "login_wall"
STATUS_NO_VISIBLE_TWEETS = "no_visible_tweets"
STATUS_ERROR = "error"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d_%H%M%S")


def unique_preserving_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def normalize_account_name(value: str) -> str:
    return str(value).strip().lstrip("@")


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_config_path(raw_path: str) -> Path:
    raw = Path(raw_path).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    candidates = [
        (Path.cwd() / raw).resolve(),
        (SCRIPT_DIR / raw).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            print("请先安装: pip install pyyaml --break-system-packages")
            sys.exit(1)
        loaded = yaml.safe_load(text) or {}
    else:
        loaded = json.loads(text)

    if not isinstance(loaded, dict):
        print(f"配置文件格式错误: {path}")
        sys.exit(1)
    return loaded


def load_config(path: str) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    loaded = load_yaml_or_json(config_path)
    config = merge_dicts(DEFAULT_CONFIG, loaded)
    base_dir = config_path.parent

    config["accounts"] = [
        normalize_account_name(item)
        for item in config.get("accounts", [])
        if normalize_account_name(item)
    ]
    config["auth"]["cookies_file"] = str(
        resolve_path(base_dir, config["auth"]["cookies_file"])
    )
    config["state_file"] = str(resolve_path(base_dir, config["state_file"]))
    config["output_dir"] = str(resolve_path(base_dir, config["output_dir"]))
    config["latest_run_file"] = str(
        resolve_path(base_dir, config["latest_run_file"])
    )
    config["config_path"] = str(config_path)
    config["base_dir"] = str(base_dir.resolve())
    return config


def read_latest_manifest(latest_run_file: Path) -> dict[str, Any] | None:
    if not latest_run_file.exists():
        return None
    return json.loads(latest_run_file.read_text(encoding="utf-8"))


def write_latest_manifest(latest_run_file: Path, payload: dict[str, Any]) -> None:
    latest_run_file.parent.mkdir(parents=True, exist_ok=True)
    latest_run_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_artifact_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    return {
        "data": output_dir / f"data_{run_id}.json",
        "prompt": output_dir / f"prompt_{run_id}.txt",
        "report": output_dir / f"report_{run_id}.txt",
        "summary": output_dir / f"summary_{run_id}.txt",
        "memory_update": output_dir / f"memory_update_{run_id}.json",
        "warning": output_dir / f"warning_{run_id}.txt",
    }


class StateManager:
    """
    持久化状态：
    - seen_ids: 已处理过的推文 ID 集合（去重）
    - theme_history: 历史主题追踪
    - account_notes: 每个账号的累积观察
    """

    def __init__(self, state_file: str):
        self.path = Path(state_file)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {
            "seen_ids": [],
            "theme_history": [],
            "account_notes": {},
            "last_run": None,
        }

    def save(self):
        self.data["last_run"] = utc_now().isoformat()
        self.data["seen_ids"] = self.data["seen_ids"][-2000:]
        self.data["theme_history"] = self.data["theme_history"][-50:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_seen(self, tweet_id: str) -> bool:
        return tweet_id in self.data["seen_ids"]

    def mark_seen(self, tweet_id: str):
        if tweet_id and tweet_id not in self.data["seen_ids"]:
            self.data["seen_ids"].append(tweet_id)

    def add_themes(self, themes: list[str]):
        clean = unique_preserving_order([item for item in themes if item])
        if not clean:
            return
        self.data["theme_history"].append(
            {"time": utc_now().isoformat(), "themes": clean}
        )

    def update_account_notes(self, username: str, note: str):
        username = normalize_account_name(username)
        note = note.strip()
        if username and note:
            self.data["account_notes"][username] = note

    def get_account_notes(self) -> dict[str, str]:
        notes = self.data.get("account_notes", {})
        return notes if isinstance(notes, dict) else {}

    def get_recent_themes(self, n: int = 10) -> list[str]:
        all_themes: list[str] = []
        for entry in self.data.get("theme_history", [])[-n:]:
            if isinstance(entry, dict):
                all_themes.extend(entry.get("themes", []))
        return unique_preserving_order(all_themes)


@dataclass
class FetchResult:
    username: str
    tweets: list[dict[str, Any]]
    status: str
    visible_tweet_count: int = 0
    new_tweet_count: int = 0
    page_url: str | None = None
    page_title: str | None = None
    error: str | None = None
    debug_path: str | None = None


def normalize_same_site(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }
    return mapping.get(normalized)


def load_cookie_export(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"cookies 文件不存在: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    cookies: list[dict[str, Any]] = []

    if isinstance(raw, dict):
        for name, value in raw.items():
            cookies.append(
                {
                    "name": str(name),
                    "value": str(value),
                    "domain": ".x.com",
                    "path": "/",
                }
            )
        return cookies

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            cookie = {
                "name": str(name),
                "value": str(item.get("value", "")),
                "domain": str(item.get("domain") or ".x.com"),
                "path": str(item.get("path") or "/"),
            }
            if "secure" in item:
                cookie["secure"] = bool(item["secure"])
            if "httpOnly" in item:
                cookie["httpOnly"] = bool(item["httpOnly"])
            same_site = normalize_same_site(
                item.get("sameSite") or item.get("same_site")
            )
            if same_site:
                cookie["sameSite"] = same_site
            expires = item.get("expires")
            if expires not in (None, "", -1):
                try:
                    cookie["expires"] = float(expires)
                except (TypeError, ValueError):
                    pass
            cookies.append(cookie)
        if cookies:
            return cookies

    raise ValueError("cookies.json 格式不支持，需为对象或 cookie 数组")


class PlaywrightFetcher:
    def __init__(self, cookies_file: Path, debug_dir: Path):
        self.cookies_file = cookies_file
        self.debug_dir = debug_dir
        self.browser = None
        self.context = None

    async def start(self, pw):
        self.browser = await pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        cookies = load_cookie_export(self.cookies_file)
        await self.context.add_cookies(cookies)
        print("✅ 浏览器已启动，cookies 已加载")

    async def close(self):
        if self.browser:
            await self.browser.close()

    async def fetch_user_tweets(
        self,
        username: str,
        state: StateManager,
        max_tweets: int = 15,
        scroll_count: int = 5,
    ) -> FetchResult:
        page = await self.context.new_page()
        page_title = None
        page_url = None

        try:
            url = f"https://x.com/{username}"
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            for _ in range(scroll_count):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1.3)

            page_url = page.url
            page_title = await page.title()

            if await self._is_login_wall(page):
                debug_path = await self._capture_debug(page, username)
                print(f"  ❌ @{username}: 落到登录墙")
                return FetchResult(
                    username=username,
                    tweets=[],
                    status=STATUS_LOGIN_WALL,
                    page_url=page_url,
                    page_title=page_title,
                    debug_path=debug_path,
                )

            tweet_elements = await page.query_selector_all(
                "article[data-testid='tweet']"
            )
            visible_tweet_count = len(tweet_elements)
            if visible_tweet_count == 0:
                debug_path = await self._capture_debug(page, username)
                print(f"  ❌ @{username}: 页面可见推文为 0")
                return FetchResult(
                    username=username,
                    tweets=[],
                    status=STATUS_NO_VISIBLE_TWEETS,
                    visible_tweet_count=0,
                    page_url=page_url,
                    page_title=page_title,
                    debug_path=debug_path,
                )

            tweets: list[dict[str, Any]] = []
            for el in tweet_elements:
                if len(tweets) >= max_tweets:
                    break
                tweet = await self._parse_tweet(el, username)
                if not tweet or not tweet.get("text"):
                    continue
                tweet_id = tweet.get("id")
                if tweet_id and state.is_seen(tweet_id):
                    continue
                tweets.append(tweet)
                state.mark_seen(tweet_id)

            print(
                f"  📥 @{username}: 可见 {visible_tweet_count} 条，新增 {len(tweets)} 条"
            )
            return FetchResult(
                username=username,
                tweets=tweets,
                status=STATUS_OK,
                visible_tweet_count=visible_tweet_count,
                new_tweet_count=len(tweets),
                page_url=page_url,
                page_title=page_title,
            )
        except Exception as exc:
            debug_path = await self._capture_debug(page, username)
            print(f"  ❌ @{username}: 抓取失败 — {exc}")
            return FetchResult(
                username=username,
                tweets=[],
                status=STATUS_ERROR,
                page_url=page.url if page else page_url,
                page_title=page_title,
                error=str(exc),
                debug_path=debug_path,
            )
        finally:
            await page.close()

    async def _capture_debug(self, page, username: str) -> str | None:
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / f"debug_{username}.png"
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return None

    async def _is_login_wall(self, page) -> bool:
        url = page.url.lower()
        if "/i/flow/login" in url:
            return True

        body_text = (await page.text_content("body") or "").lower()
        login_markers = (
            "sign in",
            "log in",
            "join x today",
            "登录",
            "注册",
            "现在加入",
            "create account",
        )
        if any(marker in body_text for marker in login_markers):
            return True

        return bool(await page.query_selector("input[name='text']"))

    async def _parse_tweet(
        self, el, source_account: str
    ) -> dict[str, Any] | None:
        try:
            text_nodes = await el.query_selector_all('[data-testid="tweetText"]')
            if not text_nodes:
                return None

            text = await text_nodes[0].inner_text()
            quoted_text = ""
            if len(text_nodes) > 1:
                quoted_text = await text_nodes[-1].inner_text()

            author = source_account
            tweet_id = None
            created_at = None
            tweet_url = None

            time_el = await el.query_selector("time")
            if time_el:
                created_at = await time_el.get_attribute("datetime")
                href = await time_el.evaluate(
                    "node => node.closest('a')?.getAttribute('href')"
                )
                if href:
                    match = re.search(r"/([^/]+)/status/(\d+)", str(href))
                    if match:
                        author = match.group(1)
                        tweet_id = match.group(2)
                        tweet_url = f"https://x.com/{author}/status/{tweet_id}"

            images: list[str] = []
            img_elements = await el.query_selector_all(
                '[data-testid="tweetPhoto"] img'
            )
            for img in img_elements:
                src = await img.get_attribute("src")
                if src and "pbs.twimg.com" in src:
                    clean = re.sub(r"name=\w+", "name=large", src)
                    if clean not in images:
                        images.append(clean)

            has_video = bool(
                await el.query_selector('[data-testid="videoPlayer"]')
            )
            stats = await self._parse_stats(el)
            is_retweet = text.startswith("RT @") or bool(
                await el.query_selector('[data-testid="socialContext"]')
            )

            return {
                "id": tweet_id,
                "text": text,
                "author": author,
                "source_account": source_account,
                "created_at": created_at,
                "is_retweet": is_retweet,
                "mentions": extract_mentions(text),
                "images": images,
                "has_video": has_video,
                "quoted_text": quoted_text,
                "retweet_count": stats.get("retweet", 0),
                "like_count": stats.get("like", 0),
                "reply_count": stats.get("reply", 0),
                "tweet_url": tweet_url,
            }
        except Exception:
            return None

    async def _parse_stats(self, el) -> dict[str, int]:
        stats: dict[str, int] = {}
        for key in ["reply", "retweet", "like"]:
            try:
                btn = await el.query_selector(f'[data-testid="{key}"]')
                if not btn:
                    continue
                aria = await btn.get_attribute("aria-label") or ""
                parsed = parse_metric_value(aria)
                if parsed is not None:
                    stats[key] = parsed
            except Exception:
                pass
        return stats


def parse_metric_value(label: str) -> int | None:
    if not label:
        return None

    match = re.search(
        r"(\d+(?:[.,]\d+)?(?:,\d{3})?)\s*([kmb万亿]?)",
        label.strip().lower(),
    )
    if not match:
        return None

    raw_number = match.group(1)
    suffix = match.group(2)

    if suffix:
        if "," in raw_number and "." not in raw_number:
            parts = raw_number.split(",")
            if len(parts[-1]) != 3:
                raw_number = ".".join(parts)
            else:
                raw_number = "".join(parts)
        raw_number = raw_number.replace(",", "")
        try:
            value = float(raw_number)
        except ValueError:
            return None
        multiplier = {
            "k": 1_000,
            "m": 1_000_000,
            "b": 1_000_000_000,
            "万": 10_000,
            "亿": 100_000_000,
        }[suffix]
        return int(round(value * multiplier))

    try:
        return int(raw_number.replace(",", ""))
    except ValueError:
        return None


def extract_mentions(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"@(\w+)", text)


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
    state: StateManager,
    predefined_themes: list[str],
) -> str:
    recent_themes = state.get_recent_themes()
    account_notes = state.get_account_notes()

    history_context = ""
    if recent_themes:
        history_context += f"\n近期反复出现的主题: {', '.join(recent_themes)}\n"
    if account_notes:
        history_context += "\n各账号历史画像:\n"
        for user, note in account_notes.items():
            history_context += f"  @{user}: {note}\n"

    theme_hint = ""
    if predefined_themes:
        theme_hint = (
            "\n用户关注的主题方向（优先归入这些类别，也可创建新类别）:\n"
            f"  {', '.join(predefined_themes)}\n"
        )

    return f"""你是一个专业的 X (Twitter) 信息分析助手。

## 任务
将以下推文按主题归类，用中文输出结构化简报。

## 输出要求
1. 先写可直接发送到 Telegram 的正文
2. 正文结束后，再追加 `### MEMORY_UPDATE`
3. `### MEMORY_UPDATE` 不给最终用户看，只用于回写 state.json
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
### MEMORY_UPDATE
THEMES: [用逗号分隔的本次主题列表；如果无新推文可留空]
ACCOUNT_NOTES:
@账号1: [一句话更新该账号的内容画像]
@账号2: [一句话更新该账号的内容画像]

## 规则
1. 同一主题下合并不同账号的相关推文
2. 保留推文原始含义，不要过度简化
3. 保留所有图片 URL（用 [图片: URL] 格式）
4. 保留推文链接
5. 高互动推文可标注 🔥
6. `监控源` 与 `作者` 不同时，说明这是转推/转发线索
7. `### MEMORY_UPDATE` 必须输出
{theme_hint}
## 历史上下文
{history_context if history_context else "（首次运行，无历史数据）"}

## 发现数据
{discovery_section or "（本次无额外发现）"}

## 本次推文数据
{raw_report}
"""


def build_collection_warning(results: list[FetchResult]) -> str | None:
    if not results:
        return "⚠️ 本次运行没有任何抓取结果。"

    if any(result.visible_tweet_count > 0 for result in results):
        return None

    status_counter = Counter(result.status for result in results)
    detail_lines = [f"  - @{result.username}: {result.status}" for result in results]
    details = "\n".join(detail_lines)

    if status_counter.get(STATUS_LOGIN_WALL) == len(results):
        return (
            "⚠️ 所有账号都落到了 X 登录墙。\n"
            "账号状态:\n"
            f"{details}\n"
            "优先检查 cookies.json 是否过期，并重新导出浏览器 cookies。"
        )

    if status_counter.get(STATUS_ERROR) == len(results):
        return (
            "⚠️ 所有账号抓取都失败了。\n"
            "账号状态:\n"
            f"{details}\n"
            "请检查 Playwright/Chromium、网络连通性，以及 X 页面结构是否变化。"
        )

    return (
        "⚠️ 本次运行没有在任何账号页面看到可见推文。\n"
        "账号状态:\n"
        f"{details}\n"
        "可能原因包括 cookies 失效、页面结构变化、账号受限，或网络异常。"
    )


def parse_memory_update(summary_text: str) -> dict[str, Any]:
    lines = summary_text.splitlines()
    start_index = 0

    for index, line in enumerate(lines):
        if re.match(r"^\s*#{0,6}\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break
        if re.match(r"^\s*MEMORY_UPDATE\s*$", line, re.IGNORECASE):
            start_index = index + 1
            break

    block_lines = lines[start_index:]
    themes: list[str] = []
    account_notes: dict[str, str] = {}
    in_account_notes = False
    current_user: str | None = None

    for raw_line in block_lines:
        line = raw_line.strip()
        if not line:
            current_user = None
            continue

        themes_match = re.match(r"^THEMES\s*:\s*(.*)$", line, re.IGNORECASE)
        if themes_match:
            theme_text = themes_match.group(1).strip()
            if theme_text:
                parts = re.split(r"[,，;/|｜]+", theme_text)
                themes = unique_preserving_order(
                    [part.strip() for part in parts if part.strip()]
                )
            continue

        if re.match(r"^ACCOUNT_NOTES\s*:\s*$", line, re.IGNORECASE):
            in_account_notes = True
            current_user = None
            continue

        if not in_account_notes:
            continue

        note_match = re.match(r"^@?([A-Za-z0-9_]{1,15})\s*:\s*(.+)$", line)
        if note_match:
            current_user = normalize_account_name(note_match.group(1))
            account_notes[current_user] = note_match.group(2).strip()
            continue

        if current_user:
            account_notes[current_user] = (
                account_notes[current_user] + " " + line
            ).strip()

    return {"themes": themes, "account_notes": account_notes}


async def collect(config_path: str) -> int:
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

    state = StateManager(config["state_file"])
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

    discovery = DiscoveryEngine(
        accounts,
        config["discovery"]["min_interactions"],
    )
    if config["discovery"]["enabled"]:
        discovery.process(all_tweets)
    recommendations = discovery.get_recommendations()
    keywords = extract_keywords(all_tweets)

    raw_report = format_raw_report(account_tweets)
    discovery_section = format_discovery_section(recommendations, keywords)
    prompt = build_llm_prompt(
        raw_report=raw_report,
        discovery_section=discovery_section,
        state=state,
        predefined_themes=config.get("themes", []),
    )

    now = utc_now()
    run_id = timestamp_slug(now)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = build_artifact_paths(output_dir, run_id)

    data_payload = {
        "run_id": run_id,
        "timestamp": now_str,
        "config_path": config["config_path"],
        "account_results": [asdict(result) for result in fetch_results],
        "account_tweets": account_tweets,
        "recommendations": recommendations,
        "keywords": keywords,
        "warning": warning,
    }
    artifact_paths["data"].write_text(
        json.dumps(data_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    artifact_paths["prompt"].write_text(prompt, encoding="utf-8")
    full_report = f"📊 X 监控报告 — {now_str}\n\n{raw_report}\n{discovery_section}"
    artifact_paths["report"].write_text(full_report, encoding="utf-8")

    warning_path: str | None = None
    if warning:
        artifact_paths["warning"].write_text(warning, encoding="utf-8")
        warning_path = str(artifact_paths["warning"])

    state.save()

    latest_payload = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "config_path": config["config_path"],
        "paths": {
            "data": str(artifact_paths["data"]),
            "prompt": str(artifact_paths["prompt"]),
            "report": str(artifact_paths["report"]),
            "summary": str(artifact_paths["summary"]),
            "memory_update": str(artifact_paths["memory_update"]),
            "warning": warning_path,
        },
        "summary": {
            "new_tweet_count": len(all_tweets),
            "recommendation_count": len(recommendations),
            "keyword_count": len(keywords),
        },
        "account_results": [asdict(result) for result in fetch_results],
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
    if recommendations:
        print(f"   发现: {', '.join('@' + item['username'] for item in recommendations[:3])}")
    if keywords:
        print(f"   关键词: {', '.join(keywords[:5])}")
    print(f"{'=' * 60}")
    print(f"\n📁 数据: {artifact_paths['data']}")
    print(f"📝 Prompt: {artifact_paths['prompt']}")
    print(f"📄 报告: {artifact_paths['report']}")
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

    if field in {"data", "prompt", "report", "summary", "memory_update", "warning"}:
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
    if not parsed["themes"] and not parsed["account_notes"]:
        print("未在 summary 中找到可解析的 MEMORY_UPDATE")
        return 1

    state = StateManager(config["state_file"])
    state.add_themes(parsed["themes"])
    for username, note in parsed["account_notes"].items():
        state.update_account_notes(username, note)
    state.save()

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
    if preferred_summary_path and preferred_summary_path.resolve() != summary_path.resolve():
        preferred_summary_path.parent.mkdir(parents=True, exist_ok=True)
        preferred_summary_path.write_text(summary_text, encoding="utf-8")
        stored_summary_path = preferred_summary_path

    memory_update_path = (
        Path(latest_payload.get("paths", {}).get("memory_update"))
        if latest_payload.get("paths", {}).get("memory_update")
        else output_dir / f"memory_update_{timestamp_slug()}.json"
    )
    memory_update_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "applied_at": utc_now().isoformat(),
        "summary_file": str(stored_summary_path),
        "themes": parsed["themes"],
        "account_notes": parsed["account_notes"],
    }
    memory_update_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    latest_payload.setdefault("paths", {})
    latest_payload["paths"]["summary"] = str(stored_summary_path)
    latest_payload["paths"]["memory_update"] = str(memory_update_path)
    latest_payload["memory_update_applied"] = True
    latest_payload["memory_update"] = payload
    if "summary" not in latest_payload:
        latest_payload["summary"] = {}
    write_latest_manifest(latest_run_file, latest_payload)

    print(f"🧠 已更新记忆: {config['state_file']}")
    print(f"📝 Summary: {stored_summary_path}")
    print(f"📦 MEMORY_UPDATE: {memory_update_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X Monitor for Hermes")
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR / "config.yaml"),
        help="配置文件路径",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("collect", help="抓取推文并生成 artifacts")

    latest_parser = subparsers.add_parser("latest", help="读取 latest_run.json")
    latest_parser.add_argument(
        "--field",
        choices=[
            "manifest",
            "data",
            "prompt",
            "report",
            "summary",
            "memory_update",
            "warning",
            "new_tweet_count",
        ],
        help="仅读取某个字段",
    )

    apply_parser = subparsers.add_parser(
        "apply-memory",
        help="解析 summary 中的 MEMORY_UPDATE 并写入 state.json",
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
