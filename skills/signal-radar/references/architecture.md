# Signal Radar 分层架构

这份文档定义 `signal-radar` 的稳定边界。只要你在判断“某段逻辑到底该放在哪”，就应该先看这里，而不是直接改实现。

## 目标

`signal-radar` 不是一个“大模型从打开网页一路干到发 Telegram”的单体 agent，而是一条长期运行的工作流。为了让系统更容易调试、更容易换实现，也更容易定位问题，当前设计故意拆成清晰的文件边界层：

```text
collector -> analysis input -> local store -> analyzer -> digest / alerts
```

在当前实现里，这些层大致对应：

- `collector`
  - `monitor.py collect`
  - `collectors/registry.yaml` 和 `collectors/<source>/source.yaml` 现在作为多源接入契约存在，但运行时尚未切到 registry 驱动
- `analysis input`
  - `monitor.py build-analysis-input`
  - 读取 `collector_batch` 和 memory context，写出 `analysis_input` 与 `prompt`
- `local store`
  - `reports/*.json|*.txt`
  - `latest_run.json`
  - `MemoryBackend`
  - `memory/`（当前 file backend）
- `analyzer`
  - LLM 读取 prompt，生成摘要和 `MEMORY_UPDATE`
- `digest / alerts`
  - Telegram 或其他下游通知逻辑
- `monitor.py apply-memory`
  - 负责把 analyzer 的 `MEMORY_UPDATE` 安全提交到当前 memory backend

## 为什么要分层

因为这些问题的失败模式完全不同：

- collector 失败
  - cookies 过期
  - 登录墙
  - selector 变化
  - 页面慢或风控
- analysis input 失败
  - collector schema 不兼容
  - memory context 读取失败
  - prompt 契约或路径错误
- local store 失败
  - 路径解析错误
  - JSON 损坏
  - Git merge 冲突
  - latest manifest 漂移
- analyzer 失败
  - 主题归类不准
  - 总结质量差
  - `MEMORY_UPDATE` 格式不合法
- digest / alerts 失败
  - 不该发的时候发了
  - 该发的时候没发
  - Telegram 格式不对

如果把这些逻辑揉在一起，最后很难判断是“没抓到内容”，还是“抓到了但判断错了”。分层的价值就在这里。

## 第 1 层：Collector

### 目标

稳定拿到原始材料，并把抓取结果落地成可复查的文件。

### 当前负责模块

- `monitor.py collect`
- `collectors/registry.yaml`
- `collectors/<source>/source.yaml`

### 多源设计约束

collector 未来不应该只对应 X。它应该允许不同来源使用不同 transport，例如：

- `browser`
- `http`
- `api`
- `rss`

因此现在先引入两层契约：

- `collectors/registry.yaml`
  - 注册有哪些 source，以及它们的入口和 transport
- `collectors/<source>/source.yaml`
  - 描述这个 source 的抓取方式、认证方式、healthcheck 和标准化规则

需要注意：当前仓库里这套 registry/source 定义还是“准备态契约”，还没有替换现有 `monitor.py collect` 的直接入口。

### 应该负责什么

- 读取配置和 cookies
- 用 Playwright 打开 X 页面
- 滚动页面并提取可见推文
- 规范化基础字段
- 检查页面是否明显异常
- 写出原始产物和 `latest_run.json`

### 输入

- `config.yaml`
- `cookies.json`
- 监控账号列表
- 当前浏览器 / 网络环境

### 输出

- `reports/data_<run_id>.json`
- `reports/collector_batch_<run_id>.json`
- `reports/run_metrics_<run_id>.json`
- 可选的 `reports/warning_<run_id>.txt`
- `latest_run.json`
- 更新后的 `memory/state.json`

当前实现已经会额外输出 `collector-batch/v1` 和 `collector-item/v1` 契约，便于 analyzer 以后跨来源工作。schema 定义见 `references/collector-schema.md`。

### 不应该负责什么

- 最终主题判断
- 账号画像归纳
- 读取长期 memory
- 生成 analyzer prompt
- Telegram 发消息
- 主观决定“这条值不值得进日报”

### 允许做的确定性判断

collector 仍然可以做一些边界清晰的判断，比如：

- 按 `seen_ids` 去重
- 判断页面状态是 `ok`、`login_wall`、`no_visible_tweets` 还是 `error`
- 统计 mentions 和基础互动数

### 典型失败信号

- 所有账号都落到登录墙
- 所有账号都没有可见推文
- Playwright / 页面异常
- selector 漂移导致抓取字段缺失

collector 的责任是把这些失败表达成文件和 manifest 字段，而不是自己生成“看起来像摘要”的用户输出。

## 第 2 层：Analysis Input

### 目标

把标准化 collector batch、发现提示和当前 memory context 组装成可回放的 analyzer 输入。

### 当前负责模块

- `monitor.py build-analysis-input`
- `reports/analysis_input_<run_id>.json`
- `reports/prompt_<run_id>.txt`
- `reports/report_<run_id>.txt`

### 输入

- `reports/collector_batch_<run_id>.json`
- `config.yaml`
- 当前 `MemoryBackend`

### 输出

- `reports/analysis_input_<run_id>.json`
- `reports/prompt_<run_id>.txt`
- `reports/report_<run_id>.txt`
- 更新后的 `latest_run.json`
- 更新后的 `reports/run_metrics_<run_id>.json`

### 应该负责什么

- 将 source-agnostic collector items 转换成 analyzer 可读材料
- 读取近期主题、标的、事件、宏观和来源记忆
- 生成 discovery hints 和关键词
- 生成 prompt

### 不应该负责什么

- 打开浏览器或重新抓取网页
- 对用户发送摘要
- 写入长期 memory
- 代替 LLM 判断 claim 是否真实或值得记忆

## 第 3 层：Local Store

### 目标

把原始产物、运行状态和长期记忆可靠地落到本地，让后续步骤只读本地文件，不直接依赖浏览器会话。

### 当前负责模块

- `reports/`
- `latest_run.json`
- `memory/`
- `monitor.py` 里的原子写 helpers
- `StateManager`
- `MemoryBackend`
- `FileMemoryStore`
- `ThemeNormalizer`

### 数据类型

#### 运行产物

这类文件是“某一轮 run 的快照”，主要用于调试、回放和后续处理：

- `reports/data_<run_id>.json`
- `reports/collector_batch_<run_id>.json`
- `reports/analysis_input_<run_id>.json`
- `reports/prompt_<run_id>.txt`
- `reports/report_<run_id>.txt`
- `reports/summary_<run_id>.txt`
- `reports/memory_update_<run_id>.json`
- `reports/run_metrics_<run_id>.json`
- `reports/warning_<run_id>.txt`

它们很重要，但不是长期记忆的最终真源。

`run_metrics_<run_id>.json` 是机器可读健康指标。`collect` 写入账号抓取、可见推文、新推文、warning 和运行耗时；`build-analysis-input` 回填 analyzer input 是否构建、输入条数、发现推荐数和关键词数；`apply-memory` 回填事件簇、强增量事件、候选告警、冲突数和各类 memory 写入数。它用于判断“没有新信息”和“系统链路异常”之间的区别。

#### 运行 manifest

`latest_run.json` 是当前工作流的控制面入口。它负责告诉下游：

- 这一轮的 `run_id`
- 本轮产物路径
- 新推文数量
- warning 是否存在
- memory 是否已经 apply

当前关键字段包括：

- `run_id`
- `status`
- `paths.data`
- `paths.collector_batch`
- `paths.analysis_input`
- `paths.prompt`
- `paths.report`
- `paths.summary`
- `paths.memory_update`
- `paths.run_metrics`
- `paths.memory_index`
- `paths.state`
- `paths.warning`
- `paths.memory_dir`
- `memory_backend`
- `summary.new_tweet_count`
- `summary.event_cluster_count`
- `memory_update_applied`

#### 长期记忆

当前实现使用 `memory_backend: file`。`memory/` 是 file backend 的本地状态目录，可随 Git 同步、跨机器延续：

- `memory/state.json`
- `memory/accounts/<username>.json`
- `memory/themes/<primary-theme>.json`
- `memory/entities/<entity-id>.json`
- `memory/events/<event-id>.json`
- `memory/macro/<macro-id>.json`
- `memory/sources/<source-id>.json`
- `memory/contradictions/<contradiction-id>.json`
- `memory/index.json`

`accounts/` 和 `themes/` 保留原有账号画像与宽泛主题记忆。`entities/`、`events/`、`macro/`、`sources/` 和 `contradictions/` 用于金融/地缘场景下的 claim-driven memory，详细契约见 `references/memory-schema.md`。

这里的关键边界是：业务层依赖 `MemoryBackend` 和 `MEMORY_UPDATE` contract，而不是依赖文件路径本身。当前只实现 `FileMemoryStore`，未来如果需要 Postgres，应新增 backend 实现，不应改 analyzer 输出协议。

### Git 同步边界

这些应该提交：

- 代码
- `config.yaml`
- `memory/`

这些不应该提交：

- `cookies.json`
- `latest_run.json`
- `reports/`
- 调试截图
- `memory/.write.lock`

### 不应该负责什么

- 打开网页
- 决定内容的重要性
- 直接发送消息

local store 的职责是“保存状态并暴露清晰契约”，不是“替业务做判断”。

## 第 4 层：Analyzer

### 目标

基于 collector 收集到的内容和已有记忆，判断“这次到底新了什么、该怎么归类、记忆该怎么更新”。

### 当前负责模块

- `build-analysis-input` 生成的 prompt
- LLM 总结步骤
- 严格 JSON 的 `MEMORY_UPDATE` 协议

### 输入

- `reports/analysis_input_<run_id>.json`
- `reports/prompt_<run_id>.txt`

### 输出

- 用户可读的中文摘要
- 带 `### MEMORY_UPDATE` 的完整 summary
- 严格 JSON 对象，包含：
  - `primary_themes`
  - `secondary_themes`
  - `account_notes`
  - `event_clusters`
  - `signal_evaluations`
  - `entity_updates`
  - `entity_updates[].thesis_update`
  - `event_updates`
  - `macro_updates`
  - `source_assessments`
  - `alert_candidates`
  - `contradictions`

### 不应该负责什么

- 打开网页
- 重试浏览器
- 判断 cookies 是否健康
- 直接改写 `memory/*.json`
- 最终决定是否发送候选告警

analyzer 应该只吃本地落地的数据。如果 analyzer 觉得材料不够，通常说明 collector 的契约还不够完整，应该补 collector，而不是让 analyzer 自己去碰网页。

### 质量要求

analyzer 至少应该回答这些问题：

- 这轮真正新增了什么
- 哪些推文应该被合并为同一个 `event_clusters`，避免同一事件多次污染摘要和 memory
- 它们属于哪些一级主题
- 各一级主题下应该记录哪些二级主题
- 哪些账号画像需要更新
- 哪些内容是新事实、新角度、复读或噪音
- 每个重要信号的 `novelty_level`、`evidence_strength`、`memory_action` 和 `alert_level` 应该是什么
- 每个重要 claim 相对旧记忆或近期 run 的 `what_changed`、`changed_since` 和 `prior_claim_refs` 是什么
- 哪些金融标的、公司、行业链条 claim 值得进入 `entity_updates`
- 哪些标的信息改变了 bull/bear thesis、关键验证点、证伪条件或催化时间表
- 哪些持续事件需要按时间线进入 `event_updates`
- 哪些宏观背景或趋势需要进入 `macro_updates`
- 哪些来源可信度或确认要求需要更新到 `source_assessments`
- 来源画像是否需要更新 `source_type`、`topic_scores`、`trust_score`、`repeat_rate`、`valuable_count`、`marketing_tendency`、`emotion_tendency`、`primary_source_score` 或 `confirmation_required`
- 来源画像的 `metrics`、`rates`、`topic_counts` 和 `contribution_history` 由 `apply-memory` 从 event clusters / claim updates 自动累积，不由 analyzer 手工编造
- 哪些内容只是 `alert_candidates`，需要交给 digest / alerts 再决定是否发送
- 哪些内容存在疑似冲突，应进入 `contradictions` 观察但不自动裁决真假
- 哪些内容值得进入最终 digest

它不应该机械地把每条推文都重复一遍。

对于社交媒体内容，analyzer 应该保守标注验证状态。单一来源通常只能是 `unverified` 或 `plausible`；只有官方或多源证据支持时，才应该输出 `confirmed`。

## 第 5 层：Digest / Alerts

### 目标

决定什么内容要发出去、什么时候发、用什么形式发。

### 当前负责模块

- Hermes cron / operator prompt
- Telegram gateway 流程
- 任何读取 `latest` 并做对外发送的自动化

### 输入

- `latest_run.json`
- 可选的 warning 文件
- analyzer 生成的 summary

### 输出

- Telegram digest
- warning / incident 消息
- 或者无动作

### 规则

- 如果有 `warning`，发 warning 并停止
- 如果 `new_tweet_count == 0` 且没有 warning，不发摘要
- 如果有新推文，只发送用户可读部分
- 不要把原始 `MEMORY_UPDATE` 发到 Telegram
- 完整 summary 保存后，再执行 `apply-memory`

### 不应该负责什么

- 爬网页
- 修改原始推文数据
- 在没有 analyzer 输出时凭空造 memory update

## 层与层之间的契约

### Collector -> Local Store

collector 必须留下足够多的本地证据，至少包括：

- 结构化数据 JSON
- 标准化 collector batch JSON
- 需要时的 warning 文件
- 稳定可读的 latest manifest

如果 collector 失败了，但本地什么都没留下，后续排查会很被动。

### Local Store -> Analysis Input

analysis input builder 依赖的应该是稳定文件路径，而不是浏览器上下文。当前主契约是：

- `latest --field collector_batch`
- `latest --field memory_dir`
- `latest --field memory_backend`

它输出：

- `latest --field analysis_input`
- `latest --field prompt`

如果未来进入多源模式，analysis input builder 应该优先消费统一的 collector schema，而不是来源专属字段。

### Analysis Input -> Analyzer

analyzer 依赖的应该是稳定 prompt 和 replayable input，而不是直接读浏览器或扫描目录。当前主契约是：

- `latest --field prompt`
- `latest --field analysis_input`
- `latest --field summary`
- `latest --field state`

### Analyzer -> Local Store

analyzer 的职责是输出可解析的 `MEMORY_UPDATE`。真正把它翻译成 backend 写入的提交者，应该始终是 `apply-memory`。

### Local Store -> Digest / Alerts

digest 应该从 manifest 做判断，而不是自己扫描目录、猜最新文件名。

## 当前文件所有权

如果你不确定该改哪，先按这个归类。

### 属于 collector 的逻辑

- Playwright selector
- 滚动策略和抓取节奏
- 推文字段提取
- warning 生成
- visible tweet count

### 属于 local store 的逻辑

- 路径解析
- 原子写
- lock 处理
- memory 文件 schema
- dedupe state schema
- manifest schema

### 属于 analysis input 的逻辑

- collector batch 到 prompt 的转换
- memory context 读取和压缩
- discovery hints
- keyword hints
- analysis_input artifact schema

### 属于 analyzer 的逻辑

- prompt wording
- 主题归类规则
- 摘要风格
- `MEMORY_UPDATE` 协议

### 属于 digest / alerts 的逻辑

- Telegram 格式
- 发 / 不发 / 告警条件
- cron 编排

## 实际判断规则

### 规则 1

如果一项改动需要真实浏览器会话，它大概率属于 collector。

### 规则 2

如果一项改动只碰 JSON schema、路径布局或 Git 同步行为，它大概率属于 local store。

### 规则 3

如果一项改动影响主题命名、记忆质量、什么叫“新增价值”，它属于 analyzer。

### 规则 4

如果一项改动影响通知对象、通知时机或 digest 渲染，它属于 digest / alerts。

### 规则 5

不要因为有一个上层 orchestrator，就把所有边界重新揉成一个 giant agent。上层可以串联各层，但不应该抹掉层与层之间的契约。

## 本地开发与 VPS 运行

这套架构不要求“只能本地”或“只能 VPS”，但两者更适合的事情不同：

- 本地更适合：
  - selector 调试
  - 可见浏览器检查
  - cookies 刷新
  - Playwright 迭代
- VPS 更适合：
  - 定时采集
  - 长时间运行
  - 记忆累积
  - Telegram 发送

推荐做法：

- collector 的调试优先在本地做
- 定时运行和正式 digest 放在 VPS
- 需要跨机延续状态时，用 Git 同步 `memory/`
- `cookies.json` 保持每台机器本地维护

## 多源演进的当前状态

现在已经完成：

- 分层架构边界
- collector registry 设计
- source definition 设计
- 统一 collector 输出 schema 设计

现在还没有完成：

- runtime 通过 registry 动态加载 source
- X collector 从单一 `monitor.py` 入口彻底拆成多源 collector 框架的一部分
- Reddit / 雪球等新 source 的真实 collector 实现

所以这一步的定位是：先把契约和骨架定下来，再逐步替换运行时。

## 演进原则

这套分层的最大价值，是以后替换实现时不用整套一起重来：

- 可以换 Playwright selector，而不改 analyzer 契约
- 可以换模型，而不改 collector 契约
- 可以换 Telegram 以外的通知渠道，而不改 memory 写入逻辑
- 以后就算把 `monitor.py` 拆成多个脚本，也不需要推翻这套分层模型

这也是为什么现在就要把边界写清楚。
