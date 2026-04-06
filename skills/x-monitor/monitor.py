#!/usr/bin/env python3
"""
X (Twitter) Monitor v2 — 完整版
特性：
  - 完整推文文本 + 图片 URL 提取
  - 去重：基于推文 ID，不重复报告
  - 主题归类 prompt（供 LLM 按主题组织而非按账号）
  - 持久化状态：记住已处理的推文和历史主题
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
    "tweets_per_account": 15,
    "auth": {"cookies_file": "cookies.json"},
    "discovery": {"enabled": True, "min_interactions": 3},
    "scroll_count": 5,
    "delay_between_accounts": 5,
    "state_file": "state.json",
    "themes": [],  # 用户可预定义主题，如 ["AI", "crypto", "geopolitics"]
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
# 状态管理（去重 + 记忆）
# ─────────────────────────────────────────────

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

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "seen_ids": [],
            "theme_history": [],      # 最近 N 次的主题列表
            "account_notes": {},      # {"elonmusk": "经常讨论 AI、政府效率..."}
            "last_run": None,
        }

    def save(self):
        self.data["last_run"] = datetime.now(timezone.utc).isoformat()
        # 只保留最近 2000 个 seen_ids 防止文件膨胀
        self.data["seen_ids"] = self.data["seen_ids"][-2000:]
        # 只保留最近 50 次主题历史
        self.data["theme_history"] = self.data["theme_history"][-50:]
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_seen(self, tweet_id: str) -> bool:
        return tweet_id in self.data["seen_ids"]

    def mark_seen(self, tweet_id: str):
        if tweet_id not in self.data["seen_ids"]:
            self.data["seen_ids"].append(tweet_id)

    def add_themes(self, themes: list[str]):
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "themes": themes,
        }
        self.data["theme_history"].append(entry)

    def update_account_notes(self, username: str, note: str):
        self.data["account_notes"][username] = note

    def get_account_notes(self) -> dict:
        return self.data.get("account_notes", {})

    def get_recent_themes(self, n: int = 10) -> list[str]:
        """返回最近 N 次出现过的所有主题（去重）"""
        all_themes = []
        for entry in self.data["theme_history"][-n:]:
            all_themes.extend(entry.get("themes", []))
        return list(dict.fromkeys(all_themes))  # 去重保序


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
        self,
        username: str,
        state: StateManager,
        max_tweets: int = 15,
        scroll_count: int = 5,
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

            # 多次滚动加载
            for i in range(scroll_count):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1.5)

            # 提取所有推文
            tweet_elements = await page.query_selector_all(
                "article[data-testid='tweet']"
            )

            for el in tweet_elements:
                if len(tweets) >= max_tweets:
                    break
                tweet_data = await self._parse_tweet(el, username, page)
                if not tweet_data or not tweet_data["text"]:
                    continue

                # 去重
                tid = tweet_data.get("id")
                if tid and state.is_seen(tid):
                    continue

                tweets.append(tweet_data)
                if tid:
                    state.mark_seen(tid)

            print(f"  📥 @{username}: 获取 {len(tweets)} 条新推文")

        except Exception as e:
            print(f"  ❌ @{username}: 抓取失败 — {e}")
        finally:
            await page.close()

        return tweets

    async def _parse_tweet(self, el, default_author: str, page) -> dict | None:
        try:
            # ── 完整推文文本 ──
            text_el = await el.query_selector('[data-testid="tweetText"]')
            text = ""
            if text_el:
                # inner_text 会保留换行，拿到完整内容
                text = await text_el.inner_text()

            # ── 推文 ID（从链接提取） ──
            tweet_id = None
            time_el = await el.query_selector("time")
            created_at = None
            if time_el:
                created_at = await time_el.get_attribute("datetime")
                # time 通常在一个 <a> 里，href 包含推文链接
                parent_a = await time_el.evaluate_handle(
                    "el => el.closest('a')"
                )
                if parent_a:
                    href = await parent_a.get_property("href")
                    href_str = await href.json_value()
                    if href_str:
                        # href 格式: https://x.com/user/status/123456
                        match = re.search(r"/status/(\d+)", str(href_str))
                        if match:
                            tweet_id = match.group(1)

            # ── 图片 URL ──
            images = []
            img_elements = await el.query_selector_all(
                '[data-testid="tweetPhoto"] img'
            )
            for img in img_elements:
                src = await img.get_attribute("src")
                if src and "pbs.twimg.com" in src:
                    # 获取高清版：替换 name 参数
                    clean_src = re.sub(
                        r"name=\w+", "name=large", src
                    )
                    images.append(clean_src)

            # ── 视频标记 ──
            has_video = bool(
                await el.query_selector('[data-testid="videoPlayer"]')
            )

            # ── 互动数据 ──
            stats = await self._parse_stats(el)

            # ── 转推检测 ──
            is_retweet = text.startswith("RT @") or bool(
                await el.query_selector('[data-testid="socialContext"]')
            )

            # ── 引用推文 ──
            quoted_text = ""
            quoted_el = await el.query_selector(
                '[aria-labelledby] [data-testid="tweetText"]'
            )
            # 简单检测：如果有嵌套的 tweetText 且不是自身
            quote_containers = await el.query_selector_all(
                '[data-testid="tweetText"]'
            )
            if len(quote_containers) > 1:
                quoted_text = await quote_containers[-1].inner_text()

            return {
                "id": tweet_id,
                "text": text,
                "author": default_author,
                "created_at": created_at,
                "is_retweet": is_retweet,
                "mentions": extract_mentions(text),
                "images": images,
                "has_video": has_video,
                "quoted_text": quoted_text,
                "retweet_count": stats.get("retweet", 0),
                "like_count": stats.get("like", 0),
                "reply_count": stats.get("reply", 0),
                "tweet_url": f"https://x.com/{default_author}/status/{tweet_id}"
                if tweet_id
                else None,
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

def format_raw_report(account_tweets: dict[str, list[dict]]) -> str:
    """
    生成包含完整信息的原始报告（供 LLM 做主题归类）
    """
    lines = []

    all_tweets = []
    for username, tweets in account_tweets.items():
        for t in tweets:
            all_tweets.append(t)

    if not all_tweets:
        return "本次监控无新推文。"

    # 按时间倒序
    all_tweets.sort(
        key=lambda t: t.get("created_at") or "",
        reverse=True,
    )

    for t in all_tweets:
        lines.append(f"--- TWEET ---")
        lines.append(f"作者: @{t['author']}")
        if t.get("created_at"):
            lines.append(f"时间: {t['created_at']}")
        if t.get("tweet_url"):
            lines.append(f"链接: {t['tweet_url']}")
        lines.append(f"正文:")
        lines.append(t["text"])
        if t.get("quoted_text"):
            lines.append(f"引用推文: {t['quoted_text']}")
        if t.get("images"):
            lines.append(f"图片: {', '.join(t['images'])}")
        if t.get("has_video"):
            lines.append(f"[包含视频]")
        engagement = []
        if t.get("like_count"):
            engagement.append(f"❤️ {t['like_count']}")
        if t.get("retweet_count"):
            engagement.append(f"🔁 {t['retweet_count']}")
        if t.get("reply_count"):
            engagement.append(f"💬 {t['reply_count']}")
        if engagement:
            lines.append(f"互动: {' | '.join(engagement)}")
        lines.append("")

    return "\n".join(lines)


def format_discovery_section(
    recommendations: list[dict], keywords: list[str]
) -> str:
    lines = []
    if recommendations:
        lines.append("── 发现推荐 ──")
        for r in recommendations[:5]:
            lines.append(f"  @{r['username']} — 被提及 {r['count']} 次")
        lines.append("")
    if keywords:
        lines.append(f"── 热点关键词 ──")
        lines.append(f"  {', '.join(keywords)}")
    return "\n".join(lines)


def extract_keywords(tweets: list[dict], top_n: int = 10) -> list[str]:
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
    for t in tweets:
        text = re.sub(r"https?://\S+", "", t.get("text", ""))
        text = re.sub(r"@\w+", "", text)
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
        for w in words:
            if w not in stopwords and len(w) > 2:
                counter[w] += 1
    return [w for w, _ in counter.most_common(top_n)]


# ─────────────────────────────────────────────
# LLM Prompt（主题归类 + 记忆更新）
# ─────────────────────────────────────────────

def build_llm_prompt(
    raw_report: str,
    discovery_section: str,
    state: StateManager,
    predefined_themes: list[str],
) -> str:
    # 历史上下文
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
        theme_hint = f"\n用户关注的主题方向（优先归入这些类别，也可创建新类别）:\n  {', '.join(predefined_themes)}\n"

    return f"""你是一个专业的 X (Twitter) 信息分析助手。

## 任务
将以下推文按**主题**归类（不是按账号），用中文输出结构化的简报。

## 输出格式要求
严格按以下格式输出:

### 📋 简报标题（一句话概括本次最重要的发现）

**🔖 主题1: [主题名]**
- [要点1] (@作者)
  链接: [推文链接]
  [如有图片，保留图片 URL]
- [要点2] (@作者)
  ...

**🔖 主题2: [主题名]**
- ...

**📊 趋势观察**
- 与上次报告相比的变化或新趋势

**🔍 发现推荐**
- 推荐关注的新账号及理由

### MEMORY_UPDATE
（以下部分用于更新 agent 记忆，不发送给用户）
THEMES: [用逗号分隔的本次主题列表]
ACCOUNT_NOTES:
@账号1: [一句话更新该账号的内容画像]
@账号2: [一句话更新该账号的内容画像]

## 规则
1. 同一主题下合并不同账号的相关推文
2. 保留推文完整含义，不要过度简化
3. 保留所有图片 URL（用 [图片: URL] 格式）
4. 保留推文链接
5. 热度高的推文（互动量大）要标注 🔥
6. 如果推文涉及争议或重大事件，单独标注
7. MEMORY_UPDATE 部分必须输出，用于下次运行时参考
{theme_hint}
## 历史上下文
{history_context if history_context else "（首次运行，无历史数据）"}

## 发现数据
{discovery_section}

## 本次推文数据
{raw_report}
"""


# ─────────────────────────────────────────────
# Cookies 健康检查
# ─────────────────────────────────────────────

def check_cookies_health(account_tweets: dict[str, list[dict]]) -> str | None:
    """如果所有账号都没抓到推文，返回警告信息"""
    total = sum(len(tweets) for tweets in account_tweets.values())
    if total == 0:
        return (
            "⚠️ 所有账号均未抓取到推文！\n"
            "可能原因:\n"
            "  1. Cookies 已过期 — 请重新从浏览器导出\n"
            "  2. 账号被限制 — 检查是否需要验证\n"
            "  3. 网络问题 — 检查服务器能否访问 x.com\n"
            "请更新 cookies.json 后重试。"
        )
    return None


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

async def main(config_path: str):
    config = load_config(config_path)
    accounts = config["accounts"]

    if not accounts:
        print("❌ 请在 config.yaml 中配置要监控的账号")
        sys.exit(1)

    # 状态管理
    state = StateManager(config.get("state_file", "state.json"))
    last_run = state.data.get("last_run")
    if last_run:
        print(f"📅 上次运行: {last_run}")

    print(f"🚀 开始监控 {len(accounts)} 个账号: {', '.join('@'+a for a in accounts)}")

    # 抓取
    async with async_playwright() as pw:
        fetcher = PlaywrightFetcher(config["auth"]["cookies_file"])
        await fetcher.start(pw)

        account_tweets = {}
        all_tweets = []

        for username in accounts:
            tweets = await fetcher.fetch_user_tweets(
                username,
                state=state,
                max_tweets=config["tweets_per_account"],
                scroll_count=config.get("scroll_count", 5),
            )
            account_tweets[username] = tweets
            all_tweets.extend(tweets)
            delay = config.get("delay_between_accounts", 5)
            if username != accounts[-1]:
                print(f"  ⏳ 等待 {delay} 秒...")
                await asyncio.sleep(delay)

        await fetcher.close()

    # Cookies 健康检查
    warning = check_cookies_health(account_tweets)
    if warning:
        print(f"\n{warning}")

    # 发现
    discovery = DiscoveryEngine(
        accounts, config["discovery"]["min_interactions"]
    )
    if config["discovery"]["enabled"]:
        discovery.process(all_tweets)
    recommendations = discovery.get_recommendations()
    keywords = extract_keywords(all_tweets)

    # 生成报告
    raw_report = format_raw_report(account_tweets)
    discovery_section = format_discovery_section(recommendations, keywords)

    # 生成 LLM prompt
    prompt = build_llm_prompt(
        raw_report,
        discovery_section,
        state,
        config.get("themes", []),
    )

    # 保存状态
    state.save()

    # 输出
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'=' * 60}")
    print(f"📊 X 监控报告 — {now_str}")
    print(f"   新推文: {len(all_tweets)} 条")
    print(f"   账号: {', '.join(f'@{u}({len(t)})' for u, t in account_tweets.items())}")
    if recommendations:
        print(f"   发现: {', '.join('@'+r['username'] for r in recommendations[:3])}")
    if keywords:
        print(f"   关键词: {', '.join(keywords[:5])}")
    print(f"{'=' * 60}")

    # 保存文件
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 原始数据（JSON，方便程序处理）
    data_path = output_dir / f"data_{ts}.json"
    data_path.write_text(
        json.dumps(
            {
                "timestamp": now_str,
                "account_tweets": account_tweets,
                "recommendations": recommendations,
                "keywords": keywords,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # LLM Prompt
    prompt_path = output_dir / f"prompt_{ts}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    # 原始报告（人类可读）
    report_path = output_dir / f"report_{ts}.txt"
    full_report = f"📊 X 监控报告 — {now_str}\n\n{raw_report}\n{discovery_section}"
    report_path.write_text(full_report, encoding="utf-8")

    if warning:
        warning_path = output_dir / f"warning_{ts}.txt"
        warning_path.write_text(warning, encoding="utf-8")

    print(f"\n📁 数据: {data_path}")
    print(f"📝 Prompt: {prompt_path}")
    print(f"📄 报告: {report_path}")

    return prompt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="X Monitor v2")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()
    asyncio.run(main(args.config))