"""stdio MCP 服务器主循环。

为什么不用官方 `mcp` SDK
------------------------
官方 Python SDK 会拉进 pydantic / starlette / anyio 一串依赖，冷启动明显变慢，
而 stdio server 是**每个客户端每次会话都要拉起**的进程 —— 启动开销会被放大。
stdio 上的 MCP 就是「换行分隔的 JSON-RPC 2.0」，本文件用标准库实现全部必需方法
（initialize / ping / tools/list / tools/call / notifications），零第三方依赖。

三条硬约束（踩过就知道）
------------------------
1. **stdout 只能有 JSON-RPC**。任何 print / traceback 都必须走 stderr，
   否则客户端解析失败，且报错信息极其难查（表现为"server 无响应"）。
2. **每行一条完整 JSON**，写完立刻 flush —— stdio 是流式的，不 flush 客户端会一直等。
3. **Windows 下用 buffer 读写**，避免系统把 \\n 自动转成 \\r\\n 破坏协议。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from . import protocol as P
from .bridge import CognitiveBridge
from .tools import call_tool, list_tools


def _log(msg: str) -> None:
    """日志一律走 stderr —— stdout 是协议通道，不能污染。"""
    print("[pasm-mcp] %s" % msg, file=sys.stderr, flush=True)


def _write(out, obj: Dict[str, Any]) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    out.write(data)
    out.flush()


def handle_message(msg: Dict[str, Any], bridge: CognitiveBridge) -> Optional[Dict[str, Any]]:
    """处理一条 JSON-RPC 消息。返回 None 表示无需回复（通知类）。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return P.error_response(msg.get("id") if isinstance(msg, dict) else None,
                                P.INVALID_REQUEST, "Invalid Request: jsonrpc must be '2.0'")

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # 通知类：无 id，不回复
    if method == "notifications/initialized":
        return None
    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    if method == "initialize":
        client_version = (params or {}).get("protocolVersion")
        return P.result_response(req_id, P.initialize_result(client_version))

    if method == "ping":
        return P.result_response(req_id, {})

    if method == "tools/list":
        return P.result_response(req_id, {"tools": list_tools()})

    if method == "tools/call":
        name = (params or {}).get("name")
        args = (params or {}).get("arguments") or {}
        try:
            result = call_tool(name, args, bridge)
        except KeyError:
            # 未知工具：按规范是协议错误，不是工具执行错误
            return P.error_response(req_id, P.INVALID_PARAMS,
                                    "Unknown tool: %s" % name)
        except Exception as ex:  # noqa: BLE001
            # 工具执行失败：用 isError 内容返回，让大模型看得懂并自行纠错
            _log("tool %s failed: %s" % (name, ex))
            return P.result_response(req_id, {
                "content": [{"type": "text", "text": "PASM 工具 %s 执行失败：%s" % (name, ex)}],
                "isError": True,
            })
        text = json.dumps(result, ensure_ascii=False, indent=2)
        payload: Dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
        # 2025-06-18+ 的客户端支持结构化结果，老客户端会忽略这个字段。
        payload["structuredContent"] = result
        return P.result_response(req_id, payload)

    if method == "shutdown":
        bridge.save_all()
        return P.result_response(req_id, {})

    return P.error_response(req_id, P.METHOD_NOT_FOUND,
                            "Method not found: %s" % method)


def serve(bridge: Optional[CognitiveBridge] = None) -> int:
    """跑 stdio 主循环，直到 stdin 关闭。"""
    bridge = bridge or CognitiveBridge()
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    _log("starting (persist=%s)" % bridge.persist_root)
    try:
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                _write(out, P.error_response(None, P.PARSE_ERROR, "Parse error"))
                continue
            resp = handle_message(msg, bridge)
            if resp is not None:
                _write(out, resp)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        # 客户端断开时把状态落盘 —— 记忆不该因为退出而丢
        saved = bridge.save_all()
        if saved:
            _log("saved on exit: %s" % ", ".join(saved))
    return 0


def selftest() -> int:
    """本地自检：不起 stdio，直接把协议与工具跑一遍。"""
    import tempfile
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print("  %s %s" % ("v" if cond else "x", msg))
        if not cond:
            ok = False

    print("pasm-mcp-server selftest v%s" % P.SERVER_VERSION)
    with tempfile.TemporaryDirectory() as td:
        bridge = CognitiveBridge(persist_root=td)

        # initialize
        r = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}}, bridge)
        check(r["result"]["protocolVersion"] == "2024-11-05", "版本协商回显客户端版本")
        check(r["result"]["serverInfo"]["name"] == P.SERVER_NAME, "serverInfo 正确")

        # tools/list
        r = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, bridge)
        names = [t["name"] for t in r["result"]["tools"]]
        check(len(names) >= 10, "tools/list 返回 %d 个工具" % len(names))
        check("fn" not in r["result"]["tools"][0], "对外清单不含内部 fn 字段")

        # tools/call: observe
        r = handle_message(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "pasm_observe",
                        "arguments": {"title": "用户叫小志", "brief": "他在做 PASM",
                                      "tags": ["姓名"], "salience": 5}}}, bridge)
        check(r["result"]["isError"] is False, "pasm_observe 写入成功")

        # tools/call: recall（应命中刚写的记忆）
        r = handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "pasm_recall", "arguments": {"query": "小志"}}}, bridge)
        hits = r["result"]["structuredContent"]["hits"]
        check(len(hits) >= 1, "pasm_recall 能检索到刚写入的记忆")

        # tools/call: context
        r = handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "pasm_context", "arguments": {"query": "姓名"}}}, bridge)
        ctx = r["result"]["structuredContent"]
        check("mood" in ctx and "recalled" in ctx, "pasm_context 返回情绪与记忆")

        # tools/call: feedback
        r = handle_message(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "pasm_feedback",
                        "arguments": {"kind": "praise", "action": "teach"}}}, bridge)
        w = r["result"]["structuredContent"]["weights"]
        check("teach" in w, "pasm_feedback 作用于指定动作")

        # tools/call: 语义检索（换说法命中：存的是"用户叫小志"，问"我叫什么名字"）
        r = handle_message(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "pasm_semantic", "arguments": {"query": "我叫什么名字"}}}, bridge)
        sem = r["result"].get("structuredContent") or {}
        check(r["result"]["isError"] is False,
              "pasm_semantic 可执行（mode=%s）" % sem.get("mode", "?"))
        if sem.get("mode") == "semantic":
            check(bool(sem.get("hits")), "语义检索：换说法也能命中")
            check("score" in (sem.get("hits") or [{}])[0], "语义检索给出可解释打分")

        # tools/call: 焦点栈
        r = handle_message(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
             "params": {"name": "pasm_focus",
                        "arguments": {"topic": "身份信息", "entities": ["小志"]}}}, bridge)
        check(r["result"]["isError"] is False, "pasm_focus 可压入话题")

        # tools/call: 巩固（默认只出建议，不落盘）
        r = handle_message(
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
             "params": {"name": "pasm_consolidate", "arguments": {}}}, bridge)
        con = r["result"].get("structuredContent") or {}
        check(r["result"]["isError"] is False and con.get("applied") is False,
              "pasm_consolidate 默认只出建议（不落盘）")

        # 状态里能看到认知层
        r = handle_message(
            {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
             "params": {"name": "pasm_status", "arguments": {}}}, bridge)
        st = r["result"].get("structuredContent") or {}
        check("cognition" in st, "pasm_status 报告认知层状态")

        # 未知工具 → 协议错误
        r = handle_message(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "nope", "arguments": {}}}, bridge)
        check("error" in r and r["error"]["code"] == P.INVALID_PARAMS, "未知工具返回协议错误")

        # 工具内部报错 → isError 内容
        r = handle_message(
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
             "params": {"name": "pasm_observe", "arguments": {}}}, bridge)
        check(r["result"]["isError"] is True, "参数缺失返回 isError 内容")

        # 通知类不回复
        check(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"},
                             bridge) is None, "通知类消息不回复")

        # 落盘
        saved = bridge.save_all()
        check(len(saved) >= 1, "状态可落盘")

    print("pasm-mcp-server selftest:", "通过" if ok else "失败")
    return 0 if ok else 1


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pasm-mcp-server",
        description="PASM 认知内核的 MCP 服务器（stdio）")
    ap.add_argument("--persist-dir", default=None,
                    help="状态落盘根目录，默认 ~/.pasm-mcp")
    ap.add_argument("--selftest", action="store_true",
                    help="本地自检（不起 stdio），用于验证安装是否可用")
    ap.add_argument("--version", action="version",
                    version="%(prog)s " + P.SERVER_VERSION)
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    return serve(CognitiveBridge(persist_root=args.persist_dir))


if __name__ == "__main__":
    raise SystemExit(main())
