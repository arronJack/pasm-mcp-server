"""MCP 协议常量、版本协商与 JSON-RPC 错误码。

只依赖标准库 —— 本包刻意**不依赖**官方 `mcp` Python SDK：
stdio 上的 MCP 就是「换行分隔的 JSON-RPC 2.0」，自己实现可以做到零依赖、
启动快（<100ms），也让本包能直接被任意语言的客户端（Node / Python / Electron 外壳）拉起。

版本协商策略（重要）
--------------------
客户端会在 `initialize` 里带上自己的 `protocolVersion`。
- 客户端版本在我们支持列表里 → **原样回显**（最安全，双方都认这个版本）；
- 不在列表里 → 回我们默认支持的最新版本，并在 stderr 记一条警告，
  由客户端决定是否继续（规范允许客户端此时断开）。

不要把服务端版本写死成一个常量然后无视客户端 —— 那样遇到只认旧版的客户端
（如部分 2024 年实现的 SDK）会直接握手失败。
"""
from __future__ import annotations

#: 本服务端支持的协议版本（按时间升序）。
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2026-07-28",
)

#: 客户端没带版本 / 带了不认识的版本时，回这个。
#: 选 2025-03-26 是因为它在 2025-2026 的客户端里覆盖最广。
DEFAULT_PROTOCOL_VERSION = "2025-03-26"

SERVER_NAME = "pasm-mcp-server"
SERVER_VERSION = "0.3.3"

#: 服务端能力声明。只声明 tools —— 不声明就是不支持，别虚报。
CAPABILITIES = {"tools": {}}

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def negotiate(client_version: str | None) -> str:
    """版本协商：客户端认得的就回显，否则回默认版本。"""
    if client_version and client_version in SUPPORTED_PROTOCOL_VERSIONS:
        return client_version
    return DEFAULT_PROTOCOL_VERSION


def initialize_result(client_version: str | None) -> dict:
    """构造 `initialize` 的响应 result。"""
    return {
        "protocolVersion": negotiate(client_version),
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": CAPABILITIES,
        # 2025-06-18 起部分客户端会读这个字段做能力提示，给了无害。
        "instructions": (
            "PASM 认知内核：提供长期记忆、情绪状态与动作倾向。"
            "典型用法是先 pasm_context 取认知上下文，再据此回复；"
            "有值得记住的事就 pasm_observe 写进去；被夸/被凶就用 pasm_feedback 塑形。"
        ),
    }


def error_response(req_id, code: int, message: str, data=None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def result_response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}
