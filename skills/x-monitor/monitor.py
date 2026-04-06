#!/usr/bin/env python3
"""
X (Twitter) Monitor — Playwright 版
抓取指定账号推文 → 发现相关账号 → 生成报告 → 供 LLM 总结
"""

import asyncio
import json
import re
import sys
import argparse
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("请先安装: pip install playwright --break-system-packages && playwright install chromium --with-deps")
    sys.exit(1)


# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

DEFAULT_CONFIG = {
    "accounts": [],
    "tweets_per_account": 10,
    "auth": {"cookies_file": "cookies.json"},
    "discovery": {"enabled": True, "min_interactions": 3},
    "scroll_count": 3,
    "delay_between_accounts": 5,
}


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"配置文件不存在: {path}")
        sys.exit(1)
    text = p.read_text(encoding="utf-8")
    try:
        import yaml
        loaded = yaml.safe_load(text)
    except ImportError:
        loaded = json.loads(text)
    return {**DEFAULT_CONFIG, **loaded}


# ─────────────────────────────────────────────
# 抓取层 (Playwright)
# ─────────────────────────────────────────────

class PlaywrightFetcher:
    def __init__(self, cookies_file: str):
        self.cookies_file = cookies_file
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
        )
        with open(self.cookies_file) as f:
            cookies = json.load(f)
        pw_cookies = []
        for k, v in cookies.items():
            pw_cookies.append({
                "name": k,
                "value": str(v),
                "domain": ".x.com",
                "path": "/",
            })
        await self.context.add_cookies(pw_cookies)
        print("✅ 浏览器已启动，cookies 已加载")

    async def close(self):
        if self.browser:
            await self.browser.close()

    async def fetch_user_tweets(
        self, username: str, max_tweets: int = 10, scroll_count: int = 3
    ) -> list[dict]:
        page = await self.context.new_page()
        tweets = []

        try:
            url = f"https://x.com/{username}"
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector(
                    '[data-testid="tweetText"]', timeout=15000
                )
            except Exception:
                print(f"  ❌ @{username}: 页面加载超时或无推文")
                await page.screenshot(path=f"debug_{username}.png")
                return []

            await asyncio.sleep(2)

            for _ in range(scroll_count):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1.5)

            tweet_elements = await page.query_selector_all(
                "article[data-testid='tweet']"
            )

            for el in tweet_elements:
                if len(tweets) >= max_tweets:
                    break
                tweet_data = await self._parse_tweet(el, username)
                if tweet_data and tweet_data["text"]:
                    tweets.append(tweet_data)

            print(f"  📥 @{username}: 获取 {len(tweets)} 条推文")

        except Exception as e:
            print(f"  ❌ @{username}: 抓取失败 — {e}")
        finally:
            await page.close()

        return tweets

    async def _parse_tweet(self, el, default_author: str) -> dict | None:
        try:
            text_el = await el.query_selector('[data-testid="tweetText"]')
            text = await text_el.inner_text() if text_el else ""

            time_el = await el.query_selector("time")
            created_at = None
            if time_el:
                created_at = await time_el.get_attribute("datetime")

            stats = await self._parse_stats(el)

            is_retweet = text.startswith("RT @") or bool(
                await el.query_selector('[data-testid="socialContext"]')
            )

            return {
                "text": text,
                "author": default_author,
                "created_at": created_at,
                "is_retweet": is_retweet,
                "mentions": extract_mentions(text),
                "retweet_count": stats.get("retweet", 0),
                "like_count": stats.get("like", 0),
                "reply_count": stats.get("reply", 0),
            }
        except Exception:
            return None

    async def _parse_stats(self, el) -> dict:
        stats = {}
        for key in ["reply", "retweet", "like"]:
            try:
                btn = await el.query_selector(f'[data-testid="{key}"]')
                if btn:
                    aria = await btn.get_attribute("aria-label") or ""
                    nums = re.findall(r"[\d,]+", aria)
                    if nums:
                        stats[key] = int(nums[0].replace(",", ""))
            except Exception:
                pass
        return stats


def extract_mentions(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"@(\w+)", text)


# ─────────────────────────────────────────────
# 发现引擎
# ─────────────────────────────────────────────

class DiscoveryEngine:
    def __init__(self, monitored: list[str], min_interactions: int = 3):
        self.monitored = set(a.lower() for a in monitored)
        self.min_interactions = min_interactions
        self.counter = Counter()

    def process(self, all_tweets: list[dict]):
        for t in all_tweets:
            for m in t.get("mentions", []):
                if m.lower() not in self.monitored:
                    self.counter[m] += 1

    def get_recommendations(self) -> list[dict]:
        return [
            {"username": u, "count": c}
            for u, c in self.counter.most_common(10)
            if c >= self.min_interactions
        ]


# ─────────────────────────────────────────────
# 报告生成
# ─────────────────────────────────────────────

def extract_keywords(tweets: list[dict], top_n: int = 8) -> list[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on",
        "at", "for", "of", "and", "or", "but", "not", "with", "this",
        "that", "it", "be", "as", "by", "from", "has", "have", "had",
        "rt", "https", "http", "co", "amp", "just", "will", "can",
    }
    counter = Counter()
    for t in tweets:
        text = re.sub(r"https?://\S+", "", t.get("text", ""))
        text = re.sub(r"@\w+", "", text)
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
        for w in words:
            if w not in stopwords:
                counter[w] += 1
    return [w for w, _ in counter.most_common(top_n)]


def format_report(
    account_tweets: dict[str, list[dict]],
    recommendations: list[dict],
    keywords: list[str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 X 监控报告 — {now}", ""]

    for username, tweets in account_tweets.items():
        if not tweets:
            lines.append(f"👤 @{username} — 无新推文")
            lines.append("")
            continue

        lines.append(f"👤 @{username} ({len(tweets)} 条推文)")

        sorted_tweets = sorted(
            tweets,
            key=lambda t: t.get("like_count", 0) + t.get("retweet_count", 0),
            reverse=True,
        )

        for t in sorted_tweets[:5]:
            preview = (t["text"] or "")[:150].replace("\n", " ")
            engagement = t.get("like_count", 0) + t.get("retweet_count", 0)
            hot = " 🔥" if engagement > 1000 else ""
            time_str = ""
            if t.get("created_at"):
                time_str = f" [{t['created_at'][:16]}]"
            lines.append(
                f"  • {preview}"
                f"{'...' if len(t.get('text',''))>150 else ''}"
                f"{hot}{time_str}"
            )

        lines.append("")

    if recommendations:
        lines.append("🔍 发现推荐")
        for r in recommendations[:5]:
            lines.append(f"  • @{r['username']} — 被提及 {r['count']} 次")
        lines.append("")

    if keywords:
        lines.append(f"📌 热点关键词：{', '.join(keywords)}")

    return "\n".join(lines)


LLM_SUMMARY_PROMPT = """你是一个 X (Twitter) 信息分析助手。请用中文总结以下推文报告。

要求：
1. 每个账号的推文提炼 2-3 个核心要点
2. 标注热度最高的推文及其话题
3. 如果有值得关注的趋势或争议，单独说明
4. 对"发现推荐"的账号，简要说明为什么值得关注
5. 语言简洁，像新闻简报一样

原始报告：
{report}
"""


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

async def main(config_path: str):
    config = load_config(config_path)
    accounts = config["accounts"]

    if not accounts:
        print("❌ 请在 config.yaml 中配置要监控的账号")
        sys.exit(1)

    print(f"🚀 开始监控 {len(accounts)} 个账号: {', '.join('@'+a for a in accounts)}")

    async with async_playwright() as pw:
        fetcher = PlaywrightFetcher(config["auth"]["cookies_file"])
        await fetcher.start(pw)

        account_tweets = {}
        all_tweets = []

        for username in accounts:
            tweets = await fetcher.fetch_user_tweets(
                username,
                max_tweets=config["tweets_per_account"],
                scroll_count=config.get("scroll_count", 3),
            )
            account_tweets[username] = tweets
            all_tweets.extend(tweets)
            delay = config.get("delay_between_accounts", 5)
            if username != accounts[-1]:
                print(f"  ⏳ 等待 {delay} 秒...")
                await asyncio.sleep(delay)

        await fetcher.close()

    # 发现
    discovery = DiscoveryEngine(
        accounts, config["discovery"]["min_interactions"]
    )
    if config["discovery"]["enabled"]:
        discovery.process(all_tweets)
    recommendations = discovery.get_recommendations()

    # 关键词
    keywords = extract_keywords(all_tweets)

    # 报告
    report = format_report(account_tweets, recommendations, keywords)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    # 保存
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_path = output_dir / f"report_{ts}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n📁 报告已保存: {report_path}")

    prompt_path = output_dir / f"prompt_{ts}.txt"
    prompt_path.write_text(
        LLM_SUMMARY_PROMPT.format(report=report), encoding="utf-8"
    )
    print(f"📝 LLM Prompt 已保存: {prompt_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="X Monitor (Playwright)")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()
    asyncio.run(main(args.config))