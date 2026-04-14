# X Monitor — Hermes Agent 推文监控与智能分析系统

## 项目概述

X Monitor 是一个运行在 Hermes Agent 上的 X (Twitter) 推文监控系统。它定期抓取指定账号的推文，通过 LLM 按主题归类生成中文简报，并发送到 Telegram。系统具备去重、记忆、账号发现等能力，设计目标是成为一个**长期运行、越用越聪明**的信息助手。

## 文档分工

- `SKILL.md`：运行入口和标准操作流程
- `references/architecture.md`：collector / local store / analyzer / digest 四层边界与契约
- `references/collector-schema.md`：多来源 collector 的统一输出 schema
- `claude.md`：当前实现细节、文件结构、调试方式、限制和演进方向

如果你要判断“某段逻辑该放哪一层”，先读 `references/architecture.md`。如果你要改选择器、状态结构或落盘行为，再看这份 `claude.md`。

### 核心理念

传统的推文监控工具是"按账号罗列"——你关注了谁，就看谁的推文。X Monitor 的思路不同：它把所有监控账号的推文打散，**按主题重新组织**。你关注的不是"Elon Musk 说了什么"，而是"AI 领域今天发生了什么，哪些人在讨论"。

这更接近一个私人情报分析员的工作方式：跨源收集 → 主题归类 → 趋势追踪 → 简报输出。

---

## 四层架构

```text
collector -> local store -> analyzer -> digest / alerts
```

当前代码映射关系：

- `collector`
  - `monitor.py collect`
  - 负责 Playwright、cookies、滚动、DOM 提取、warning 判断、原始产物生成
- `local store`
  - `reports/`
  - `latest_run.json`
  - `memory/state.json`
  - `memory/accounts/*.json`
  - `memory/themes/*.json`
  - `memory/index.json`
- `analyzer`
  - Hermes / LLM 读取 `prompt_*.txt`
  - 结合 `memory/` 生成中文摘要和严格 JSON `MEMORY_UPDATE`
- `digest / alerts`
  - Telegram 或其他下游通知逻辑
  - 根据 `warning`、`new_tweet_count` 和 summary 决定发送什么

外部依赖：

- Playwright + Chromium（无头浏览器）
- X.com（通过浏览器 cookies 认证）

这四层故意分开，原因不是抽象，而是失败模式不同：

- collector 失败，通常是 cookies、选择器、页面加载、风控
- local store 失败，通常是路径、JSON、Git 同步、状态漂移
- analyzer 失败，通常是主题判断、记忆质量、输出格式
- digest / alerts 失败，通常是错误地发送、漏发、误发

因此当前实现不建议用“一个大 agent 从打开 X 一路干到发 Telegram”为主路径。更稳的方式是：collector 只负责拿材料，analyzer 只负责判断价值，digest / alerts 只负责对外输出。

## 多来源准备态

当前运行时仍然是 X-first：

- `monitor.py collect` 直接负责 X 的抓取
- 还没有改成 runtime 按 `registry.yaml` 动态加载所有 source
- `collect` 已经开始额外输出标准化的 `collector_batch_<run_id>.json`

但为了以后接 Reddit、雪球等来源，仓库现在已经补了两层契约：

- `collectors/registry.yaml`
  - 注册来源、transport、source definition 路径
- `collectors/<source>/source.yaml`
  - 描述这个来源是 browser / http / api / rss 哪种抓取方式
  - 描述认证方式、healthcheck、能力边界、标准化约定

也就是说，这一步已经把“多来源接入方式”写清楚了，但还没有宣称运行时已经全面切到多来源框架。

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

### 1. 脚本接口与产物契约

当前 `monitor.py` 是一个三段式 CLI，而不是单次跑完所有逻辑的脚本：

- `collect`：抓取账号页面，生成 `data/collector_batch/prompt/report/summary/memory_update/warning` 等产物路径，并刷新 `latest_run.json`
- `latest`：稳定读取 `latest_run.json`，避免 Hermes 通过 glob 猜文件名
- `apply-memory`：解析 summary 尾部的 `MEMORY_UPDATE`，做主题归一化、幂等检查、记忆回写

这三个命令共同构成 Hermes 的标准编排链路：

1. `collect`
2. `latest --field new_tweet_count`
3. `latest --field prompt`
4. 生成 summary
5. `apply-memory`

其中 `latest_run.json` 是关键的“控制面索引”。它会记录当前 run 的：

- `data`
- `collector_batch`
- `prompt`
- `report`
- `summary`
- `memory_update`
- `memory_index`
- `state`
- `warning`
- `memory_dir`

所以 Hermes 不需要猜目录结构，只需要读取 `latest` 输出。

当前 `collector_batch_<run_id>.json` 已经开始使用统一 schema：

- 顶层是 `collector-batch/v1`
- 每个 item 是 `collector-item/v1`
- 现在仍然只由 X collector 写入
- 但后续 Reddit、雪球只要也产出同样的 item 结构，analyzer 就能逐步复用

### 2. 推文抓取

脚本通过 Playwright 打开每个监控账号的 X 页面，模拟滚动后从 DOM 里提取结构化推文。当前实现已经不是单一路径抓取，而是“主路径 + fallback”。

| 字段 | 当前实现 | 说明 |
|------|---------|------|
| 正文文本 | 优先 `[data-testid="tweetText"]`，其次 `div[lang]` | 避免因为 `tweetText` 缺失漏掉正文 |
| 纯媒体推文文本 | 若无正文但有图片/视频，生成 `[媒体推文：…]` 占位 | 防止图片/视频推文被完全丢弃 |
| 推文 ID / 作者 / 链接 | 优先 `<time>` 上层 `<a>`，其次扫描任意 `a[href*="/status/"]` | 对 DOM 细节变化更稳 |
| 发布时间 | `<time>` 的 `datetime` | ISO 格式 |
| 图片 URL | `[data-testid="tweetPhoto"] img` 的 `src` | 自动替换为 `name=large` |
| 视频标记 | `[data-testid="videoPlayer"]` | 布尔值 |
| 互动数据 | 优先按钮 `aria-label`，其次按钮文本 | 兼容更多页面状态 |
| @提及 | 正文正则匹配 `@\w+` | 用于发现引擎 |
| 引用推文文本 | 多个正文节点时取后者作为 `quoted_text` | 保留引用上下文 |
| 转推标记 | `socialContext` 或 `RT @` 前缀 | 布尔值 |

每个账号之间有可配置的延迟，默认 5 秒，目的是降低限流和登录态波动风险。

### 3. 去重状态与迁移

系统现在把运行状态放在 `memory/state.json`，而不是根目录 `state.json`。文件结构如下：

```json
{
  "version": 1,
  "seen_ids": ["1234567890", "1234567891"],
  "last_run": "2026-04-06T07:22:00+00:00",
  "updated_at": "2026-04-06T07:22:03+00:00"
}
```

语义是：

- `seen_ids`：已经处理过的 tweet id，用于跨轮去重
- `last_run`：兼容字段，保留旧语义
- `updated_at`：状态文件最近写入时间

当前实现还保留了旧状态迁移能力：

- 如果新路径 `memory/state.json` 不存在，会尝试读取旧的根目录 `state.json`
- 如果旧 state 里还残留 `account_notes` 或 `theme_history`，会迁移进新的记忆文件结构
- 迁移后会把旧的长期记忆字段从 state 中清掉

需要注意的是：当前代码在 `collect` 和 `apply-memory` 阶段都会保存 state，但不会主动推进 `last_run`。因此在实际运行里，`updated_at` 才是更可靠的“最近一次状态写入时间”，而 `last_run` 主要用于兼容旧数据结构。

这样做的目的有两个：

- 运行状态和长期记忆解耦
- `memory/` 可直接提交到 GitHub，换 VPS 后不会把旧推文重新当成“新推文”

### 4. 主题归类与 MEMORY_UPDATE 协议

X Monitor 的核心不是“按账号罗列推文”，而是“按主题重组多个账号的动态”。因此 `collect` 生成的 prompt 会要求模型输出 Telegram 正文，以及一个只供系统消费的 `MEMORY_UPDATE`。

现在的正式协议是严格 JSON。例如：

```json
{
  "primary_themes": ["AI/人工智能", "Space/航天"],
  "secondary_themes": {
    "AI/人工智能": ["Grok", "AI监管"],
    "Space/航天": ["Starship"]
  },
  "account_notes": {
    "elonmusk": "近期主要讨论政府效率、AI 和航天。"
  }
}
```

其中：

- `primary_themes`：稳定的一级主题
- `secondary_themes`：每个一级主题下的二级主题
- `account_notes`：账号画像，key 使用不带 `@` 的用户名

解析器仍保留向后兼容：

- 优先读取严格 JSON
- 如果 JSON 不合法或不存在，再回退解析旧的半结构化文本格式

这意味着历史 summary 仍可回放，但新流程的目标协议已经完全转向 JSON。

### 5. 记忆结构、归一化与幂等

记忆已经从单文件拆成了多文件结构：

- `memory/state.json`：去重和运行状态
- `memory/accounts/<username>.json`：单账号记忆
- `memory/themes/<primary-theme>.json`：单一级主题记忆
- `memory/index.json`：汇总索引

当前记忆写入前会做两层归一化：

- 一级主题别名归一化  
  例如 `AI`、`人工智能`、`LLM` 可统一落到 `AI/人工智能`
- 二级主题按一级主题分别归一化  
  例如在 `AI/人工智能` 下面，`AI policy`、`AI政策` 可归一到 `AI监管`

幂等机制是当前实现的关键变化。`apply-memory` 会基于 summary 内容和 run 身份生成稳定 `update_id`，并把它写入账号文件和主题文件的：

- `applied_update_ids`
- `last_update_id`

因此同一份 summary 重跑时：

- 不会重复增加 `run_count`
- 不会重复增加二级主题出现次数
- 不会重复追加账号 note 历史

这使得 Hermes 的定时任务在重试或补跑时更安全。

此外，`reports/memory_update_*.json` 会输出一份结构化回写结果，至少包含：

- `update_id`
- `summary_file`
- `state_file`
- `primary_themes`
- `secondary_themes`
- `account_notes`
- `theme_updates`
- `account_updates`
- `already_applied`

### 6. 索引、锁与原子写

当前实现已经不是“直接覆写 JSON 文件”的脆弱模式，而是补上了几层工程保护：

- **索引文件：** `memory/index.json` 汇总所有账号和主题文件，供快速遍历和跨机同步后恢复
- **索引版本：** 当前仓库初始化的 `memory/index.json` 是 `version: 2`
- **本地写锁：** `memory/.write.lock` 防止同一台机器上的并发任务同时写记忆
- **原子写：** 关键 JSON/TXT 落盘通过“临时文件 + `os.replace`”完成，减少异常退出时的半截文件风险

这里要注意一个边界：

- 本地 `.write.lock` 只能解决“同一台机器上的并发写”
- 它不能解决“两台 VPS 同时改记忆后再 git push”的冲突

也就是说，多 VPS 场景下真正需要注意的是 Git merge，而不是本地文件锁。

### 7. latest_run.json 与 Hermes 编排

`latest_run.json` 现在不只是“上次跑过的记录”，而是 Hermes 工作流的稳定入口。

`collect` 完成后，它会写入：

- 本轮 run id
- 产物路径
- 新推文数量
- warning 路径
- `memory_index` 路径
- `state` 路径

`apply-memory` 完成后，它还会补充：

- `memory_update_applied`
- 结构化 `memory_update` 结果
- 最新 `summary` 的 canonical 路径

当前实现还做了一件细节处理：

- 如果 `latest_run.json` 已经声明了某轮 canonical 的 `summary_<run_id>.txt`
- 而 `apply-memory` 收到的是另一个临时 summary 路径
- 它会优先把内容回收到 canonical summary 路径，再继续生成 `update_id`

这样同一轮任务的 summary 路径就不会在多次运行之间来回漂移。

### 8. 账号发现、告警与健康检查

发现引擎会统计所有新推文中的 @提及。如果某个不在监控列表里的账号被高频提及，就会进入推荐列表。

告警逻辑当前分成三类：

- **所有账号都落到登录墙**
- **所有账号都抓取异常**
- **所有账号页面都看不到可见推文**

只有当“所有账号都没有可见推文”时才会生成 warning。只要某个账号页面里确实有可见 tweet，系统就不会把“本轮新增为 0”误判成 cookies 失效。

---

## 文件结构

```
~/.hermes/skills/x-monitor/
├── monitor.py              # 主脚本
├── config.yaml             # 配置文件
├── cookies.json            # X 登录 cookies（敏感，不要提交到 git）
├── collectors/
│   ├── registry.yaml       # 多来源 collector 注册表
│   └── x/
│       └── source.yaml     # X 来源定义模板
├── references/
│   ├── architecture.md     # 四层边界、契约和职责分工
│   └── collector-schema.md # 统一 collector 输出 schema
├── memory/                 # 长期记忆目录
│   ├── state.json          # 去重状态（建议提交到 git）
│   ├── accounts/
│   │   └── elonmusk.json   # 一个账号一个文件
│   ├── themes/
│   │   └── AI_人工智能.json  # 一个一级主题一个文件，内部含二级主题
│   ├── index.json          # 账号/主题记忆总索引
│   └── .write.lock         # 本地并发写锁（运行时文件，不提交）
├── latest_run.json         # 最近一次运行的产物索引
├── SKILL.md                # Hermes skill 运行说明
├── reports/                # 输出目录
│   ├── data_YYYYMMDD_HHMMSS.json     # 原始数据（JSON）
│   ├── collector_batch_YYYYMMDD_HHMMSS.json # 标准化 collector batch
│   ├── prompt_YYYYMMDD_HHMMSS.txt    # LLM prompt
│   ├── report_YYYYMMDD_HHMMSS.txt    # 人类可读报告
│   ├── summary_YYYYMMDD_HHMMSS.txt   # Hermes 生成的完整总结（含 MEMORY_UPDATE）
│   ├── memory_update_YYYYMMDD_HHMMSS.json  # 解析后的记忆更新
│   └── warning_YYYYMMDD_HHMMSS.txt   # 告警（仅在异常时生成）
└── debug_*.png             # 调试截图（仅在加载失败时生成）
```

---

## 运行方式

### 手动运行

```bash
cd ~/.hermes/skills/x-monitor
python3 monitor.py collect --config config.yaml
```

常用查询命令：

```bash
python3 monitor.py latest --config config.yaml --field new_tweet_count
python3 monitor.py latest --config config.yaml --field collector_batch
python3 monitor.py latest --config config.yaml --field prompt
python3 monitor.py latest --config config.yaml --field warning
python3 monitor.py latest --config config.yaml --field state
```

### 通过 Hermes 定时运行

在 Hermes 对话中：

```
每 2 小时运行 python3 ~/.hermes/skills/x-monitor/monitor.py collect --config ~/.hermes/skills/x-monitor/config.yaml。
然后读取 latest_run.json 里的 new_tweet_count、warning 和 prompt 路径。
如果 warning 存在，直接把 warning 发到 Telegram。
如果 new_tweet_count 为 0，就告诉我本轮没有新推文并停止。
如果有新推文，就用 prompt 生成中文简报。
发送到 Telegram 时不要包含 MEMORY_UPDATE 段。
完整总结末尾必须带严格 JSON 的 MEMORY_UPDATE，
并且把完整总结保存到 latest_run.json 里的 summary 路径，
再运行 python3 ~/.hermes/skills/x-monitor/monitor.py apply-memory --config ~/.hermes/skills/x-monitor/config.yaml --summary-file <summary_path>。
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

# 去重状态文件（建议提交到 git）
state_file: "memory/state.json"

# 记忆目录
memory_dir: "memory"

# 输出目录和最近一次运行索引
output_dir: "reports"
latest_run_file: "latest_run.json"

# 一级主题别名归一化
theme_aliases:
  "AI/人工智能":
    - "AI"
    - "人工智能"
    - "大模型"
    - "LLM"
  "Space/航天":
    - "Space"
    - "航天"
    - "火箭"

# 二级主题别名归一化（按一级主题分别配置）
secondary_theme_aliases:
  "AI/人工智能":
    "Grok":
      - "grok3"
      - "Grok 3"
    "AI监管":
      - "AI policy"
      - "AI政策"
      - "监管"
  "Space/航天":
    "Starship":
      - "Starship Flight"
      - "星舰"

# 预定义主题方向（可选，引导 LLM 的归类方向）
themes:
  - "AI/人工智能"
  - "加密货币/区块链"
  - "地缘政治"
  - "科技行业"
  - "Space/航天"

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

当前的推文提取仍然依赖 X 的 DOM 结构，尤其是 `tweetText`、`tweetPhoto`、`videoPlayer` 等选择器。虽然实现已经补了 `div[lang]` 和 `a[href*="/status/"]` 的 fallback，但如果 X 做大范围前端改版，仍然可能失效。

**应对方式：** 如果某天突然所有账号都抓取到 0 条推文但 cookies 没过期，大概率是选择器变了。检查 `debug_*.png` 截图确认页面状态，然后更新 `monitor.py` 中的选择器。

### 本地锁与多 VPS 冲突

系统现在有 `memory/.write.lock`，它能避免同一台机器上两个进程同时写记忆文件。

但它解决不了下面这种情况：

- VPS A 拉了仓库并运行
- VPS B 也拉了仓库并运行
- 两边都改了 `memory/`，然后分别 push

这种冲突最终还是会体现在 Git merge 上。因此如果你要多机并行跑同一份 skill，仍然需要额外约束“谁负责写主记忆”。

### 原子写与恢复边界

现在关键 JSON/TXT 落盘已经使用临时文件再 `os.replace` 的方式，正常情况下比直接覆写安全很多。

但原子写解决的是“单文件写坏”的问题，不解决：

- 逻辑层面的错误 summary
- 多文件之间的跨文件事务一致性
- 多 VPS 的并行修改冲突

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

- **补正式测试文件：** 当前核心路径已经做过手工回归，但还缺少仓库内的自动化单元测试。
- **把 apply-memory 串进固定 cron workflow：** 当前接口已经稳定，下一步可以进一步模板化 Hermes cron 提示词。
- **Telegram 消息格式优化：** 根据 Telegram 的 Markdown 格式限制调整输出，让图片以内联预览显示。
- **多次运行的趋势报告：** 每周生成一份周报，基于 memory/themes 里的一级/二级主题变化分析热度趋势。

### 中期可做

- **关键词搜索扩展：** 不只监控特定账号，还能搜索特定关键词的公开讨论。需要在 Playwright 中打开 X 搜索页面。
- **互动图谱可视化：** 基于 mentions 数据生成账号关系网络图，直观展示谁在跟谁互动。
- **多语言支持：** 当前 prompt 默认输出中文，可配置为其他语言。

### 长期可做

- **自动调整监控列表：** 基于发现引擎的推荐和 LLM 的判断，自动将高价值账号加入监控列表。
- **与其他数据源联动：** 结合 Reddit、Hacker News、RSS 等信息源，做跨平台的主题追踪。
- **本地 embedding 搜索：** 将历史推文向量化存储，支持语义搜索——"最近谁讨论过半导体出口管制？"
