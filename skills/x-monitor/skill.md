# X (Twitter) Monitor Skill

监控指定 X 账号的最新推文，发现相关内容和账号，用中文总结后发送到 Telegram。

## 依赖

```bash
pip install twikit --break-system-packages
```

## 配置

编辑 `config.yaml`：

```yaml
# 监控的账号列表
accounts:
  - "elonmusk"
  - "kaboruo"

# 每次拉取每个账号的推文数量
tweets_per_account: 20

# cookies 认证（从浏览器导出）
auth:
  cookies_file: "cookies.json"  # twikit cookies 文件路径

# 发现模式：追踪被监控账号互动最多的人
discovery:
  enabled: true
  min_interactions: 3  # 某账号被提及/转推 >= 3 次才推荐
```

## 使用方式

### 在 Hermes 中直接对话

```
监控 @elonmusk 和 @kaboruo 的最新推文，用中文总结要点，发到 Telegram
```

### 定时任务

```
每 2 小时检查我监控列表里的 X 账号，总结新推文，标注值得关注的新账号，发 Telegram
```

### 手动运行

```bash
python monitor.py --config config.yaml
```

## Cookies 获取方法

1. 用 Chrome 登录 x.com
2. 安装 "EditThisCookie" 或 "Cookie-Editor" 扩展
3. 导出 cookies 为 JSON 格式，保存为 `cookies.json`
4. 或者用 twikit 内置登录（见 monitor.py 中的 login 部分）

## 输出格式

```
📊 X 监控报告 — 2026-04-06 18:00

👤 @elonmusk (5 条新推文)
• 宣布 xAI 新模型 Grok-3 即将发布，强调多模态能力
• 回应 FCC 关于 Starlink 的监管问题，态度强硬
• 🔥 热度最高：关于 AI 监管的推文 (12.3K 转推)

👤 @kaboruo (3 条新推文)
• ...

🔍 发现推荐
• @xxx — 被 @elonmusk 提及 4 次，主要讨论 AI 安全话题
• @yyy — 多条高互动回复，观点独特

📌 热点关键词：AI监管, Grok-3, Starlink
```