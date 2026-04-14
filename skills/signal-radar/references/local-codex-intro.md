# 给本地 Codex 的项目介绍

这是一套长期运行的社交信号采集与分析 skill，目前主来源是 X，后续会扩展到 Reddit、雪球等来源。

项目目标不是“抓到推文就结束”，而是把远程内容收集到本地，再做主题归类、记忆更新和摘要输出。当前运行主线是：

```text
collect -> local store -> analyzer -> apply-memory
```

## 你先要知道的几件事

- 这是一个 skill，不是独立 Web 服务
- 当前主入口是 `monitor.py`
- 当前 runtime 还是 X-first，但文档和 schema 已经开始为多来源做准备
- `memory/` 建议随 Git 同步
- `cookies.json`、`reports/`、`latest_run.json` 不应提交

## 当前最重要的文件

- `SKILL.md`
  运行入口、标准流程、对 Hermes 的调用约定
- `monitor.py`
  当前 collector 和 memory bridge 的核心实现
- `config.yaml`
  账号列表、cookies 路径、state、memory、输出目录
- `references/architecture.md`
  四层边界，判断一段逻辑该放哪时先看这个
- `references/collector-schema.md`
  多来源 collector 的统一输出 schema
- `claude.md`
  当前实现细节、选择器、状态结构、调试方式

## 当前架构边界

- `collector`
  负责浏览器抓取和标准化输出，不负责主观判断
- `local store`
  负责落地 `reports/`、`latest_run.json`、`memory/`
- `analyzer`
  负责读 prompt 和 memory，生成摘要与 `MEMORY_UPDATE`
- `apply-memory`
  是 analyzer 写回 memory 的唯一入口

如果你准备改代码，尽量不要把抓取逻辑、主题判断、通知逻辑重新揉成一个大脚本。

## 本地最小验证

如果本地只是想确认工程代码和 Playwright 能正常工作，不需要先跑 Hermes。最小步骤是：

```bash
pip3 install --break-system-packages playwright pyyaml
python3 -m playwright install chromium --with-deps
python3 -m py_compile skills/signal-radar/monitor.py
python3 skills/signal-radar/monitor.py collect --config skills/signal-radar/config.yaml
```

前提：

- `skills/signal-radar/cookies.json` 已准备好
- `config.yaml` 里至少配置了一个账号

## 当前输出约定

- 原始运行产物在 `reports/`
- 最新运行索引在 `latest_run.json`
- 同步记忆在 `memory/`
- 标准化 batch 产物是 `collector_batch_<run_id>.json`
- 统一 schema 是 `collector-batch/v1` 和 `collector-item/v1`

## 你改代码时最容易踩的坑

- 不要提交 `cookies.json`
- 不要把 `reports/` 当成长期数据源
- 不要绕过 `apply-memory` 直接手写 memory 回写逻辑
- 不要把 analyzer 重新耦合回浏览器流程
- 如果只是要接新 source，优先补 `collectors/<source>/source.yaml` 和标准化输出，不要先改摘要层

## 一句话总结

Signal Radar 现在本质上是一个“X 先行、面向多来源演进”的 collector + memory skill。你本地开发时，重点是保证 `monitor.py`、Playwright 和标准化产物稳定，再逐步把 analyzer 从 X 专用输入迁到统一 schema。
