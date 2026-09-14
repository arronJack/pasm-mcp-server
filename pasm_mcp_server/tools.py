"""MCP 工具定义与实现。

工具设计原则：**暴露认知，不抢语言**。
PASM 提供客户端大模型没有的东西 —— 跨会话的长期记忆、连续的情绪状态、
被反馈塑形过的行为倾向。至于"这句话该怎么说"，交给客户端自己的模型。

所以最常用的不是 `pasm_chat`（那会把 PASM 当成又一个聊天模型），
而是 `pasm_context`：它把"现在该记得什么、情绪如何、倾向做什么"打包返回，
客户端拿去拼进自己的提示词。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from .bridge import CognitiveBridge

# ============================================================ 工具实现


def _agent_id(args: Dict[str, Any]) -> str:
    return str(args.get("agent_id") or "default")


def tool_context(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """取认知上下文（只读，不写记忆）。这是**注入提示词**用的一号工具。"""
    ag = bridge.get(_agent_id(args))
    query = str(args.get("query") or "")
    k = int(args.get("k") or 5)
    facts = ag.recall(query, k=k) if query else []
    return {
        "agent_id": ag.agent_id,
        "tier": ag.tier,
        "query": query,
        "recalled": [
            {
                "title": f.get("title", ""),
                "brief": f.get("brief", ""),
                "tags": list(f.get("tags", [])),
                "category": f.get("cat", f.get("category", "")),
                "salience": f.get("sal", f.get("salience", 1)),
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


def tool_recall(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """记忆检索。"""
    ag = bridge.get(_agent_id(args))
    query = str(args.get("query") or "")
    if not query:
        raise ValueError("query 不能为空")
    k = max(1, min(50, int(args.get("k") or 5)))
    hits = ag.recall(query, k=k)
    return {
        "agent_id": ag.agent_id,
        "query": query,
        "count": len(hits),
        "hits": [
            {
                "title": f.get("title", ""),
                "brief": f.get("brief", ""),
                "tags": list(f.get("tags", [])),
                "salience": f.get("sal", f.get("salience", 1)),
            }
            for f in hits
        ],
    }


def tool_observe(args: Dict[str, Any], bridge: CognitiveBridge) -> Dict[str, Any]:
    """写入一条经历（记忆）。"""
    ag = bridge.get(_agent_id(args))
    title = str(args.get("title") or "").strip()
    if not title:
        raise ValueError("title 不能为空")
    sal = int(args.get("salience") or 2)
    sal = max(1, min(5, sal))
    ag.observe(
        title=title,
        brief=str(args.get("brief") or ""),
        tags=[str(t) for t in (args.get("tags") or [])],
        salience=sal,
        category=str(args.get("category") or "日常"),
    )
    ag.save()
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
    """状态快照：档位、记忆量、情绪、反馈数。"""
    ag = bridge.get(_agent_id(args))
    snap = ag.summary()
    snap["persist_dir"] = str(ag.persist_dir)
    snap["bridge_root"] = str(bridge.persist_root)
    snap["loaded_agents"] = bridge.agent_ids()
    return snap


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
                "agent_id": {"type": "string", "description": "智能体 id，默认 default。不同 id 记忆互相隔离", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": ["query"],
        },
        "fn": tool_recall,
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "default": "default"},
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
                "agent_id": {"type": "string", "description": "可选；不传则保存全部"},
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
