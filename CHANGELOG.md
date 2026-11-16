# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.1] — 2026-11-16

### 变更（省 token：认知摘要进 brief）

- **`pasm_context.brief` 升级为「认知摘要」**：身份锚 + 情绪语义 + 人格画像 + 显著度
  记忆，按优先级整块丢弃（坑 9 口径），默认 80 字档 ≈38 tok。实测整包 ~923 tok →
  brief 38 tok（省 ~96%），且比旧紧凑版（58 tok，只带 mood+3 标题）**更省且更全**。
  宿主无需改代码，注入 `brief` 字段即受益。
- **兼容性字段**：新增 `brief_digest`（始终是摘要）/ `brief_legacy`（始终是旧紧凑版）/
  `brief_mode` / `digest_meta`（kept/dropped 可观测）；`digest=false` 可回滚到旧行为，
  `digest_chars` 调预算（默认 80，要带 hint 可传 220）。
- **新增 `cognitive_digest.py`**：runtime 自包含摘要模块（零依赖 pasm2/pasm-skills），
  与 PASM 仓 analysis 版用黄金向量校验逐字一致，防两份实现漂移。
- **接入规范**：README 第五节明确「注入 `brief` 而非整包」，含字段表与省 token 口径。

### 验证

- 新增 `tests/test_cognitive_digest_ab.py`：A/B 对照全 PASS（一致性 / 回滚 / 信息保真 /
  省 token / preflight 防假绿）。
- `pasm-mcp-server --selftest`：18/18 全绿，无回归。
- 审核整改：修复 bench 在 Ollama 未起时召回 0 条导致的反例**空洞假绿**（加 preflight
  门禁 + 基线必须有 memory 块 + 报告带时间戳备份），整改后召回 5 条、数字可信。

## [0.3.0] — 2026-11-10

### 变更（默认认知后端 V1 → V2）

- **默认走 pasm2 V2 后端**：此前只有 `PASM2=1` 才切 V2 → 实际部署几乎永远跑 V1，
  新引擎等于没上线。现在默认 `create_backend(backend_choice="v2")`；
  pasm2 不可用 / 构造失败 → 工厂**如实回退 V1**（不虚构 v2 能力）。
- **逃生舱**：`PASM_BACKEND=v1`（或 `PASM2=0/false/no/off`）强制 V1。
- 为此在 `pasm2` 仓补齐了 V2 后端的基座契约：`episodes()`（认知层语义索引的数据源，
  此前缺它会让 `pasm_recall` / `pasm_semantic` 命中 0）、`feedback()` 词汇表对齐
  （praise 不再被当负反馈）、`persist_dir` + `save()/load()`（V2 认知状态可落盘续跑）。

### 新增

- **`pasm_context` 增加 `brief` 字段**：一段可直接注入提示词的紧凑上下文
  （此刻心情 + 你记得的几件事 + 当前焦点），几十 tok。
  此前整包返回体（recalled 全量 brief + persona 全量 + action_pool + hint）
  直接塞进提示词实测约 500 tok —— **省 token 是 PASM 的初心**，
  客户端现在不必自己裁剪。
- **`pasm_status` 增加 `engine_backend`**：如实申报当前跑的是哪套引擎
  （此前不可见 → "到底用的 V1 还是 V2"只能靠猜，属于隐性缺口）。

### 验证

- `pasm-mcp-server --selftest`：**19/19 全绿**（V2 默认下）。
- 基座 `pasm-skills selftest`：通过。

### 兼容性

- 行为变化：默认引擎从 V1 变 V2。语义检索 / 焦点 / 遗忘等认知层能力不变
  （认知层在基座侧，与后端解耦）；V2 的记忆与情绪状态现在会落盘。
- 需要 v1 行为的客户端：设 `PASM_BACKEND=v1`。

## [0.2.1] — 2026-09-29

### 新增

- **`PASM2=1` 实验开关**：`CognitiveBridge.get()` 建 agent 时，经基座
  `create_backend()` 选用 pasm2 V2 认知后端；未设该环境变量时**逐字节不变**走原路径
  （pasm2 未安装或构造失败 → 如实回退 V1）。依赖 `pasm-skills>=0.6.3`（含探测工厂）。

## [0.2.0] — 2026-09-15

**通用化 + 认知能力接入**：从"能挂进某一个客户端"升级为"任何 MCP 客户端都能挂"，
并把基座 0.5.0 的认知能力层接进来。

### 新增

- **3 个新工具**（共 13 个）
  - `pasm_semantic` 语义检索 + 可解释打分（融合分 / 语义分 / 记忆保留度 / 被唤起次数），
    并回显查询被扩展成了哪些同义说法
  - `pasm_focus` 焦点栈：压入/查看"现在在聊什么"，给后续检索加权
  - `pasm_consolidate` 记忆巩固（睡眠回放），默认只出建议，`apply=true` 才执行
- **认知能力自动接入**：依赖 `pasm-skills>=0.5.0` 时，`pasm_recall` / `pasm_context` /
  `pasm_observe` 自动走认知中枢（语义检索 + 遗忘加权 + 焦点 + 同步索引），
  并在 `pasm_status` 里如实报告当前向量后端。**装不上也不报错**，退回字面匹配
- **主流客户端配置示例**：Cursor / Claude Desktop / VS Code(Copilot) / 通用 stdio
- `MANIFEST.in`，`dist` 打包就绪（`python -m build`）

### 修复

- **打包元数据版本号错误**：`pyproject.toml` 的 `version` 还是 `0.1.0`，而代码、README、
  CHANGELOG 都已是 `0.2.0` —— 真打包出来会得到 `pasm_mcp_server-0.1.0-py3-none-any.whl`，
  发到 PyPI 就是"用 0.1.0 的名义发布 0.2.0 的内容"，且与 `__version__` 自相矛盾。
  已对齐为 `0.2.0`。
- **`pyproject` 的 `description` 残留特定产品名**（此前清理漏了这一处，而它会被写进
  PyPI 元数据公开可见）→ 改为通用表述"任意支持 MCP 的客户端"。

### 变更

- `pasm_status` 增加 `cognition` 段：向量后端名、索引条数、焦点、归档、记忆强度分布
- `pasm_context` 增加 `cognition`（当前检索模式）与 `focus`（焦点提示词）字段
- 依赖提升到 `pasm-skills>=0.5.0`；新增可选依赖组 `embed`（本地语义向量）
- 文档与示例去掉对特定产品的依赖，改为通用接入说明
- 日志可静默：宿主客户端若把 stderr 也收进自身日志，设 `PASM_MCP_QUIET=1` 即可
  （工具失败信息仍通过 `isError` 内容回给模型，不影响纠错）
- 补齐六仓同频的生态索引（此前五仓都有、本仓漏了）
- README 自检项数由「10 项」更正为实际的「16 项」（新增 3 个工具后已不止 10）

### 验证

- `pasm-mcp-server --selftest`：通过（16 项）
- `python examples/stdio_client_demo.py`：端到端通过

## [0.1.0] — 2026-09-15

首个版本：**把 PASM 认知内核以 MCP 标准协议暴露出去**。

这是 PASM 生态「分发层」的落地 —— 不改任何外部产品一行代码，
就能让支持 MCP 的 Agent（桌面 AI 客户端 / IDE 插件 / 自研）用上
PASM 的长期记忆、情绪状态与行为倾向。

### 新增

- **stdio MCP 服务器**（`pasm_mcp_server.server`）
  - 纯标准库实现，不依赖官方 MCP SDK，冷启动快
  - 支持 `initialize`（版本协商）、`ping`、`tools/list`、`tools/call`、
    `notifications/*`、`shutdown`
  - 协议版本协商：客户端版本在支持列表内则回显，否则回默认版本
  - 版本支持：`2024-11-05` / `2025-03-26` / `2025-06-18` / `2026-07-28`
- **10 个 MCP 工具**（`pasm_mcp_server.tools`）
  - `pasm_context` 认知上下文（接进提示词的主入口，只读）
  - `pasm_recall` / `pasm_observe` 记忆检索与写入
  - `pasm_feel` 情绪输入
  - `pasm_act` / `pasm_feedback` 动作选择与反馈塑形
  - `pasm_chat` 完整认知回路
  - `pasm_persona` / `pasm_status` / `pasm_save` 人格与运维
- **PASM 认知桥**（`pasm_mcp_server.bridge`）
  - 按 `agent_id` 管理 `BaseAgent` 实例，同 id 跨调用共享认知状态
  - 多智能体隔离，各自落盘到 `~/.pasm-mcp/<agent_id>/`
  - 档位透明：`light` / `core` / `bionic` 如实标注，不隐藏降级
- **工具与示例**
  - `pasm-mcp-server --selftest` 本地自检（10 项）
  - `examples/stdio_client_demo.py` 模拟客户端的端到端冒烟测试
  - `examples/mcp_generic.json` 通用 stdio 客户端配置
  - `examples/mcp_cursor.json` / `mcp_claude_desktop.json` / `mcp_vscode.json`

### 设计决定

- 依赖**公开的** `pasm-skills>=0.4.4`，不依赖私有 PASM 核心：
  没装核心跑 `light` 档，装了自动升级。
- 不内置 LLM：回复走模板渲染。语言生成交给客户端自己的模型，
  PASM 只负责记忆 / 情绪 / 倾向。

### 验证

- `pasm-mcp-server --selftest`：10/10 通过
- `python examples/stdio_client_demo.py`：10/10 通过（本机 tier=light）
