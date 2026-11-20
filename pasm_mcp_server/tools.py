"""MCP 工具定义与实现。

工具设计原则：**暴露认知，不抢语言**。
PASM 提供客户端大模型没有的东西 —— 跨会话的长期记忆、连续的情绪状态、
被反馈塑形过的行为倾向。至于"这句话该怎么说"，交给客户端自己的模型。

所以最常用的不是 `pasm_chat`（那会把 PASM 当成又一个聊天模型），
而是 `pasm_context`：它把"现在该记得什么、情绪如何、倾向做什么"打包返回，
客户端拿去拼进自己的提示词。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from .bridge import CognitiveBridge, validate_agent_id
from .cognitive_digest import cognitive_digest

# 本地开发逃生口（与 bridge 同款）：PASM_SKILLS_PATH 指向 pasm-skills 仓库根目录
if os.environ.get("PASM_SKILLS_PATH"):
    sys.path.insert(0, os.environ["PASM_SKILLS_PATH"])

# 认知能力层（pasm-skills >= 0.5.0）。装了就自动用上语义检索 / 遗忘 / 巩固 / 焦点；
# 没有也能跑 —— 退回基座的原生 recall，只是没有语义增强。
try:
    from pasm_skills.cognition import enhance as _enhance  # type: ignore
except Exception:  # pragma: no cover
    _enhance = None  # type: ignore


def _agent_id(args: Dict[str, Any]) -> str:
    """统一收口：所有工具都从这里取 agent_id，非法值明确拒绝。

    课题 C 实测：原先只 ``str(args.get(...) or "default")``，
    ``../`` / 绝对路径 / 空白 id 会直接拼进 persist_root 造成越权写。
    """
    return validate_agent_id(args.get("agent_id") or "default")


def _cog(bridge: CognitiveBridge, agent_id: str) -> Tuple[Any, Optional[Any]]:
    """取 (智能体, 认知中枢)。中枢拿不到就返回 None —— 功能降级但不报错。"""
    ag = bridge.get(agent_id)
    if _enhance is None:
        return ag, None
    hub = getattr(ag, "cognition", None)
    if hub is None:
        try:
            hub = _enhance(ag)
        except Exception:
            return ag, None
    return ag, hub


def _compact_brief(ag, facts, cog) -> str:
    """紧凑版上下文（给客户端**直接注入提示词**用，替代整包 JSON）。

    为什么要它：``pasm_context`` 的整个返回体（recalled 全量 brief + persona 全量
    + action_pool + hint）直接塞进提示词实测约 500 tok，而真正影响回话的信息只有
    几十 tok。**省 token 是 PASM 的初心**，所以额外给一份可直接注入的紧凑文本，
    客户端不必自己裁剪（省下的正是重复注入的历史与冗余结构）。
    """
    parts = []
    try:
        parts.append("此刻心情 %+.2f" % float(ag.mood))
    except Exception:
        pass
    titles = "、".join(str(f.get("title") or "") for f in (facts or [])[:3]
                       if f.get("title"))
    if titles:
        parts.append("你记得：%s" % titles)
    try:
        focus = (cog.focus.to_prompt() if cog is not None else "") or ""
    except Exception:
        focus = ""
    if focus.strip():
        parts.append(focus.strip())
    return "｜".join(parts)


def tool_context(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """取认知上下文（只读，不写记忆）。这是**注入提示词**用的一号工具。"""
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    query = str(args.get("query") or "")
    k = int(args.get("k") or 5)
    if cog is not None and query:
        facts = cog.recall(query, k=k)
    else:
        facts = ag.recall(query, k=k) if query else []
    ctx = {
        "agent_id": ag.agent_id,
        "tier": ag.tier,
        "query": query,
        "cognition": (
            "semantic" if cog is not None else
            ("lexical（未装 pasm-skills>=0.5.0 的认知层，检索为字面匹配）")
        ),
        "focus": (cog.focus.to_prompt() if cog is not None else ""),
        "recalled": [
            {
                "title": f.get("title", ""),
                "brief": f.get("brief", ""),
                "tags": list(f.get("tags", [])),
                "category": f.get("cat", f.get("category", "")),
                "salience": f.get("sal", f.get("salience", 1)),
                # 语义模式暴露相对置信度：接近 0 表示该条对本问题是弱命中
                **({"relevance": f.get("relevance")} if cog is not None else {}),
            }
            for f in facts
        ],
        "mood": round(float(ag.mood), 3),
        "persona": dict(ag.persona),
        "growth_stage": ag.state.growth_stage,
        "total_interactions": ag.state.total_interactions,
        "action_pool": ag.action_pool(),
        "hint": (
            "把 recalled 里的内容当作'你确实记得的事'写进回复；"
            "mood 决定语气；action_pool 是当前可选行为。"
        ),
    }
    # ---- 省 token：认知摘要（阶段 12）。保留旧紧凑版供兼容/回滚，宿主零改动即受益。----
    # brief_legacy = 旧 _compact_brief（只带 mood + 3 标题，丢人格/显著度/情绪语义）
    # brief_digest = 新认知摘要（身份+情绪语义+人格+显著度记忆，固定预算整块丢弃）
    # brief        = 默认指向 digest；传 digest=false 可回滚到 legacy。
    legacy = _compact_brief(ag, facts, cog)
    # 默认 80 字档：实测 ≈38 tok，比旧 brief(58 tok) 更省且信息更全（保住
    # 身份/情绪/人格/显著度记忆，只丢给宿主的 hint）；220 字档反而比 legacy 贵，
    # 仅当用户明确要带 hint 时传 digest_chars=220。（阶段12 A/B 对照抓到的坑）
    d = cognitive_digest(ctx, max_chars=int(args.get("digest_chars") or 80))
    digest = d["text"]
    use_digest = str(args.get("digest", "true")).lower() not in ("false", "0", "no")
    ctx.update({
        "brief": digest if use_digest else legacy,
        "brief_legacy": legacy,
        "brief_digest": digest,
        "brief_mode": "digest" if use_digest else "legacy",
        "digest_meta": {"chars": d["chars"], "approx_tok": d["approx_tok"],
                        "kept": d["kept"], "dropped": d["dropped"]},
    })
    return ctx


def tool_recall(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """记忆检索。装了认知层时走**语义检索**（含同义扩展 + 遗忘加权）。"""
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    query = str(args.get("query") or "")
    if not query:
        raise ValueError("query 不能为空")
    k = max(1, min(50, int(args.get("k") or 5)))
    min_rel = float(args.get("min_relevance") or 0.0)
    if cog is not None:
        hits = cog.recall(query, k=k, min_relevance=min_rel)
    else:
        hits = ag.recall(query, k=k)
    return {
        "agent_id": ag.agent_id,
        "query": query,
        "mode": "semantic" if cog is not None else "lexical",
        "count": len(hits),
        "relevance_gate": min_rel if min_rel > 0 else "off",
        "note": ("返回空 = 没有能支撑此问题的记忆，请如实说明而非编造"
                 if min_rel > 0 and not hits else None),
        "hits": [
            {
                "title": f.get("title", ""),
                "brief": f.get("brief", ""),
                "tags": list(f.get("tags", [])),
                "salience": f.get("sal", f.get("salience", 1)),
                # 仅语义模式有：融合分 / 语义分 / 记忆保留度 / 被唤起次数 / 相对置信度
                **({"score": f.get("score"), "semantic": f.get("semantic"),
                    "relevance": f.get("relevance"),
                    "retention": f.get("retention"), "hits": f.get("hits")}
                   if cog is not None else {}),
            }
            for f in hits
        ],
    }


def tool_semantic(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """显式语义检索，并解释每一条为什么被召回（可解释性）。"""
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    query = str(args.get("query") or "")
    if not query:
        raise ValueError("query 不能为空")
    if cog is None:
        return {
            "agent_id": aid, "query": query, "mode": "lexical",
            "note": "未装 pasm-skills>=0.5.0 的认知层，退回字面匹配。",
            "hits": [{"title": f.get("title", ""), "brief": f.get("brief", "")}
                     for f in ag.recall(query, k=int(args.get("k") or 5))],
        }
    k = max(1, min(50, int(args.get("k") or 5)))
    hits = cog.recall(query, k=k,
                      use_focus=bool(args.get("use_focus", True)),
                      use_forgetting=bool(args.get("use_forgetting", True)))
    return {
        "agent_id": aid,
        "query": query,
        "mode": "semantic",
        "backend": getattr(cog.index.backend, "name", "?"),
        "expanded": cog.index.bridge.expand(query)[:8],
        "count": len(hits),
        "hits": [
            {
                "title": h.get("title", ""),
                "brief": h.get("brief", ""),
                "tags": list(h.get("tags", [])),
                "salience": h.get("sal", 1),
                "score": h.get("score"),
                "semantic": h.get("semantic"),
                "retention": h.get("retention"),
                "rehearsals": h.get("hits"),
            }
            for h in hits
        ],
        "hint": (
            "score = 语义×0.62 + 记忆保留度×0.24 + 重要度×0.14 + 焦点加成。"
            "retention 低说明这条很久没被唤起（正在遗忘）。"
        ),
    }


def tool_focus(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """焦点栈：查看或压入"现在在聊什么"。"""
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    if cog is None:
        return {"agent_id": aid, "ok": False,
                "error": "需要 pasm-skills>=0.5.0 的认知层"}
    topic = str(args.get("topic") or "").strip()
    if topic:
        cog.focus.push(
            topic,
            entities=[str(e) for e in (args.get("entities") or [])],
            weight=float(args.get("weight") or 1.0),
        )
    return {
        "agent_id": aid,
        "updated": bool(topic),
        "depth": len(cog.focus),
        "prompt": cog.focus.to_prompt(int(args.get("n") or 3)),
        "stack": cog.focus.snapshot()[:8],
    }


def tool_consolidate(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """记忆巩固（睡眠回放）：把高度相似的重复经历蒸馏成要点。

    ``apply=false``（默认）只给建议，不落盘。
    """
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    if cog is None:
        return {"agent_id": aid, "ok": False,
                "error": "需要 pasm-skills>=0.5.0 的认知层"}
    apply = bool(args.get("apply", False))
    rep = cog.consolidate(apply=apply)
    return {
        "agent_id": aid,
        "applied": apply,
        **rep.as_dict(),
        "hint": ("这是建议，未落盘。想执行请再调一次并传 apply=true。"
                 if not apply else "已写入要点记忆，源条目标记为已合并。"),
    }


def tool_observe(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """写入一条经历（记忆）。"""
    ag = bridge.get(_agent_id(args))
    title = str(args.get("title") or "").strip()
    if not title:
        raise ValueError("title 不能为空")
    sal = int(args.get("salience") or 2)
    sal = max(1, min(5, sal))
    ag, cog = _cog(bridge, _agent_id(args))
    if cog is not None:
        # 走中枢：写记忆 + 同步语义索引 + 更新焦点，一次做完
        cog.observe(
            title=title,
            brief=str(args.get("brief") or ""),
            tags=[str(t) for t in (args.get("tags") or [])],
            salience=sal,
            category=str(args.get("category") or "日常"),
        )
    else:
        ag.observe(
            title=title,
            brief=str(args.get("brief") or ""),
            tags=[str(t) for t in (args.get("tags") or [])],
            salience=sal,
            category=str(args.get("category") or "日常"),
        )
    ag.save()
    # P11-D3（2026-11-13）：本条经历写在 V2 mind 的自传体层，
    # ag.save() 覆盖不到 —— 必须同时 core.save() 落盘 pasm2-state.json，
    # 否则重启后 episodes() 为空、语义索引重建不出来。
    _core = getattr(ag, "_core", None)
    if _core is not None and hasattr(_core, "save"):
        _core.save()
    # P11-D2（2026-11-13）：认知索引（含真语义向量）是 CognitionHub 的
    # sidecar，BaseAgent.save() 不会写它。只调 ag.save() 会让进程重启后
    # episodes_of() 归零、索引重建为空 —— 实测跨重启记忆全部丢失。
    # 不吞异常：落盘失败必须显式报错，不能再"静默丢记忆"。
    if cog is not None:
        cog.save()
    return {
        "agent_id": ag.agent_id,
        "ok": True,
        "title": title,
        "salience": sal,
        "total_interactions": ag.state.total_interactions,
    }


def tool_feel(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """报告一个带情绪效价的事件。"""
    ag = bridge.get(_agent_id(args))
    event = str(args.get("event") or "").strip()
    if not event:
        raise ValueError("event 不能为空")
    valence = float(args.get("valence") or 0.0)
    valence = max(-1.0, min(1.0, valence))
    ag.feel(event, valence)
    ag.save()
    return {
        "agent_id": ag.agent_id,
        "event": event,
        "valence": valence,
        "mood": round(float(ag.mood), 3),
        "emotion_backend": "pasm.modules.emotion" if ag._emo_ok else "fallback",
    }


def tool_act(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """从动作池里按「性格 + 学到的偏好」选一个动作。"""
    ag = bridge.get(_agent_id(args))
    cands = args.get("candidates")
    if cands:
        pool = [str(c) for c in cands if str(c)]
        if not pool:
            raise ValueError("candidates 不能是空数组")
        chosen = _act_with_pool(ag, pool)
    else:
        chosen = ag.act()
    return {
        "agent_id": ag.agent_id,
        "chosen": chosen,
        "pool": list(cands) if cands else ag.action_pool(),
    }


def _act_with_pool(ag, pool: List[str]) -> str:
    """用指定候选池走一次动作选择（复用基座的学习层，不绕过反馈）。"""
    picker = getattr(ag._core, "learn_pick", None)
    if picker is not None:
        try:
            got = picker(pool, base=ag._fallback_weights(pool),
                         persona=ag.persona, stage=ag.state.growth_stage)
            if got in pool:
                return got
        except Exception:
            pass
    import random
    return random.choices(pool, weights=ag._fallback_weights(pool), k=1)[0]


def tool_feedback(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """用户反馈塑形。**强烈建议带 action**，否则长期会让动作分布极端化。"""
    ag = bridge.get(_agent_id(args))
    kind = str(args.get("kind") or "").strip()
    valid = {"praise", "scold", "poke", "hug", "ignore"}
    if kind not in valid:
        raise ValueError("kind 必须是 %s 之一" % ", ".join(sorted(valid)))
    action = args.get("action")
    weights = ag.feedback(kind, action=str(action) if action else None)
    ag.save()
    return {
        "agent_id": ag.agent_id,
        "kind": kind,
        "action": action,
        "weights": {k: round(float(v), 3) for k, v in (weights or {}).items()},
        "warning": (
            None if action else
            "未指定 action：反馈作用在了当前最偏好的动作上，"
            "长期会让行为分布极端化（基座已知特性，建议明确传 action）。"
        ),
    }


def tool_chat(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """走完整认知回路对话一次：检索 → 渲染 → 写入记忆。

    注意：回复是**模板渲染**的，不是 LLM 生成。
    想要自然语言的客户端应该改用 pasm_context + 自己的模型。
    """
    ag = bridge.get(_agent_id(args))
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text 不能为空")
    facts = ag.recall(text, k=3)
    reply = ag.chat(text)
    ag.save()
    return {
        "agent_id": ag.agent_id,
        "reply": reply,
        "cognitive": {
            "recalled": [f.get("title", "") for f in facts],
            "mood": round(float(ag.mood), 3),
            "tier": ag.tier,
            "total_interactions": ag.state.total_interactions,
        },
        "note": "模板渲染，非 LLM 生成；接 LLM 请用 pasm_context。",
    }


def tool_persona(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """查看或（合并式）更新人格。"""
    ag = bridge.get(_agent_id(args))
    patch = args.get("persona")
    if patch:
        if not isinstance(patch, dict):
            raise ValueError("persona 必须是对象")
        ag.set_persona(patch)
        ag.save()
    return {
        "agent_id": ag.agent_id,
        "persona": dict(ag.persona),
        "updated": bool(patch),
    }


def tool_status(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """状态快照：档位、记忆量、情绪、反馈数、认知层状态。"""
    aid = _agent_id(args)
    ag, cog = _cog(bridge, aid)
    snap = ag.summary()
    snap["persist_dir"] = str(ag.persist_dir)
    snap["bridge_root"] = str(bridge.persist_root)
    snap["loaded_agents"] = bridge.agent_ids()
    # 诚实申报：当前到底跑的是哪套认知引擎（V2=pasm2 / V1=核心档 / 轻量档）。
    # 此前这个信息不可见 → 「MCP 实际用 V1 还是 V2」只能靠猜，属于隐性缺口。
    try:
        snap["engine_backend"] = type(getattr(ag, "_core", None)).__name__
    except Exception:
        snap["engine_backend"] = "unknown"
    if cog is not None:
        try:
            snap["cognition"] = {
                "enabled": True,
                "embedding_backend": cog.index.backend.name,
                "indexed": len(cog.index),
                "focus": cog.focus.to_prompt(),
                "focus_depth": len(cog.focus),
                "archive": cog.archive.stats(),
                "memory": cog.curve.decay_report(_episodes_of(cog)),
            }
        except Exception as ex:
            snap["cognition"] = {"enabled": True, "error": str(ex)}
    else:
        snap["cognition"] = {"enabled": False,
                             "hint": "pip install -U 'pasm-skills>=0.5.0' 可启用"}
    return snap


def _episodes_of(cog) -> List[Dict[str, Any]]:
    """从中枢取出当前记忆条目（给 decay_report 用）。"""
    try:
        from pasm_skills.cognition import episodes_of  # type: ignore
        return episodes_of(cog.agent)
    except Exception:
        return []


def tool_save(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """把当前所有智能体状态落盘。"""
    if args.get("agent_id"):
        ag = bridge.get(_agent_id(args))
        path = ag.save()
        return {"saved": [str(path)]}
    return {"saved": bridge.save_all()}


# ============================================================ 注册表

ToolFn = Callable[[Dict[str, Any], CognitiveBridge], Dict[str, Any]]

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "pasm_context",
        "description": (
            "取 PASM 认知上下文（只读，不写记忆）。返回：与当前话题相关的长期记忆、"
            "当前情绪值、人格、可用动作池。**这是把 PASM 接进大模型提示词的首选工具** —— "
            "先调它，再把 recalled 里的内容当作'你确实记得的事'写进回复。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "当前用户说的话/话题，用于检索相关记忆"},
                "k": {"type": "integer", "description": "最多返回几条记忆，默认 5", "default": 5},
                "agent_id": {"type": "string", "description": "智能体 id，默认 default。不同 id 记忆互相隔离", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
                "digest": {"type": "boolean", "description": "brief 字段是否用认知摘要（默认 true，省 token 且不丢情绪/人格/显著度记忆；false 回滚到旧紧凑版）", "default": True},
                "digest_chars": {"type": "integer", "description": "认知摘要字符预算，默认 80（≈38 tok，比旧 brief 更省且保住人格/显著度记忆）；要连 hint 一起带可传 220（≈80 tok）", "default": 80},
            },
            "required": [],
        },
        "fn": tool_context,
    },
    {
        "name": "pasm_recall",
        "description": "在 PASM 长期记忆里检索与 query 相关的经历，返回标题/摘要/标签/重要度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词"},
                "k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                "min_relevance": {
                    "type": "number", "default": 0.0,
                    "description": ("可选相关性闸门（默认 0 = 关闭，保持旧行为）。"
                                    "设为正值时，只返回语义分显著高于本批均值的记忆；"
                                    "返回空表示'没有能支撑此问题的记忆'，宿主应如实说明而非编造。"
                                    "离线 hashing 后端建议 0.15，嵌入后端需自行标定。"),
                },
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["query"],
        },
        "fn": tool_recall,
    },
    {
        "name": "pasm_semantic",
        "description": (
            "语义检索（认知层）：换一种说法也能命中，并解释每条为什么被召回。"
            "适合当 pasm_recall 检索不到时的第二步 —— 它走向量 + 中文同义扩展，"
            "并按'记忆保留度'加权（很久没被唤起的记忆会自然降权）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词（可以是完整的问句）"},
                "k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                "use_focus": {"type": "boolean", "description": "是否按当前焦点加权，默认 true", "default": True},
                "use_forgetting": {"type": "boolean", "description": "是否启用遗忘曲线，默认 true", "default": True},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["query"],
        },
        "fn": tool_semantic,
    },
    {
        "name": "pasm_focus",
        "description": (
            "焦点栈：查看或更新'现在在聊什么'。长对话里先压入当前话题，"
            "后续检索会自动给相关内容加权，避免跑题。不传 topic 就是查看。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "当前话题（不传则只看不写）"},
                "entities": {"type": "array", "items": {"type": "string"}, "description": "涉及的实体/关键词"},
                "weight": {"type": "number", "description": "权重，默认 1.0", "default": 1.0},
                "n": {"type": "integer", "description": "渲染几条焦点，默认 3", "default": 3},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_focus,
    },
    {
        "name": "pasm_consolidate",
        "description": (
            "记忆巩固（睡眠回放）：把高度相似的重复经历蒸馏成一条要点，"
            "并把源条目标记为已合并，避免记忆池被重复项撑爆。"
            "默认只给建议（apply=false），确认后传 apply=true 执行。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apply": {"type": "boolean", "description": "是否真的执行（默认 false，只出建议）", "default": False},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_consolidate,
    },
    {
        "name": "pasm_observe",
        "description": (
            "把一件事写进 PASM 长期记忆。值得记住的用户信息、承诺、偏好、共同经历都应该写进来。"
            "salience 越高越不容易被淘汰（1-5，重要的事用 4-5）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "记忆标题，简短醒目"},
                "brief": {"type": "string", "description": "详细描述"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签，便于检索命中"},
                "salience": {"type": "integer", "description": "重要度 1-5，默认 2", "default": 2, "minimum": 1, "maximum": 5},
                "category": {"type": "string", "description": "分类，默认 日常", "default": "日常"},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["title"],
        },
        "fn": tool_observe,
    },
    {
        "name": "pasm_feel",
        "description": "向 PASM 报告一个带情绪效价的事件，驱动情绪状态演化（valence: -1 负面 ~ +1 正面）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event": {"type": "string", "description": "事件描述"},
                "valence": {"type": "number", "description": "情绪效价 -1.0 ~ 1.0", "minimum": -1, "maximum": 1},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["event", "valence"],
        },
        "fn": tool_feel,
    },
    {
        "name": "pasm_act",
        "description": (
            "让 PASM 按「人格基线 + 反馈学到的偏好」从动作池里选一个动作。"
            "不传 candidates 就用智能体自己的动作池。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidates": {"type": "array", "items": {"type": "string"}, "description": "候选动作列表（可选）"},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_act,
    },
    {
        "name": "pasm_feedback",
        "description": (
            "用户对 PASM 行为的反馈，会塑形后续动作选择。"
            "kind: praise(夸奖)/scold(责怪)/poke(调侃)/hug(安慰)/ignore(无视)。"
            "**必须尽量带 action**（被评价的那个动作名），否则偏好会集中在某一个动作上。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["praise", "scold", "poke", "hug", "ignore"]},
                "action": {"type": "string", "description": "被反馈的动作名，强烈建议传"},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["kind"],
        },
        "fn": tool_feedback,
    },
    {
        "name": "pasm_chat",
        "description": (
            "走一次完整认知回路：检索记忆 → 渲染回复 → 把这次对话写进记忆。"
            "**回复是模板渲染、非 LLM 生成**，用于快速验证或纯离线场景；"
            "要自然语言效果请用 pasm_context 配合你自己的模型。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "用户输入"},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": ["text"],
        },
        "fn": tool_chat,
    },
    {
        "name": "pasm_persona",
        "description": (
            "查看或更新人格。不传 persona 就是查看。传入为**合并更新**（未提及的键保持原值）。"
            "常用键：name/role/tone/temper(0-1 主动性)/energy(0-1 活跃度)/play(0-1 俏皮度)/actions(动作池数组)。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "object", "description": "要合并进去的人格字段（可选）"},
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_persona,
    },
    {
        "name": "pasm_status",
        "description": "查看 PASM 状态快照：档位(light/core/bionic)、记忆条数、情绪值、交互次数、落盘目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "default": "default", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_status,
    },
    {
        "name": "pasm_save",
        "description": "把 PASM 状态立即落盘（不传 agent_id 则保存全部已加载的智能体）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "可选；不传则保存全部", "pattern": "^[\\w.\\-]{1,64}$"},
            },
            "required": [],
        },
        "fn": tool_save,
    },
]

#: name -> 工具定义（含 fn）
TOOL_INDEX: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}


def list_tools() -> List[Dict[str, Any]]:
    """给 `tools/list` 用的工具清单（不含内部 fn）。"""
    return [
        {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for t in TOOLS
    ]


def call_tool(name: str, args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """执行一个工具。未知工具抛 KeyError，由 server 转成 JSON-RPC 错误。"""
    tool = TOOL_INDEX.get(name)
    if tool is None:
        raise KeyError(name)
    return tool["fn"](args or {}, bridge)
