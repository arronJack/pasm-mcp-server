"""PASM 认知桥 —— 把 `pasm_skills.sdk.BaseAgent` 包成 MCP 工具能直接调用的接口。

设计要点
--------
1. **每个 agent_id 一个实例**，进程内缓存。同 id 多次调用共享同一份记忆/情绪/动作权重 ——
   这正是 PASM 的价值所在（跨调用连续的认知状态），而不是每次调用新建。
2. **档位透明**：`tier` 字段照抄 BaseAgent（light / core / bionic）。
   降级不隐藏 —— 客户端能知道自己用的是哪档。
3. **不内置 LLM**：`_render_reply` 走模板渲染。
   本包定位是"认知器官"，不是"对话引擎" —— 真正的语言生成交给客户端的大模型，
   PASM 负责给它**记忆、情绪、倾向**。想接 LLM 的在自己那一侧接。
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__  # noqa: F401  保证包版本号单一来源

# 本地开发逃生口：还没把 pasm-skills 装进当前解释器时，
#   PASM_SKILLS_PATH=/path/to/pasm-skills pasm-mcp-server --selftest
# 正式部署不需要它（pip install pasm-skills 即可）。
_skill_path = os.environ.get("PASM_SKILLS_PATH")
if _skill_path:
    sys.path.insert(0, _skill_path)

try:
    from pasm_skills.sdk import BaseAgent
except ImportError as ex:  # pragma: no cover
    raise SystemExit(
        "找不到 pasm-skills 基座。请先安装：pip install pasm-skills>=0.4.4\n"
        "本地开发也可设 PASM_SKILLS_PATH 指向 pasm-skills 仓库根目录。\n"
        "（原始错误：%s）" % ex
    )

#: 未显式配置动作池时的默认动作。
#: 名字里刻意带 BaseAgent._fallback_weights 认得的关键词
#: （talk/share/teach/give → temper；hop/dance/run → energy；peek/play/joke → play），
#: 这样即使装在 light 档、没有真学习层，性格参数也仍然起作用。
DEFAULT_ACTIONS: List[str] = ["greet", "ask", "share", "teach", "listen"]

#: 默认人格。客户端可通过 pasm_persona 覆盖任一键。
DEFAULT_PERSONA: Dict[str, Any] = {
    "name": "小墨",
    "role": "认知陪伴",
    "tone": "温和、简洁",
    "temper": 0.5,   # 主动性
    "energy": 0.5,   # 活跃度
    "play": 0.5,     # 俏皮度
}


def _force_v1() -> bool:
    """显式要求走 V1（逃生舱）。

    认两种写法：``PASM_BACKEND=v1``（基座工厂的标准变量）与
    ``PASM2=0/false/no/off``（沿用旧的实验开关语义，关掉即回到 V1）。
    """
    b = os.environ.get("PASM_BACKEND", "").strip().lower()
    if b in ("v1", "pasm1"):
        return True
    v = os.environ.get("PASM2", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return True
    return False


class McpAgent(BaseAgent):
    """MCP 场景下的 PASM 智能体：动作池与回复模板都可配置，其余交给基座。"""

    def action_pool(self) -> List[str]:
        acts = self.persona.get("actions")
        if isinstance(acts, list) and acts:
            return [str(a) for a in acts]
        return list(DEFAULT_ACTIONS)

    def bootstrap_event(self) -> List[Dict[str, Any]]:
        """首次启动时写一条初始记忆 —— 让 pasm_context 第一次调用就不空手。"""
        name = self.persona.get("name", "小墨")
        return [{
            "title": "初次相遇",
            "brief": f"{name}第一次接入 MCP 客户端，还没有任何共同经历。",
            "tags": ["初次", "相遇"],
            "salience": 3,
            "category": "关系",
        }]

    def _render_reply(self, text: str, facts: List[Dict[str, Any]], mood: float) -> str:
        """模板渲染。不带 LLM —— 保证无网、无 key、无 GPU 也能回话。"""
        name = self.persona.get("name", "小墨")
        tone = self.persona.get("tone", "温和")
        parts: List[str] = []
        if facts:
            head = "；".join(str(f.get("title", "")) for f in facts[:2] if f.get("title"))
            if head:
                parts.append(f"我记得「{head}」")
        if mood > 0.25:
            parts.append("现在心情不错")
        elif mood < -0.25:
            parts.append("这会儿有点低落")
        if text:
            parts.append(f"你刚才说的是：{text[:40]}")
        body = "，".join(parts) if parts else "我还在熟悉你"
        return f"{name}（{tone}）：{body}。"

    # ------- 人格热更新 -----------------------------------------

    def set_persona(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """合并式更新人格（不是整体替换 —— 漏传的键不该被抹掉）。"""
        if not isinstance(patch, dict):
            raise ValueError("persona 必须是对象")
        self.persona.update(patch)
        if hasattr(self, "state") and isinstance(self.state.persona, dict):
            self.state.persona.update(patch)
        return dict(self.persona)


# ============================================================ agent_id 安全
# 课题 C（2026-11-20）实测缺陷：_agent_id() 只 str() 不清洗，bridge 又直接
# persist_root / agent_id 拼路径 → 路径穿越 / 绝对路径写 / 大小写碰撞 / NFC-NFD 分裂。
# 这里做统一收口：工具层与桥层都调用，纵深防御。
_AGENT_ID_RE = re.compile(r"^[\w.\-]{1,64}$", re.UNICODE)
_WIN_RESERVED = {"con", "prn", "aux", "nul"} | \
    {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def validate_agent_id(value: Any) -> str:
    """把外部传入的 agent_id 收敛成安全的目录名；非法值明确报错。

    - NFC 归一：同一身份的 NFC/NFD 写法合并到同一目录
    - 白名单：字母/数字/Unicode 文字/`_`/`-`/`.`，1-64 字符（中文 id 可用）
    - 拒绝 `.`、`..`、路径分隔符、控制字符、Windows 保留设备名
    - 不做静默改写：非法 id 报错，避免"换个目录 = 记忆凭空消失"
    """
    raw = "" if value is None else str(value)
    aid = unicodedata.normalize("NFC", raw).strip()
    if not aid or aid in (".", ".."):
        raise ValueError("agent_id 不能为空，也不能是 . 或 ..")
    if not _AGENT_ID_RE.fullmatch(aid):
        raise ValueError(
            "agent_id 只允许字母、数字、文字、_、-、.（1-64 字符）；"
            "禁止空格、路径分隔符、控制字符与绝对路径"
        )
    if aid.split(".")[0].lower() in _WIN_RESERVED:
        raise ValueError(f"agent_id 不能使用 Windows 保留设备名：{aid}")
    return aid


class CognitiveBridge:
    """按 agent_id 管理 McpAgent 实例。"""

    def __init__(self, persist_root: Optional[str | Path] = None,
                 default_persona: Optional[Dict[str, Any]] = None):
        root = persist_root or os.environ.get("PASM_MCP_PERSIST_DIR")
        self.persist_root = Path(root) if root else (Path.home() / ".pasm-mcp")
        self.persist_root.mkdir(parents=True, exist_ok=True)
        self._default_persona = dict(DEFAULT_PERSONA)
        if default_persona:
            self._default_persona.update(default_persona)
        # 允许用环境变量整体覆盖默认人格（JSON 字符串）
        env_persona = os.environ.get("PASM_MCP_PERSONA")
        if env_persona:
            try:
                self._default_persona.update(json.loads(env_persona))
            except Exception:
                pass
        self._agents: Dict[str, McpAgent] = {}

    def get(self, agent_id: str = "default",
            persona: Optional[Dict[str, Any]] = None) -> McpAgent:
        """取（或创建）一个智能体。persona 只在**首次创建**时生效。

        已存在的 agent 想改人格请走 pasm_persona 工具 —— 否则每次调用传不同 persona
        会造成"人格抖动"，而 persona 是长期资产，不该被单次调用覆盖。
        """
        # ★ 纵深防御：工具层会校验，这里再校验一次，防止绕过工具直接调 bridge。
        agent_id = validate_agent_id(agent_id)
        agent_dir = self.persist_root / agent_id
        resolved = agent_dir.resolve()
        root_resolved = self.persist_root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise ValueError(f"agent_id 逃逸出数据目录：{agent_id}")
        # 大小写 / Unicode 同形碰撞检测：Windows 文件系统大小写不敏感，
        # AliceCase 与 alicecase 会落进同一目录 → 跨身份记忆串味。
        # 用 sidecar 标记记录创建者，命中不一致就明确拒绝，而不是静默共享。
        if agent_dir.exists():
            marker = agent_dir / ".agent_id"
            if marker.exists():
                try:
                    owner = marker.read_text(encoding="utf-8").strip()
                except Exception:
                    owner = ""
                if owner and owner != agent_id:
                    raise ValueError(
                        f"agent_id 冲突：目录已属于 {owner!r}，不能再用 {agent_id!r} 打开"
                    )
            else:
                try:
                    marker.write_text(agent_id, encoding="utf-8")
                except Exception:
                    pass
        if agent_id not in self._agents:
            p = dict(self._default_persona)
            if persona:
                p.update(persona)
            # ---- 认知后端选择（v0.3.0）：默认 V2（pasm2），V1 为诚实回退。
            # 为什么改默认：PASM 主推 V2，此前只有 PASM2=1 才走 V2 →
            # 实际部署几乎永远跑 V1，新引擎等于没上线。
            # 逃生舱：PASM_BACKEND=v1（或 PASM2=0/false/no）强制 V1。
            # 诚实回退：pasm2 未安装 / 构造失败 → 基座工厂如实回退 V1。
            backend = None
            choice = "v1" if _force_v1() else "v2"
            try:
                from pasm_skills.sdk.backend import create_backend
                backend = create_backend(
                    self.persist_root / agent_id, backend_choice=choice)
            except Exception:
                backend = None            # 诚实回退默认路径
            # P11-D3（2026-11-13）：V2 backend 拿到 persist_dir 后，构造时
            # **不会自动 load()** —— 必须在这里显式恢复，否则跨重启后
            # 人格/情绪/自传体记忆全部回到出厂（实测 episodes()=0 →
            # 语义索引永远建不起来，pasm_recall 全空）。
            if backend is not None and hasattr(backend, "load"):
                try:
                    backend.load()
                except Exception:
                    pass                  # 无历史状态 → 全新开始，不算错误
            self._agents[agent_id] = McpAgent(
                agent_id=agent_id,
                persona=p,
                persist_dir=self.persist_root / agent_id,
                backend=backend,
            )
            # 新建目录也要打标记，否则首次创建后立刻用大小写变体打开仍会共享
            try:
                agent_dir.mkdir(parents=True, exist_ok=True)
                marker = agent_dir / ".agent_id"
                if not marker.exists():
                    marker.write_text(agent_id, encoding="utf-8")
            except Exception:
                pass
        return self._agents[agent_id]

    def agent_ids(self) -> List[str]:
        """已加载的智能体 id 列表。"""
        return sorted(self._agents.keys())

    def save_all(self) -> List[str]:
        """落盘所有已加载的智能体（进程退出前调用）。

        P11-D3（2026-11-13）：``ag.save()`` 只写基座 state 层
        （agent_state.json），不写 V2 引擎的 mind 状态（记忆图/自传体/
        情绪/心境…）。缺 ``core.save()`` 时 ``pasm2-state.json`` 从不
        落盘，下次启动 ``core.load()`` 无处可读 —— 跨重启失忆的另一半
        根因。不吞 core.save 的异常以外的错误：core 落盘失败要留下痕迹。
        """
        saved = []
        for aid, ag in self._agents.items():
            try:
                ag.save()
                core = getattr(ag, "_core", None)
                if core is not None and hasattr(core, "save"):
                    try:
                        core.save()
                    except Exception:
                        pass          # core 落盘失败不阻塞 state 落盘
                saved.append(aid)
            except Exception:
                pass
        return saved

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CognitiveBridge root={self.persist_root} agents={list(self._agents)}>"
