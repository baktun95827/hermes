# 给本地 Codex 的项目介绍

如果你是在这个 repo 里本机开发 `signal-radar`，先读这份文档。如果你是在 VPS 上以 Hermes 已安装 skill 的方式运行它，请看上一级的 `SKILL.md`；那份文档默认使用 `~/.hermes/skills/signal-radar/...` 路径和部署态工作流。

这是一套长期运行的社交信号采集与分析 skill，目前主来源是 X，后续会扩展到 Reddit、雪球等来源。

项目目标不是“抓到推文就结束”，而是把远程内容收集到本地，再做主题归类、记忆更新和摘要输出。当前运行主线是：

```text
collect -> build-analysis-input -> analyzer -> apply-memory
```

## 你先要知道的几件事

- 这是一个 skill，不是独立 Web 服务
- 当前主入口是 `monitor.py`
- `SKILL.md` 主要面向部署态 / Hermes operator
- 这份文档主要面向 repo-local 开发和本机验证
- 当前 runtime 还是 X-first，但文档和 schema 已经开始为多来源做准备
- 当前只实现 `memory_backend: file`，`memory/` 是 file backend 的本地目录，建议随 Git 同步
- `cookies.json`、`reports/`、`latest_run.json` 不应提交
- `memory/state.json` 里 `updated_at` 是当前更可靠的状态写入时间，`last_run` 主要保留给旧消费者兼容使用
- 记忆模型已经从宽泛主题扩展为 claim-driven memory，可维护标的、事件、宏观、来源评价和疑似冲突
- `MEMORY_UPDATE` 现在也承载价值判断和 diff：`event_clusters`、`signal_evaluation`、`cluster_id`、`what_changed`、`contradictions`、`alert_candidates`
- 每轮会生成 `run_metrics_<run_id>.json`，先记录抓取健康指标，再由 `build-analysis-input` 回填输入构建指标，最后由 `apply-memory` 回填事件簇和 memory 写入指标

## 当前最重要的文件

- `SKILL.md`
  部署态运行入口、标准流程、对 Hermes 的调用约定
- `monitor.py`
  当前 collector、analysis input builder 和 memory bridge 的核心实现
- `config.yaml`
  账号列表、cookies 路径、state、memory、输出目录
- `references/architecture.md`
  分层边界，判断一段逻辑该放哪时先看这个
- `references/collector-schema.md`
  多来源 collector 的统一输出 schema
- `references/memory-schema.md`
  金融/地缘场景下的标的、事件、宏观和来源记忆 schema
- `claude.md`
  当前实现细节、选择器、状态结构、调试方式

## 当前架构边界

- `collector`
  负责浏览器抓取和标准化输出，不负责主观判断
- `analysis input`
  负责读取 `collector_batch` 和 memory context，生成 `analysis_input` 与 prompt
- `local store`
  负责落地 `reports/`、`latest_run.json`、`memory/`、`run_metrics`
- `analyzer`
  负责读 prompt，生成摘要与 `MEMORY_UPDATE`
- `apply-memory`
  是 analyzer 提交 `MEMORY_UPDATE` 到当前 memory backend 的唯一入口

如果你准备改代码，尽量不要把抓取逻辑、主题判断、通知逻辑重新揉成一个大脚本。

## 本地最小验证

如果本地只是想确认工程代码和 Playwright 能正常工作，不需要先跑 Hermes。最小步骤是：

```bash
pip3 install --break-system-packages playwright pyyaml
python3 -m playwright install chromium --with-deps
python3 -m py_compile skills/signal-radar/monitor.py
python3 skills/signal-radar/monitor.py collect --config skills/signal-radar/config.yaml
python3 skills/signal-radar/monitor.py build-analysis-input --config skills/signal-radar/config.yaml
```

前提：

- `skills/signal-radar/cookies.json` 已准备好
- `config.yaml` 里至少配置了一个账号

## 当前输出约定

- 原始运行产物在 `reports/`
- 最新运行索引在 `latest_run.json`
- 当前 memory backend 是 `file`
- 同步记忆在 `memory/`
- 去重状态在 `memory/state.json`，其中 `updated_at` 比 `last_run` 更适合表示最近一次成功写入
- 标的记忆在 `memory/entities/`
- 持续事件记忆在 `memory/events/`
- 宏观趋势记忆在 `memory/macro/`
- 来源评价记忆在 `memory/sources/`
- 疑似冲突观察在 `memory/contradictions/`
- 标准化 batch 产物是 `collector_batch_<run_id>.json`
- 分析输入产物是 `analysis_input_<run_id>.json`
- LLM prompt 由 `build-analysis-input` 生成到 `prompt_<run_id>.txt`
- 运行指标产物是 `run_metrics_<run_id>.json`
- 统一 schema 是 `collector-batch/v1` 和 `collector-item/v1`
- 结构化记忆更新可以包含 `event_clusters`、`signal_evaluations`、各 claim 的 `signal_evaluation`、diff 字段、标的内嵌 `thesis_update`、结构化 `source_profile`、疑似 `contradictions`、以及只供下游判断的 `alert_candidates`

## 你改代码时最容易踩的坑

- 不要提交 `cookies.json`
- 不要把 `reports/` 当成长期数据源
- 不要把 `last_run` 当成当前状态的唯一时间依据
- 不要绕过 `apply-memory` 直接手写 memory 回写逻辑
- 不要让业务逻辑依赖“文件路径就是业务模型”；依赖 `MEMORY_UPDATE` 和 memory backend 边界
- 不要把未经验证的社交媒体观点写成 `confirmed`
- 不要把复读或噪音信号写进长期 memory；应使用 `signal_type: repeat|noise` 或 `memory_action: skip`
- 不要把同一事件的多条转述当成多条新信息；先合并到同一个 `event_clusters[].cluster_id`
- 不要把 `contradictions` 当成事实裁决；它只是冲突观察，后续还需要验证
- 不要把普通新闻都写成 thesis；只有信息改变 bull/bear case、关键验证点、证伪条件或催化时间表时才写 `thesis_update`
- 不要把 analyzer 重新耦合回浏览器流程
- 不要让 `collect` 重新读取长期 memory 或生成 prompt；这属于 `build-analysis-input`
- 如果只是要接新 source，优先补 `collectors/<source>/source.yaml` 和标准化输出，不要先改摘要层

## 一句话总结

Signal Radar 现在本质上是一个“X 先行、面向多来源演进”的 collector + analysis input + memory skill。你本地开发时，重点是保证 `monitor.py`、Playwright、标准化产物和 `analysis_input` 契约稳定，再逐步把 analyzer 从 X 专用输入迁到统一 schema。
