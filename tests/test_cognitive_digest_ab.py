# -*- coding: utf-8 -*-
"""A/B 对照：认知摘要下沉进 pasm_context.brief 的验证（阶段 12 / 方案 A）。

验证四件事，任一失败 exit!=0：
  1. 运行时 cognitive_digest 与 PASM 仓 analysis 版对黄金向量逐字一致（防漂移）。
  2. 真实 MCP bridge：brief 默认指向 digest，digest=false 回滚 legacy，字段并存。
  3. 信息保真：digest 比 legacy 多带「人格 + 显著度记忆 + 情绪语义」，且 prio0 不丢。
  4. 省 token：digest 的 tok 显著小于整包 JSON。

不依赖 LLM / 网络（除本地 Ollama 语义检索）；环境对齐 mcp.json。
运行：
    C:/Python312/python.exe tests/test_cognitive_digest_ab.py
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, r"E:/AI/pasm/code/PASM")  # 只为 import analysis 版做一致性比对
sys.path.insert(0, r"E:/AI/pasm/code/pasm-skills")

os.environ.setdefault("PASM2", "1")
os.environ.setdefault("PASM_EMBED_URL", "http://localhost:11434/v1/embeddings")
os.environ.setdefault("PASM_EMBED_MODEL", "nomic-embed-text")
for _k in ("NO_PROXY", "no_proxy"):
    _old = os.environ.get(_k, "")
    os.environ[_k] = (_old + "," if _old else "") + "localhost,127.0.0.1,::1"

from pasm_mcp_server.cognitive_digest import cognitive_digest, consistency_ctx  # noqa: E402
from pasm_mcp_server.bridge import CognitiveBridge  # noqa: E402
from pasm_mcp_server.server import handle_message  # noqa: E402

DB = os.path.join(HERE, "_ab_persist")

FACTS = [
    ("姓名", "我叫小志，以后叫我小志", ["姓名", "关键事实"]),
    ("猫的禁忌", "我家猫对鸡肉过敏，千万别喂鸡肉", ["禁忌", "猫", "关键事实"]),
    ("验证偏好", "验证必须实跑，不接受只看日志", ["偏好", "关键事实"]),
    ("项目", "当前主线是 PASM v2 引擎", ["项目", "PASM"]),
]


def call(b, name, args):
    r = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}}, b)
    return r["result"].get("structuredContent", {})


def main():
    results = {}

    # 1) 两份实现一致性（analysis 版在 PASM 仓，可能不存在则跳过并标注）
    try:
        sys.path.insert(0, r"E:/AI/pasm/code/PASM/analysis/tools")
        from phase12_cognitive_digest import cognitive_digest as analysis_digest  # noqa: E402
        golden = consistency_ctx()
        for budget in (40, 80, 220, 500):
            a = analysis_digest(golden, max_chars=budget)
            r = cognitive_digest(golden, max_chars=budget)
            assert a == r, ("digest 实现漂移", budget, a, r)
        results["consistency_analysis_vs_runtime"] = "PASS"
    except ImportError as e:
        results["consistency_analysis_vs_runtime"] = "SKIP(%s)" % e

    # 2~4) 真实 bridge
    shutil.rmtree(DB, ignore_errors=True)
    b = CognitiveBridge(persist_root=DB)
    for title, brief, tags in FACTS:
        call(b, "pasm_observe", {"agent_id": "ab", "title": title,
                                 "brief": brief, "tags": tags, "salience": 5})
    call(b, "pasm_save", {"agent_id": "ab"})
    ctx = call(b, "pasm_context", {"agent_id": "ab", "query": "我叫什么 猫 验证", "k": 6})
    ctx_legacy = call(b, "pasm_context", {"agent_id": "ab",
                                          "query": "我叫什么 猫 验证", "k": 6,
                                          "digest": False})

    recall_n = len(ctx.get("recalled") or [])
    results["recalled_count"] = recall_n
    results["cognition"] = ctx.get("cognition")
    preflight_ok = recall_n >= 3 and "memory" in (ctx.get("digest_meta") or {}).get("kept", [])
    results["preflight"] = "PASS" if preflight_ok else "FAIL"
    if not preflight_ok:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        raise SystemExit("PREFLIGHT FAIL: 召回 %d 条 / cognition=%s —— 语义后端不可用，拒绝假绿"
                         % (recall_n, ctx.get("cognition")))

    # 2) brief 字段默认=digest，可回滚
    results["brief_default_is_digest"] = (ctx["brief"] == ctx["brief_digest"]
                                          and ctx["brief_mode"] == "digest")
    results["brief_rollback_to_legacy"] = (ctx_legacy["brief"] == ctx_legacy["brief_legacy"]
                                           and ctx_legacy["brief_mode"] == "legacy")
    results["legacy_preserved"] = ("brief_legacy" in ctx and "brief_digest" in ctx)
    assert results["brief_default_is_digest"], "brief 默认未指向 digest"
    assert results["brief_rollback_to_legacy"], "digest=false 未回滚到 legacy"
    assert results["legacy_preserved"], "旧字段未保留"

    # 3) 信息保真：digest 比 legacy 多人格/显著度记忆/情绪语义
    dtxt = ctx["brief_digest"]
    kept = ctx["digest_meta"]["kept"]
    results["digest_has_persona"] = "persona" in kept and "性格" in dtxt
    results["digest_has_memory"] = "memory" in kept and "记得" in dtxt
    results["digest_has_mood_semantics"] = "mood" in kept
    results["digest_keeps_prio0"] = ("identity" in kept and "mood" in kept)
    assert all(results[k] for k in ("digest_has_persona", "digest_has_memory",
                                    "digest_has_mood_semantics", "digest_keeps_prio0")), \
        ("信息保真失败", results, dtxt)

    # 4) 省 token：摘要 << 整包
    tok = 0.67
    full_tok = round(len(json.dumps(ctx, ensure_ascii=False)) * tok)
    digest_tok = ctx["digest_meta"]["approx_tok"]
    legacy_tok = round(len(ctx["brief_legacy"]) * tok)
    results["tokens"] = {"full": full_tok, "legacy": legacy_tok, "digest": digest_tok}
    results["saving_vs_full_pct"] = round(100 * (1 - digest_tok / full_tok), 1)
    assert digest_tok < legacy_tok < full_tok, ("省 token 断言失败", results["tokens"])

    results["verdict"] = "ALL PASS"
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
