# Collector Schema

这份文档定义多来源 collector 的统一契约。它的目标不是规定“本地最终怎么存”，而是规定 collector 收完远程内容后，至少要能稳定交付什么。

因此：

- collector 可以用 Playwright、requests、官方 API、RSS
- 本地存储方式以后可以继续演进
- 但 collector 输出给后续层的结构应该尽量统一

## 设计原则

### 1. 顶层字段尽量跨来源通用

不要在统一 schema 顶层直接写 `tweet_id`、`subreddit_name`、`雪球组合` 这种只适合单一来源的字段。来源专属信息应该放到 `source_meta` 里。

### 2. `canonical_id` 必须带来源前缀

不要只存裸 ID。统一要求：

- X: `x:1234567890`
- Reddit: `reddit:t3_abc123`
- 雪球: `xueqiu:987654321`

这样可以避免跨来源 ID 冲突，也方便去重和记忆归属。

### 3. collector 只负责拿材料，不负责判断价值

collector 输出应该是“远程内容的本地标准化结果”，而不是主题归类、日报结论、账号画像。

### 4. 来源专属字段允许保留，但必须下沉

标准化不是丢信息。X 的 `quoted_text`、Reddit 的 `subreddit`、雪球的 `symbol` 都可以保留，但应该放到 `source_meta` 或 `relations`。

## 文件组织

建议每个来源至少有这两个文件：

```text
collectors/
  registry.yaml
  x/
    source.yaml
```

职责分工：

- `collectors/registry.yaml`
  - 负责注册有哪些 source、各自入口在哪里、属于哪种 transport
- `collectors/<source>/source.yaml`
  - 负责这个 source 的机器可读配置和能力描述
- Python 代码
  - 负责真实抓取逻辑

当前仓库已经先补了 `registry.yaml` 和 `collectors/x/source.yaml`。  
需要注意：**它们现在是契约和设计骨架，不是已经接入运行时的动态加载系统。**

当前运行时已经完成了第一步接线：

- `monitor.py collect` 会额外写出 `reports/collector_batch_<run_id>.json`
- 该文件顶层使用 `collector-batch/v1`
- 其中每个 item 使用 `collector-item/v1`

也就是说，X 现在已经开始产出统一 schema，但 analyzer 还没有完全切到只消费这份 schema。

## Registry 契约

`collectors/registry.yaml` 建议至少包含：

- `version`
- `contracts.batch_schema`
- `contracts.item_schema`
- `sources.<source_id>.display_name`
- `sources.<source_id>.source_file`
- `sources.<source_id>.transport`
- `sources.<source_id>.runtime`
- `sources.<source_id>.target_kind`
- `sources.<source_id>.auth_type`
- `sources.<source_id>.status`

推荐 transport 枚举：

- `browser`
- `http`
- `api`
- `rss`

## Source Definition 契约

每个 `source.yaml` 建议至少定义这些块：

- `id`
- `display_name`
- `collector`
- `targets`
- `auth`
- `fetch`
- `capabilities`
- `healthcheck`
- `normalization`
- `status`

### 这些块分别表达什么

- `collector`
  - 抓取实现方式，例如 `browser + playwright`
- `targets`
  - 这个来源监控的对象是什么，例如 account、subreddit、symbol、keyword
- `auth`
  - 认证类型和本地 secret 形态
- `fetch`
  - 分页、超时、重试、节奏
- `capabilities`
  - 能否抓媒体、引用内容、评论、线程
- `healthcheck`
  - 如何判断登录墙、空页面、调试截图
- `normalization`
  - 统一 ID 命名、哪些字段保留到 `source_meta`
- `status`
  - 当前来源的接入成熟度和运行集成状态

## 标准输出：Batch Envelope

collector 交给后续层时，建议统一成一个 batch envelope。推荐版本名：

- `collector-batch/v1`

示例：

```json
{
  "schema_version": "collector-batch/v1",
  "source": "x",
  "collector_run_id": "20260414_120501",
  "collected_at": "2026-04-14T12:05:01Z",
  "target": {
    "kind": "account",
    "id": "elonmusk",
    "display_name": "@elonmusk"
  },
  "collector": {
    "transport": "browser",
    "implementation": "playwright"
  },
  "items": [],
  "warnings": [],
  "raw_meta": {}
}
```

### Batch 必备字段

- `schema_version`
- `source`
- `collector_run_id`
- `collected_at`
- `target`
- `collector`
- `items`

### Batch 可选字段

- `warnings`
- `next_cursor`
- `raw_meta`
- `item_schema_version`
- `item_count`

### 多目标 collector 的约定

如果一次 run 同时抓多个目标，不强制每个目标单独一个文件。当前 X collector 的做法是：

- 顶层仍然输出一个 `collector-batch/v1`
- `target.kind` 可为 `account_set`
- `target.members` 记录本轮配置里的多个账号
- 每个 item 再通过自身字段和 `source_meta.source_account` 保留来源上下文

## 标准输出：Item Schema

batch 里的每个 item 建议统一成：

- `collector-item/v1`

示例：

```json
{
  "schema_version": "collector-item/v1",
  "source": "x",
  "item_id": "1911780212345678901",
  "canonical_id": "x:1911780212345678901",
  "content_type": "post",
  "published_at": "2026-04-14T11:50:00Z",
  "collected_at": "2026-04-14T12:05:01Z",
  "url": "https://x.com/elonmusk/status/1911780212345678901",
  "title": null,
  "text": "We need to move faster on launch cadence.",
  "language": "en",
  "author": {
    "source": "x",
    "entity_type": "account",
    "entity_id": "elonmusk",
    "canonical_entity_id": "x:elonmusk",
    "display_name": "Elon Musk",
    "handle": "@elonmusk",
    "url": "https://x.com/elonmusk"
  },
  "metrics": {
    "likes": 120000,
    "replies": 9000,
    "reposts": 15000,
    "views": null
  },
  "media": [
    {
      "type": "image",
      "url": "https://pbs.twimg.com/media/example.jpg"
    }
  ],
  "relations": {
    "is_repost": false,
    "quoted_item_id": null,
    "reply_to_item_id": null,
    "mentioned_entities": ["x:nasa"]
  },
  "source_meta": {
    "quoted_text": null,
    "has_video": false
  }
}
```

## Item 字段建议

### 必备字段

- `schema_version`
- `source`
- `item_id`
- `canonical_id`
- `content_type`
- `published_at`
- `collected_at`
- `url`
- `text`
- `author`

### 推荐字段

- `title`
- `language`
- `metrics`
- `media`
- `relations`
- `source_meta`

## 字段设计说明

### `source`

固定标识来源，例如：

- `x`
- `reddit`
- `xueqiu`

### `item_id`

来源内原生 ID，不带命名空间。

### `canonical_id`

跨来源唯一 ID，必须带来源前缀。

### `content_type`

建议枚举：

- `post`
- `comment`
- `thread`
- `article`
- `quote`

### `author`

统一成对象，而不是散落多个字段。这样后面 analyzer 和 memory 更容易做跨来源实体处理。

建议包含：

- `source`
- `entity_type`
- `entity_id`
- `canonical_entity_id`
- `display_name`
- `handle`
- `url`

### `metrics`

只放标准化数值指标。来源没有的字段可以是 `null` 或缺失。

### `media`

数组，每项至少有：

- `type`
- `url`

如果来源能拿到更多信息，也可以补：

- `width`
- `height`
- `thumbnail_url`
- `duration_seconds`

### `relations`

这里放和其他内容、其他实体的关系，比如：

- 是否 repost / retweet
- reply to 谁
- quote 了谁
- mention 了哪些实体

### `source_meta`

这里放来源专属但又不想丢的信息。规则是：

- 能标准化的，优先标准化到顶层
- 不能稳定标准化的，再放 `source_meta`

## X / Reddit / 雪球的兼容思路

### X

- transport 可能是 `browser`
- `text` 对应 tweet 正文
- `relations` 里可表达 repost、quote、mentions
- `source_meta` 可保留 `quoted_text`、`has_video`

### Reddit

- transport 可能是 `http` 或 `api`
- `content_type` 可能是 `post` 或 `comment`
- `title` 通常有值
- `source_meta` 可保留 `subreddit`、`score`、`num_comments`

### 雪球

- transport 可能是 `http` 或 `browser`
- `source_meta` 可保留 `symbol`、`market`、`device_hint`

## 当前落地范围

当前这一步已经完成了四件事：

1. 定义 `collectors/registry.yaml`
2. 定义 `collectors/x/source.yaml`
3. 定义统一 collector schema 文档
4. 让 `monitor.py collect` 开始额外输出 `collector-batch/v1`

还没有完成的部分：

- 运行时按 `registry.yaml` 自动加载 source
- 新增 Reddit / 雪球 collector

也就是说，**这一步已经让 X 先产出统一 schema，但还没有宣称多源运行时已经完成。**
