from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .schemas import *


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

    def _match_status_href(self, href: str | None) -> tuple[str, str] | None:
        if not href:
            return None
        match = re.search(r"/([^/]+)/status/(\d+)", str(href))
        if not match:
            return None
        return match.group(1), match.group(2)

    async def _extract_status_metadata(
        self,
        el,
        source_account: str,
    ) -> tuple[str, str | None, str | None, str | None]:
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
            match = self._match_status_href(href)
            if match:
                author, tweet_id = match
                tweet_url = f"https://x.com/{author}/status/{tweet_id}"

        if tweet_id:
            return author, tweet_id, created_at, tweet_url

        link_elements = await el.query_selector_all('a[href*="/status/"]')
        for link_el in link_elements:
            href = await link_el.get_attribute("href")
            match = self._match_status_href(href)
            if not match:
                continue
            author, tweet_id = match
            tweet_url = f"https://x.com/{author}/status/{tweet_id}"
            break

        return author, tweet_id, created_at, tweet_url

    async def _extract_text_content(self, el) -> tuple[str, str]:
        text_candidates: list[str] = []
        quoted_text = ""

        text_nodes = await el.query_selector_all('[data-testid="tweetText"]')
        for node in text_nodes:
            value = re.sub(r"\s+", " ", (await node.inner_text() or "")).strip()
            if value and value not in text_candidates:
                text_candidates.append(value)

        if not text_candidates:
            lang_nodes = await el.query_selector_all("div[lang]")
            for node in lang_nodes[:6]:
                value = re.sub(r"\s+", " ", (await node.inner_text() or "")).strip()
                if value and value not in text_candidates:
                    text_candidates.append(value)

        if len(text_candidates) > 1:
            quoted_text = text_candidates[-1]

        return (text_candidates[0] if text_candidates else ""), quoted_text

    async def _parse_tweet(
        self, el, source_account: str
    ) -> dict[str, Any] | None:
        try:
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
            text, quoted_text = await self._extract_text_content(el)
            if not text and (images or has_video):
                media_parts: list[str] = []
                if images:
                    media_parts.append(f"{len(images)}张图片")
                if has_video:
                    media_parts.append("视频")
                text = f"[媒体推文：{', '.join(media_parts)}]"

            if not text:
                return None

            author, tweet_id, created_at, tweet_url = await self._extract_status_metadata(
                el,
                source_account,
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
                text = await btn.text_content() or ""
                parsed = parse_metric_value(aria) or parse_metric_value(text)
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


def build_x_item_id(tweet: dict[str, Any]) -> str:
    tweet_id = str(tweet.get("id") or "").strip()
    if tweet_id:
        return tweet_id

    fallback_material = "|".join(
        [
            str(tweet.get("author") or ""),
            str(tweet.get("source_account") or ""),
            str(tweet.get("created_at") or ""),
            str(tweet.get("tweet_url") or ""),
            str(tweet.get("text") or ""),
        ]
    )
    digest = hashlib.sha256(
        fallback_material.encode("utf-8")
    ).hexdigest()[:20]
    return f"synthetic-{digest}"


def build_x_author_payload(username: str) -> dict[str, Any]:
    normalized = normalize_account_name(username)
    handle = f"@{normalized}" if normalized else None
    url = f"https://x.com/{normalized}" if normalized else None
    display_name = handle or normalized or ""
    return {
        "source": X_SOURCE_ID,
        "entity_type": "account",
        "entity_id": normalized,
        "canonical_entity_id": f"{X_SOURCE_ID}:{normalized}" if normalized else None,
        "display_name": display_name,
        "handle": handle,
        "url": url,
    }


def build_x_item_url(tweet: dict[str, Any], item_id: str, author: str) -> str:
    existing = str(tweet.get("tweet_url") or "").strip()
    if existing:
        return existing
    normalized_author = normalize_account_name(author)
    if normalized_author and item_id and not item_id.startswith("synthetic-"):
        return f"https://x.com/{normalized_author}/status/{item_id}"
    if normalized_author:
        return f"https://x.com/{normalized_author}"
    return ""


def normalize_x_tweet_to_collector_item(
    tweet: dict[str, Any],
    collected_at: str,
) -> dict[str, Any]:
    author = normalize_account_name(
        tweet.get("author") or tweet.get("source_account") or ""
    )
    source_account = normalize_account_name(tweet.get("source_account") or author)
    item_id = build_x_item_id(tweet)
    image_urls = [
        str(url).strip()
        for url in tweet.get("images", [])
        if str(url).strip()
    ]
    media = [{"type": "image", "url": url} for url in image_urls]
    if tweet.get("has_video"):
        media.append({"type": "video", "url": None})

    mentions = [
        normalize_account_name(item)
        for item in tweet.get("mentions", [])
        if normalize_account_name(item)
    ]

    return {
        "schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": X_SOURCE_ID,
        "item_id": item_id,
        "canonical_id": f"{X_SOURCE_ID}:{item_id}",
        "content_type": "post",
        "published_at": tweet.get("created_at"),
        "collected_at": collected_at,
        "url": build_x_item_url(tweet, item_id, author),
        "title": None,
        "text": tweet.get("text") or "",
        "language": None,
        "author": build_x_author_payload(author),
        "metrics": {
            "likes": tweet.get("like_count", 0),
            "replies": tweet.get("reply_count", 0),
            "reposts": tweet.get("retweet_count", 0),
            "views": None,
        },
        "media": media,
        "relations": {
            "is_repost": bool(tweet.get("is_retweet")),
            "quoted_item_id": None,
            "reply_to_item_id": None,
            "mentioned_entities": [f"{X_SOURCE_ID}:{item}" for item in mentions],
        },
        "source_meta": {
            "source_account": source_account,
            "quoted_text": tweet.get("quoted_text") or None,
            "has_video": bool(tweet.get("has_video")),
            "image_urls": image_urls,
            "mentioned_users": mentions,
        },
    }


def build_collector_target(accounts: list[str]) -> dict[str, Any]:
    normalized = [
        normalize_account_name(item)
        for item in accounts
        if normalize_account_name(item)
    ]
    if len(normalized) == 1:
        username = normalized[0]
        return {
            "kind": "account",
            "id": username,
            "display_name": f"@{username}",
        }

    preview = ", ".join(f"@{item}" for item in normalized[:3])
    if len(normalized) > 3:
        preview += f" +{len(normalized) - 3}"
    return {
        "kind": "account_set",
        "id": "configured_accounts",
        "display_name": preview or "configured accounts",
        "members": normalized,
    }


def build_x_collector_batch(
    run_id: str,
    collected_at: str,
    accounts: list[str],
    fetch_results: list["FetchResult"],
    warning: str | None,
    config_path: str,
) -> dict[str, Any]:
    items = [
        normalize_x_tweet_to_collector_item(tweet, collected_at)
        for result in fetch_results
        for tweet in result.tweets
    ]
    return {
        "schema_version": COLLECTOR_BATCH_SCHEMA_VERSION,
        "item_schema_version": COLLECTOR_ITEM_SCHEMA_VERSION,
        "source": X_SOURCE_ID,
        "collector_run_id": run_id,
        "collected_at": collected_at,
        "target": build_collector_target(accounts),
        "collector": {
            "transport": X_COLLECTOR_TRANSPORT,
            "implementation": X_COLLECTOR_IMPLEMENTATION,
            "entrypoint": "monitor.py collect",
        },
        "item_count": len(items),
        "items": items,
        "warnings": [warning] if warning else [],
        "raw_meta": {
            "config_path": config_path,
            "account_results": [asdict(result) for result in fetch_results],
        },
    }


def build_collect_run_metrics(
    run_id: str,
    started_at: str,
    finished_at: str,
    runtime_seconds: float,
    accounts: list[str],
    fetch_results: list[FetchResult],
    all_tweets: list[dict[str, Any]],
    warning: str | None,
) -> dict[str, Any]:
    status_counts = Counter(result.status for result in fetch_results)
    accounts_failed = sum(1 for result in fetch_results if result.status != STATUS_OK)
    visible_tweets = sum(result.visible_tweet_count for result in fetch_results)
    new_tweets = sum(result.new_tweet_count for result in fetch_results)
    return {
        "schema_version": "signal-radar-run-metrics/v1",
        "run_id": run_id,
        "status": "warning" if warning else "ok",
        "started_at": started_at,
        "finished_at": finished_at,
        "updated_at": finished_at,
        "runtime_seconds": round(runtime_seconds, 3),
        "collector": {
            "accounts_configured": len(accounts),
            "accounts_checked": len(fetch_results),
            "accounts_succeeded": status_counts.get(STATUS_OK, 0),
            "accounts_failed": accounts_failed,
            "status_counts": dict(status_counts),
            "tweets_raw": visible_tweets,
            "tweets_new": new_tweets,
            "tweets_after_dedup": len(all_tweets),
            "warning": bool(warning),
        },
        "analysis_input": {
            "built": False,
            "item_count": 0,
            "recommendation_count": 0,
            "keyword_count": 0,
        },
        "analysis": {
            "event_clusters": 0,
            "high_novelty_events": 0,
            "signal_evaluations": 0,
            "high_novelty_signals": 0,
            "alert_candidates": 0,
            "contradictions": 0,
        },
        "memory": {
            "memory_updates": 0,
            "theme_updates": 0,
            "account_updates": 0,
            "entity_updates": 0,
            "event_updates": 0,
            "macro_updates": 0,
            "source_updates": 0,
            "contradiction_updates": 0,
        },
    }



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


