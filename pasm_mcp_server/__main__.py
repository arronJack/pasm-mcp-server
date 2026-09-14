"""`python -m pasm_mcp_server` 入口。

MCP 客户端注册时推荐用这种形式（`args: ["-m", "pasm_mcp_server"]`），
因为它不依赖脚本路径 —— 换虚拟环境、换机器都不会失效。
"""
from __future__ import annotations

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
