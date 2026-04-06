# X Monitor — Hermes Agent 推文监控与智能分析系统

## 项目概述

X Monitor 是一个运行在 Hermes Agent 上的 X (Twitter) 推文监控系统。它定期抓取指定账号的推文，通过 LLM 按主题归类生成中文简报，并发送到 Telegram。系统具备去重、记忆、账号发现等能力，设计目标是成为一个**长期运行、越用越聪明**的信息助手。

### 核心理念

传统的推文监控工具是"按账号罗列"——你关注了谁，就看谁的推文。X Monitor 的思路不同：它把所有监控账号的推文打散，**按主题重新组织**。你关注的不是"Elon Musk 说了什么"，而是"AI 领域今天发生了什么，哪些人在讨论"。

这更接近一个私人情报分析员的工作方式：跨源收集 → 主题归类 → 趋势追踪 → 简报输出。

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    Hermes Agent                      │
│                                                      │
│  ┌──────────┐   ┌───────────┐   ┌────────────────┐  │
│  │  Cron    │──▶│ monitor.py│──▶│ reports/       │  │
│  │ 定时触发  │   │  主脚本    │   │ prompt_xxx.txt │  │
│  └──────────┘   └─────┬─────┘   │ data_xxx.json  │  │
│                       │         │ report_xxx.txt  │  │
│                       ▼         └───────┬────────┘  │
│                 ┌───────────┐           │           │
│                 │ state.json│           ▼           │
│                 │ 去重+记忆  │     ┌──────────┐     │
│                 └───────────┘     │  Hermes   │     │
│                                   │  LLM 总结  │     │
│                                   └─────┬────┘     │
│                                         │          │
│                                         ▼          │
│                                   ┌──────────┐     │
│                                   │ Telegram  │     │
│                                   │ Gateway   │     │
│                                   └──────────┘     │
└─────────────────────────────────────────────────────┘

外部依赖:
  - Playwright + Chromium（无头浏览器）
  - X.com（通过浏览器 cookies 认证）
```

---

## 技术选型与决策记录

### 为什么选 Playwright 而不是 Python Scraper 库？

我们最初尝试了 **twikit** 和 **tweety-ns** 这两个主流的 Python Twitter scraper 库。两者都依赖逆向 X 的内部 GraphQL API，通过模拟请求头和生成 `X-Client-Transaction-Id` 签名来绕过认证。

然而 X 在 2026 年 3-4 月更新了 `TransactionGenerator` 的动画签名验证机制，导致所有依赖该机制的 Python 库集体失效（报错 `Couldn't get KEY_BYTE indices` 或 `Couldn't get animation key indices`）。这是一个已知的社区级问题，库的维护者通常需要数天到数周来跟进修复，而 X 大约每 2-4 周就会再次变更。

**Playwright 的优势：**

- 运行真实的 Chromium 浏览器，X 看到的是一个正常用户在浏览页面
- 不依赖任何逆向工程的 API 签名，不受 `TransactionGenerator` 变更影响
- 能抓取页面上所有可见内容：文本、图片、视频标记、互动数据
- 抗封性最强——除非 X 改变整个前端 DOM 结构（极少发生）

**Playwright 的代价：**

- 资源占用更高（每次运行启动一个 Chromium 实例，约 200-400MB 内存）
- 速度较慢（每个账号约 10-15 秒，含页面加载和滚动）
- 依赖 DOM 选择器（如 `[data-testid="tweetText"]`），X 改了选择器就要跟着改

这是一个**稳定性优先**的权衡。对于定时监控场景（每 1-2 小时跑一次），速度不是瓶颈，稳定才是。

### 为什么不用 X 官方 API？

X 官方 API（v2）的基础付费方案是每月 $100，只允许读取 10,000 条推文；企业版每月 $42,000。对于个人监控几个账号的场景，这个成本完全不合理。

Hermes 社区提供了一个 `xitter` skill，封装了官方 API 的 `x-cli` 工具。它更稳定、支持写入操作（发推、回复、点赞），但需要付费的开发者账号和 5 个 API 密钥。

**我们的建议：** 读取/监控用 Playwright（免费），写入/互动用 xitter 官方 API（付费）。两者并行，各取所长。

---

## 功能详解

### 1. 推文抓取

脚本通过 Playwright 打开每个监控账号的 X 个人页面，模拟滚动加载，然后从 DOM 中提取：

| 字段 | 提取方式 | 说明 |
|------|---------|------|
| 完整文本 | `[data-testid="tweetText"]` 的 `innerText` | 保留换行，不截断 |
| 推文 ID | 从 `<time>` 父级 `<a>` 的 href 中正则提取 | 用于去重和生成链接 |
| 发布时间 | `<time>` 元素的 `datetime` 属性 | ISO 格式 |
| 图片 URL | `[data-testid="tweetPhoto"] img` 的 `src` | 自动替换为高清版（`name=large`） |
| 视频标记 | 检测 `[data-testid="videoPlayer"]` 是否存在 | 布尔值 |
| 互动数据 | reply/retweet/like 按钮的 `aria-label` | 从中正则提取数字 |
| @提及 | 正文中正则匹配 `@\w+` | 用于发现引擎 |
| 引用推文 | 检测嵌套的 `tweetText` 元素 | 提取引用的原文 |
| 转推标记 | 检测 `socialContext` 元素或 `RT @` 前缀 | 布尔值 |

每个账号之间有可配置的延迟（默认 5 秒），防止触发限流。

### 2. 去重机制

系统维护一个 `state.json` 文件，记录所有已处理过的推文 ID：

```json
{
  "seen_ids": ["1234567890", "1234567891", ...],
  "last_run": "2026-04-06T07:22:00+00:00"
}
```

每次抓取时，已存在于 `seen_ids` 中的推文会被跳过。列表自动截断到最近 2000 条，防止文件无限膨胀。

这意味着：如果你每 2 小时跑一次，每次报告只包含**上次运行后的新推文**。不会重复推送你已经看过的内容。

### 3. 主题归类（LLM 驱动）

这是 X Monitor 与普通推文聚合工具的核心区别。

传统工具的输出是：
```
@elonmusk: 推文1、推文2、推文3
@account2: 推文4、推文5
```

X Monitor 的输出是：
```
🔖 主题: AI 发展
  - Elon Musk 宣布 Grok-3 即将发布 (@elonmusk)
  - Sam Altman 回应关于 AGI 时间线的质疑 (@sama)
  
🔖 主题: 政府与监管
  - 美联邦支出 10 年增长 40%，Musk 质疑效率 (@elonmusk)
  - ...
```

实现方式：脚本生成一个精心设计的 LLM prompt，包含所有推文的完整数据，要求 LLM 按主题而非按账号组织输出。用户可以在 `config.yaml` 中预定义关注的主题方向（如 AI、crypto、地缘政治），LLM 会优先归入这些类别，同时保留创建新类别的自由度。

### 4. Agent 记忆

`state.json` 不只做去重，还承担记忆功能：

**主题历史（theme_history）：** 记录每次运行识别出的主题列表。下次运行时，LLM 的 prompt 中会包含"近期反复出现的主题"，让它能识别趋势变化——"这个话题上周就在讨论了，本周热度继续上升"。

**账号画像（account_notes）：** 每次 LLM 总结后，输出一段 `MEMORY_UPDATE`，其中包含对每个账号的一句话画像更新。例如：

```
@elonmusk: 近期主要讨论政府效率（DOGE）、AI（Grok）、航天（Starship），偶尔发 meme
```

这些画像会持久化，下次运行时 LLM 能看到历史上下文，从而产出更有深度的分析（"与上周相比，该账号从 AI 话题转向了政策讨论"）。

### 5. 账号发现

发现引擎统计所有推文中 @提及的用户名频次。如果某个非监控列表中的账号被多次提及（超过 `min_interactions` 阈值），系统会推荐你关注。

这解决了信息茧房问题——你不需要自己去找新的信息源，系统会根据你已关注的人的互动网络，自动发现相关的新账号。

### 6. Cookies 健康检查

如果一次运行中所有账号都没抓到任何推文，系统会生成一个 warning 文件。Hermes 可以检测到这个文件并通过 Telegram 发送告警，提醒你更新 cookies。

---

## 文件结构

```
~/.hermes/skills/x-monitor/
├── monitor.py              # 主脚本
├── config.yaml             # 配置文件
├── cookies.json            # X 登录 cookies（敏感，不要提交到 git）
├── state.json              # 持久化状态（去重 + 记忆，自动维护）
├── SKILL.md                # Hermes skill 描述
├── reports/                # 输出目录
│   ├── data_YYYYMMDD_HHMMSS.json     # 原始数据（JSON）
│   ├── prompt_YYYYMMDD_HHMMSS.txt    # LLM prompt
│   ├── report_YYYYMMDD_HHMMSS.txt    # 人类可读报告
│   └── warning_YYYYMMDD_HHMMSS.txt   # 告警（仅在异常时生成）
└── debug_*.png             # 调试截图（仅在加载失败时生成）
```

---

## 运行方式

### 手动运行

```bash
cd ~/.hermes/skills/x-monitor
python3 monitor.py --config config.yaml
```

### 通过 Hermes 定时运行

在 Hermes 对话中：

```
每 2 小时运行 python3 ~/.hermes/skills/x-monitor/monitor.py --config ~/.hermes/skills/x-monitor/config.yaml，
读取 reports 目录下最新的 prompt 文件，用中文总结后发到 Telegram。
如果发现 warning 文件，也发到 Telegram 提醒我更新 cookies。
```

Hermes 会创建 cron job 自动执行。

---

## 配置说明

```yaml
# 监控账号列表
accounts:
  - "elonmusk"
  - "sama"

# 每个账号拉取推文数
tweets_per_account: 15

# 页面滚动次数（越多推文越多，但越慢）
scroll_count: 5

# 账号间延迟（秒，防限流）
delay_between_accounts: 5

# Cookies 文件路径
auth:
  cookies_file: "cookies.json"

# 去重状态文件
state_file: "state.json"

# 预定义主题方向（可选，引导 LLM 的归类方向）
themes:
  - "AI/人工智能"
  - "加密货币/区块链"
  - "地缘政治"

# 发现模式
discovery:
  enabled: true
  min_interactions: 3
```

---

## 已知限制与维护事项

### Cookies 有效期

X 的登录 cookies 通常在 1-2 周后过期。过期后 Playwright 打开页面会看到登录墙而非推文内容。系统内置了健康检查——如果一次运行全部账号都抓取失败，会生成告警。

**维护方式：** 定期（建议每周一次）从浏览器重新导出 cookies 并覆盖 `cookies.json`。

### DOM 选择器稳定性

当前的推文提取依赖 X 的 `data-testid` 属性（如 `tweetText`、`tweetPhoto`）。这些属性在过去两年中相对稳定，但 X 有可能在未来的前端重构中修改它们。

**应对方式：** 如果某天突然所有账号都抓取到 0 条推文但 cookies 没过期，大概率是选择器变了。检查 `debug_*.png` 截图确认页面状态，然后更新 `monitor.py` 中的选择器。

### 资源占用

每次运行启动一个 Chromium 无头浏览器实例。在典型配置（5 个账号、scroll_count=5）下：

- 内存峰值：约 300-500MB
- 运行时间：约 1-2 分钟
- 磁盘：报告文件每次约 10-50KB

对于 1GB+ 内存的 VPS 完全够用。如果在低配机器上运行，可以减少 `scroll_count` 和 `tweets_per_account`。

### 反爬风险

Playwright 模拟真实浏览器行为，风险远低于 API scraper。但仍需注意：

- 不要把监控频率设得太高（建议 ≥1 小时间隔）
- 不要同时监控太多账号（建议 ≤ 20 个）
- 账号间保持延迟（默认 5 秒）
- 所有基于 scraping 的方案都处于 X 服务条款的灰色地带

---

## 后续演进方向

### 短期可做

- **自动解析 MEMORY_UPDATE：** 目前 LLM 输出的记忆更新段需要手动或由 Hermes 解析后写入 state.json。可以增加一个后处理步骤自动完成。
- **Telegram 消息格式优化：** 根据 Telegram 的 Markdown 格式限制调整输出，让图片以内联预览显示。
- **多次运行的趋势报告：** 每周生成一份周报，基于 theme_history 分析主题热度变化。

### 中期可做

- **关键词搜索扩展：** 不只监控特定账号，还能搜索特定关键词的公开讨论。需要在 Playwright 中打开 X 搜索页面。
- **互动图谱可视化：** 基于 mentions 数据生成账号关系网络图，直观展示谁在跟谁互动。
- **多语言支持：** 当前 prompt 默认输出中文，可配置为其他语言。

### 长期可做

- **自动调整监控列表：** 基于发现引擎的推荐和 LLM 的判断，自动将高价值账号加入监控列表。
- **与其他数据源联动：** 结合 Reddit、Hacker News、RSS 等信息源，做跨平台的主题追踪。
- **本地 embedding 搜索：** 将历史推文向量化存储，支持语义搜索——"最近谁讨论过半导体出口管制？"