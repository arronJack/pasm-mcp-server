#!/usr/bin/env python3
"""stdio 端到端冒烟测试 —— 模拟一个真实的 MCP 客户端。

它做的事和 BaiLongma / Claude Desktop 完全一样：
1. 以子进程方式拉起 server（stdio 传输）
2. 发 `initialize` 握手
3. 发 `notifications/initialized`
4. 发 `tools/list` 发现工具
5. 连发几个 `tools/call`，验证 PASM 的认知链路真的通了

跑法（在仓库根目录）：

    python examples/stdio_client_demo.py

如果 pasm-skills 没装到当前解释器，脚本会自动把兄弟目录 `../pasm-skills`
加进 PYTHONPATH（本地开发用；正式部署请 `pip install pasm-skills`）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ensure_skills_on_path() -> None:
    """本地开发便利：没装 pasm-skills 时退回到兄弟仓。"""
    try:
        import pasm_skills  # noqa: F401
        return
    except ImportError:
        pass
    sibling = ROOT.parent / "pasm-skills"
    if (sibling / "pasm_skills").exists():
        os.environ["PYTHONPATH"] = (
            str(sibling) + os.pathsep + os.environ.get("PYTHONPATH", "")
        )


class Client:
    """极简 MCP stdio 客户端。"""

    def __init__(self, proc: subprocess.Popen):
        self.p = proc
        self._id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        self._id += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if not notify:
            msg["id"] = self._id
        if params is not None:
            msg["params"] = params
        line = json.dumps(msg, ensure_ascii=False)
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return self._id

    def recv(self):
        """读一行响应。stderr 的日志不会混进来（它们是分开的管道）。"""
        line = self.p.stdout.readline()
        if not line:
            return None
        return json.loads(line)


def show(title: str, obj) -> None:
    print("\n=== %s ===" % title)
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:1200])


def main() -> int:
    _ensure_skills_on_path()
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "pasm_mcp_server"],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    c = Client(proc)
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print("  %s %s" % ("v" if cond else "x", msg))
        if not cond:
            ok = False

    try:
        # 1. 握手
        c.send("initialize", {
            "protocolVersion": "2025-03-26",
            "clientInfo": {"name": "demo-client", "version": "1.0.0"},
        })
        r = c.recv()
        show("initialize", r)
        check(r and r["result"]["protocolVersion"] == "2025-03-26", "握手成功，版本协商正确")

        # 2. initialized 通知（不应有响应）
        c.send("notifications/initialized", {}, notify=True)

        # 3. 发现工具
        c.send("tools/list")
        r = c.recv()
        tools = r["result"]["tools"]
        names = [t["name"] for t in tools]
        print("\n=== tools/list ===\n%s" % ", ".join(names))
        check(len(names) == 10, "暴露 10 个 PASM 工具")

        # 4. 写记忆
        c.send("tools/call", {"name": "pasm_observe", "arguments": {
            "title": "用户在做 PASM 认知引擎",
            "brief": "他希望 PASM 能通过 MCP 被别的 Agent 调用",
            "tags": ["项目", "目标"], "salience": 5, "category": "项目",
        }})
        r = c.recv()
        show("pasm_observe", r["result"]["structuredContent"])
        check(r["result"]["isError"] is False, "记忆写入成功")

        # 5. 情绪
        c.send("tools/call", {"name": "pasm_feel",
                              "arguments": {"event": "MCP 接通了", "valence": 0.8}})
        r = c.recv()
        sc = r["result"]["structuredContent"]
        show("pasm_feel", sc)
        check(sc["mood"] > 0, "情绪被正向事件推高（mood=%s）" % sc["mood"])

        # 6. 认知上下文 —— 这是接进大模型提示词的主入口
        c.send("tools/call", {"name": "pasm_context",
                              "arguments": {"query": "用户在做什么项目", "k": 3}})
        r = c.recv()
        ctx = r["result"]["structuredContent"]
        show("pasm_context", ctx)
        check(len(ctx["recalled"]) >= 1, "检索到相关记忆（%d 条）" % len(ctx["recalled"]))
        check("action_pool" in ctx, "返回可用动作池")

        # 7. 反馈塑形
        c.send("tools/call", {"name": "pasm_feedback",
                              "arguments": {"kind": "praise", "action": "teach"}})
        r = c.recv()
        show("pasm_feedback", r["result"]["structuredContent"])

        # 8. 状态
        c.send("tools/call", {"name": "pasm_status", "arguments": {}})
        r = c.recv()
        st = r["result"]["structuredContent"]
        show("pasm_status", st)
        check(st["tier"] in ("light", "core", "bionic"), "档位标注：%s" % st["tier"])
        check(st["total_interactions"] >= 1, "交互计数正常")

        # 9. 未知工具应返回协议错误
        c.send("tools/call", {"name": "not_a_tool", "arguments": {}})
        r = c.recv()
        check("error" in r, "未知工具返回 JSON-RPC 错误")

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        err = proc.stderr.read() if proc.stderr else ""

    print("\n--- server stderr（日志，正常应为空或只有启动/退出记录）---")
    print(err.strip() or "(空)")
    print("\n冒烟测试：%s" % ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
