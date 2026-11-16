# -*- coding: utf-8 -*-
"""认知摘要生成器（运行时版本）：把 pasm_context 的认知状态压成固定预算文本。

来源与纪律
----------
移植自 PASM 仓 ``analysis/tools/phase12_cognitive_digest.py``（2026-11-16 验证通过：
真实 MCP bridge 整包 725 tok → 摘要 38~80 tok，省 89%~95%，三条反例对照全 PASS）。
本模块只依赖标准库与 ctx 里的普通 dict 字段，**不 import pasm2 / pasm-skills**，
因此 MCP 运行时自包含、零侵入认知引擎。

为什么运行时要有一份：analysis 工具在各仓之外，MCP server 不能依赖它。两份实现
用 ``consistency_ctx()`` 的黄金向量互相校验（``--selfcheck`` / A-B 脚本都断言逐字一致），
防止漂移。

设计（可证伪，沿用桌面端坑 6~9 口径）
--------------------------------------
* 块 = (优先级, 名称, 文本)；超预算**整块丢弃**，绝不腰斩半句（坑 9）。
* prio 0 永不丢：身份锚 + 情绪；prio 10 人格；prio 20 显著度记忆；prio 99 提示语。
* 记忆按 salience 排序而非召回顺序——显著度才是「关键事实」的信号。
* 诚实降级：无 mood 字段不编造情绪；空 ctx 输出空摘要。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

TOK_PER_CHAR = 0.67  # 仓库既有口径 desktop/llm_gateway.py:151（中文≈0.67 tok/字）

__all__ = ["cognitive_digest", "consistency_ctx", "selfcheck"]


def _mood_word(v: float) -> str:
    if v >= 0.5:
        return "心情很好"
    if v >= 0.15:
        return "心情不错"
    if v <= -0.5:
        return "情绪低落"
    if v <= -0.15:
        return "有点低落"
    return "情绪平稳"


def _temper_word(v: float) -> str:
    try:
        t = float(v)
    except (TypeError, ValueError):
        return ""
    if t >= 0.65:
        return "直率"
    if t <= 0.35:
        return "温和"
    return "平和"


def cognitive_digest(ctx: Dict[str, Any], max_chars: int = 220) -> Dict[str, Any]:
    """从 pasm_context 返回体生成固定预算的认知摘要（只读 ctx）。"""
    ctx = ctx or {}
    blocks: List[Tuple[int, int, str, str]] = []  # (prio, idx, name, text)
    idx = 0

    # prio 0 —— 身份锚 + 情绪（永不丢）
    persona = ctx.get("persona") or {}
    name = str(persona.get("name") or "")
    role = str(persona.get("role") or "")
    anchor = ("我是%s" % name) if name else ""
    if role and role not in anchor:
        anchor += ("·%s" % role) if anchor else role
    if anchor:
        blocks.append((0, idx, "identity", anchor)); idx += 1
    if "mood" in ctx and ctx.get("mood") is not None:
        try:
            mood = float(ctx["mood"])
            blocks.append((0, idx, "mood", "%s(%+.2f)" % (_mood_word(mood), mood)))
            idx += 1
        except (TypeError, ValueError):
            pass

    # prio 10 —— 人格画像
    tone = str(persona.get("tone") or "")
    temper = _temper_word(persona.get("temper"))
    persona_bits = [b for b in (tone, temper) if b]
    if persona_bits:
        blocks.append((10, idx, "persona", "性格：" + "、".join(persona_bits))); idx += 1

    # prio 20 —— 记忆：按 salience 排序，标题去重
    recalled = list(ctx.get("recalled") or [])

    def _sal(f: Dict[str, Any]) -> float:
        try:
            return float(f.get("salience", 1))
        except (TypeError, ValueError):
            return 1.0

    ranked = sorted(enumerate(recalled), key=lambda p: (-_sal(p[1]), p[0]))
    titles: List[str] = []
    for _, f in ranked:
        t = str(f.get("title") or "")
        if t and t not in titles:
            titles.append(t)
    if titles:
        blocks.append((20, idx, "memory", "记得：" + "、".join(titles))); idx += 1

    # prio 30 —— 当前焦点：只取主题，剥掉与 memory 重复的「（涉及：…）」
    focus = str(ctx.get("focus") or "").strip()
    if focus:
        first = focus.split("｜")[0].strip()
        topic = first.split("（")[0].strip()
        if topic.startswith("当前焦点："):
            topic = topic[len("当前焦点："):].strip()
        if topic and topic not in titles:
            blocks.append((30, idx, "focus", "关注：" + topic)); idx += 1

    # prio 99 —— 提示语（最容易被丢）
    hint = str(ctx.get("hint") or "").strip()
    if hint:
        blocks.append((99, idx, "hint", hint)); idx += 1

    # ---- 按 (prio, idx) 升序装；超预算整块丢，不腰斩；prio0 无条件保 ----
    blocks.sort(key=lambda b: (b[0], b[1]))
    kept: List[str] = []
    dropped: List[str] = []
    parts: List[str] = []
    used = 0
    for prio, _, name, text in blocks:
        cost = len(text) + (1 if parts else 0)
        if used + cost <= max_chars or prio == 0:
            parts.append(text); used += cost; kept.append(name)
        else:
            dropped.append(name)
    digest = "｜".join(parts)
    return {"text": digest, "chars": len(digest),
            "approx_tok": round(len(digest) * TOK_PER_CHAR),
            "dropped": dropped, "kept": kept}


def consistency_ctx() -> Dict[str, Any]:
    """黄金向量：analysis 版与运行时版必须对本向量逐字一致。"""
    return {
        "persona": {"name": "小墨", "role": "认知陪伴", "tone": "温和、简洁", "temper": 0.2},
        "mood": -0.62,
        "focus": "验证偏好（涉及：偏好）",
        "recalled": [
            {"title": "低显著闲聊", "salience": 1},
            {"title": "姓名", "salience": 5},
            {"title": "鸡肉过敏", "salience": 5},
        ],
        "action_pool": ["greet", "ask"],
        "hint": "把 recalled 里的内容当作'你确实记得的事'写进回复",
    }


def selfcheck() -> str:
    ctx = consistency_ctx()
    big = cognitive_digest(ctx, max_chars=500)
    assert "identity" in big["kept"] and "mood" in big["kept"], big
    assert "persona" in big["kept"] and "memory" in big["kept"], big
    assert "情绪低落" in big["text"] and "温和" in big["text"], big["text"]
    tight = cognitive_digest(ctx, max_chars=40)
    assert "identity" in tight["kept"] and "mood" in tight["kept"], tight
    assert "persona" in tight["kept"], tight
    empty = cognitive_digest({})
    assert empty["text"] == "" and empty["dropped"] == [], empty
    assert cognitive_digest(dict(ctx, mood=0.72))["text"] != \
           cognitive_digest(dict(ctx, mood=-0.72))["text"]
    return ("cognitive_digest(selfcheck) OK: prio0 永不丢 + 显著度排序 "
            "+ 情绪语义 + 人格保留 + 缺字段降级")


if __name__ == "__main__":
    print(selfcheck())
