"""pasm-mcp-server —— 把 PASM 认知内核暴露成标准 MCP 工具。

PASM 的核心资产是**长期记忆、连续情绪、被反馈塑形的行为倾向** ——
这些恰好是大模型原生缺失的。本包不提供"又一个聊天模型"，
而是做一个**认知器官**：任何支持 MCP 的客户端（桌面 AI 客户端、IDE 插件、自建 Agent、
Cursor、自研 Agent）都能把它挂上去，让自己的模型获得跨会话的认知连续性。

三分钟上手
----------

    pip install pasm-mcp-server
    pasm-mcp-server --selftest          # 先自检，确认安装可用

然后在客户端里注册一个 stdio server：

    command: python
    args:    ["-m", "pasm_mcp_server"]

最常用的是 `pasm_context`：它返回"此刻该记得什么 + 情绪如何 + 倾向做什么"，
客户端把它拼进自己的提示词，就得到了一个**有记忆、有情绪、会成长**的智能体。
"""
from __future__ import annotations

__version__ = "0.3.1"

__all__ = ["__version__"]
