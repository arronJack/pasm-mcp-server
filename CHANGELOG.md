# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] — 2026-09-15

首个版本：**把 PASM 认知内核以 MCP 标准协议暴露出去**。

这是 PASM 生态「路线 A」的落地 —— 不改任何外部产品一行代码，
就能让支持 MCP 的 Agent（BaiLongma / Claude Desktop / Cursor / 自研）用上
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
  - `examples/bailongma_mcp_servers.json` BaiLongma 接入配置
  - `examples/generic_mcp_client.json` 通用客户端配置

### 设计决定

- 依赖**公开的** `pasm-skills>=0.4.4`，不依赖私有 PASM 核心：
  没装核心跑 `light` 档，装了自动升级。
- 不内置 LLM：回复走模板渲染。语言生成交给客户端自己的模型，
  PASM 只负责记忆 / 情绪 / 倾向。

### 验证

- `pasm-mcp-server --selftest`：10/10 通过
- `python examples/stdio_client_demo.py`：10/10 通过（本机 tier=light）
