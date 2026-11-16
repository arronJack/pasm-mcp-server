# PASM MCP Server · 给任意 AI 客户端装上长期记忆

> **把 PASM 的认知内核暴露成标准 MCP 工具。**
> 你的大模型（IDE 插件 / 桌面 AI 客户端 / 自研 Agent）本身没有跨会话记忆、没有情绪连续性、
> 没有"被夸过就更爱做某件事"的行为倾向 —— 这个包就是给它补上这些。

**一句话定位**：PASM 不是"又一个聊天模型"，是一个**认知器官** ——
记忆、情绪、行为倾向。语言生成仍然由你自己的模型负责。

```
┌──────────────────────────┐   MCP (stdio)   ┌──────────────────────┐
│  你的 AI 客户端 / Agent   │ ◄─────────────► │  pasm-mcp-server     │
│  （负责说话与推理）        │   工具调用       │  （负责记住与感受）   │
└──────────────────────────┘                 └──────────────────────┘
```

---

## 〇、PASM 生态索引（十一仓同频，2026-09-30 校准）

| 仓 | 角色 | 可见性 | 版本 |
|---|---|---|---|
| `pasm2` | V2.0 独立认知底座（阶段 0-11：预测/记忆图/符号/双系统/量子/小脑/DMN/性格/LLM 桥，Alpha） | 公开 | 2.0.0a11 |
| `pasm-skills` | 基座：`BaseAgent` + 认知能力层 + `create_backend()` 探测工厂 | 公开 | 0.6.3 |
| `pasm-framework` | 应用框架：HTTP 服务 / 路由 / 插件 + `CognitiveAssembler.v1()/v2()` | 公开 | 0.5.4 |
| `pasm-agents` | 成品智能体集（NPC / 陪伴 / 教学 / 客服 / 验证） | 公开 | 0.5.0 |
| **`pasm-mcp-server`（本仓）** | **MCP 接入层：给任意 AI 客户端装长期记忆（`PASM2=1` 切 V2）** | **公开** | **0.3.1** |
| `pasm-domain-advisor` · `pasm-medical` · `pasm-customer-service` | 领域智能体：领域顾问引擎 / 医疗辅助 / 专业客服 | 公开 | 0.1.1 · 0.1.0 · 0.2.0 |
| `PASM-Lite` | 教学版 + 认知引擎接口（不接 V2，保持纯净） | 公开 | — |
| `PASM` | 核心引擎（七层仿生 / 世界模型，含 `pasm2/`；桌面源码 0.31.16） | 私有 | 0.7.2 |
| `pasm-qclaw` | 桌面应用发行通道（安装包 + `latest.json` 升级源） | 公开 | 0.31.15（已发行） |

流向：`PASM`（核心）→ `pasm-skills`（基座）→ `pasm-agents`（智能体）→
`pasm-mcp-server`（分发）→ `pasm-qclaw`（桌面产品）；`PASM-Lite` 是面向外界的教学窗口。

地址：
[Gitee](https://gitee.com/arronzheng/pasm-mcp-server) ·
[GitHub](https://github.com/arronJack/pasm-mcp-server)

---

## 一、快速开始

```bash
pip install pasm-mcp-server
pasm-mcp-server --selftest        # 自检（16 项）
```

### 接入客户端（以 Cursor 为例）

写到 `.cursor/mcp.json`（项目级）或 `~/.cursor/mcp.json`（全局）：

```json
{
  "mcpServers": {
    "pasm": {
      "command": "python",
      "args": ["-m", "pasm_mcp_server"]
    }
  }
}
```

> Windows 上如果 `python` 不在 PATH，把它换成绝对路径，例如 `"C:\\Python313\\python.exe"`。

### 各客户端配置位置

| 客户端 | 配置文件 | 字段形状 |
|---|---|---|
| **Cursor** | `.cursor/mcp.json` 或 `~/.cursor/mcp.json` | `mcpServers` |
| **Claude Desktop** | `%APPDATA%\Claude\claude_desktop_config.json`（macOS：`~/Library/Application Support/Claude/`） | `mcpServers` |
| **VS Code**（Copilot Agent） | `.vscode/mcp.json` | `servers` + `"type": "stdio"` |
| **自建 / 其他客户端** | 见 `examples/mcp_generic.json` | `mcpServers` |

现成文件：[`examples/mcp_cursor.json`](examples/mcp_cursor.json) ·
[`examples/mcp_claude_desktop.json`](examples/mcp_claude_desktop.json) ·
[`examples/mcp_vscode.json`](examples/mcp_vscode.json) ·
[`examples/mcp_generic.json`](examples/mcp_generic.json)

**校验是否接上**：`python examples/stdio_client_demo.py` —— 它会真的起一个子进程、
做完整握手、逐个调用工具（和真实客户端做的事一模一样）。

---

## 二、工具有哪些（13 个）

### 认知核心

| 工具 | 干什么 |
|---|---|
| **`pasm_context`** ⭐ | **首选**。取"现在该记得什么 + 情绪如何 + 倾向做什么"，拿去拼进提示词。只读，不写记忆 |
| `pasm_recall` | 记忆检索（装了认知层自动走语义） |
| `pasm_semantic` | 语义检索 + 可解释：换说法也能命中，并给出每条的融合分 / 语义分 / 记忆保留度 |
| `pasm_observe` | 把一件事写进长期记忆（重要度 1-5） |
| `pasm_feel` | 报告带情绪效价的事件，驱动情绪演化 |
| `pasm_act` | 按「人格 + 学到的偏好」选一个动作 |
| `pasm_feedback` | 反馈塑形（**务必带 `action`**） |

### 记忆维护

| 工具 | 干什么 |
|---|---|
| `pasm_focus` | 焦点栈：压入/查看"现在在聊什么"，给检索加权 |
| `pasm_consolidate` | 记忆巩固（睡眠回放）：把重复经历蒸馏成要点。默认只出建议 |

### 管理

| 工具 | 干什么 |
|---|---|
| `pasm_chat` | 完整认知回路对话一次（模板渲染，非 LLM） |
| `pasm_persona` | 查看/合并更新人格 |
| `pasm_status` | 状态快照（档位、记忆量、认知层后端、焦点、归档） |
| `pasm_save` | 立即落盘 |

---

## 三、认知能力（0.2.0 起）

依赖 `pasm-skills>=0.5.0` 的认知层时自动启用，没有也能跑（退回字面匹配，功能降级不报错）。

| 能力 | 效果 |
|---|---|
| **语义检索** | 「我叫什么名字」能命中存成「姓名」的记忆（字面匹配做不到） |
| **遗忘曲线** | 久未唤起的记忆自然降权，学情更真实 |
| **记忆巩固** | 重复经历蒸馏成要点，记忆池不被撑爆 |
| **焦点栈** | 长对话不跑题 |

检索打分是可解释的：

```
score = 语义相似 × 0.62 + 记忆保留度 × 0.24 + 重要度 × 0.14 + 焦点加成
```

### 换更好的向量后端（可选）

内置后端是**零依赖离线**的字符 n-gram hashing + 中文同义扩展，开箱即用。
想要真正的语义向量，配一个 OpenAI 兼容的 embedding 接口即可自动接管：

```bash
export PASM_EMBED_URL="https://<your-endpoint>/v1/embeddings"
export PASM_EMBED_MODEL="bge-m3"
export PASM_EMBED_KEY="<key>"
```

也可以装 `sentence-transformers` 或 `fastembed`，会自动被识别。
`pasm_status` 会告诉你当前实际用的是哪个后端 —— **降级不隐藏**。

---

## 四、环境变量

| 变量 | 作用 |
|---|---|
| `PASM_MCP_PERSIST_DIR` | 状态落盘根目录，默认 `~/.pasm-mcp/` |
| `PASM_MCP_PERSONA` | 默认人格（JSON 字符串） |
| `PASM_SKILLS_PATH` | 本地开发逃生口：指向 `pasm-skills` 仓库根目录 |
| `PASM_EMBED_URL` / `_MODEL` / `_KEY` | 可选：外部 embedding 接口 |

---

## 五、PASM 在整条链路里的位置

它**不生成语言**。正确用法是：先从 `pasm_context` 取认知上下文，再让你自己的模型说话。

```
用户说话 → pasm_context(query=用户的话) → 注入 brief 字段（不要整包！）
        → 你的模型生成回复
        → pasm_observe(值得记的事) → pasm_feedback(用户反应)
```

### 省 token 接入规范（重要）

**把 `pasm_context` 返回的 `brief` 字段拼进系统提示词，不要把整个返回体塞进去。**
整包 JSON 含 `recalled` 全量摘要 / `persona` / `action_pool` / `hint` 等结构，实测约
**900 tok/轮**；而 `brief` 是专门为此生成的**认知摘要**，默认 ≈**38 tok**，省 ~96%。

`brief` 摘要固定保住 PASM 相对通用 LLM **最独特**的东西，超预算按优先级整块丢弃（不腰斩）：

| 块 | 内容 | 紧预算下 |
|---|---|---|
| 身份锚 + 情绪语义 | `我是小墨·认知陪伴`、`情绪低落(-0.62)`（不是裸数字） | **永不丢** |
| 人格画像 | `性格：温和、平和`（被反馈塑形过的行为倾向） | 保 |
| 显著度记忆 | `记得：姓名、猫的禁忌…`（按 salience 排序，不是召回顺序） | 保 |
| 提示语 hint | 给宿主的操作说明 | 可丢 |

`pasm_context` 的相关字段：

| 字段 | 说明 |
|---|---|
| `brief` | **注入用**。默认即认知摘要（省 token 且不丢情绪/人格/记忆） |
| `brief_digest` | 始终是认知摘要（不受开关影响，供对照） |
| `brief_legacy` | 始终是全量旧紧凑版（只带 mood + 3 标题，兼容旧客户端） |
| `brief_mode` | `digest` / `legacy`，当前 `brief` 用的哪种 |
| `digest_meta` | 摘要的字符数 / tok 估算 / kept / dropped（可观测，便于审计） |

可选参数：
- `digest: true|false` —— `brief` 用摘要还是旧紧凑版（默认 `true`；`false` 回滚到旧行为）。
- `digest_chars: int` —— 摘要字符预算，默认 `80`（≈38 tok）；要连 hint 一起带可传 `220`（≈80 tok）。
  注意 220 档虽然信息更全，但仍远小于整包；只有确实需要宿主操作提示时才调大。

> 需要结构化细节（每条记忆的全量 brief / tags / 分类）时，另行调用 `pasm_recall`，
> 不要为了这些细节把 `pasm_context` 整包塞进提示词——那正是被上面的规范省掉的成本。

---

## 六、生态中的位置

| 仓 | 角色 | 可见性 |
|---|---|---|
| `pasm-skills` | **基座**：`BaseAgent` + 认知能力层 | 公开 |
| `pasm-agents` | 成品智能体集（NPC / 陪伴 / 教学 / 验证） | 公开 |
| **`pasm-mcp-server`** | **本仓**：MCP 接入层 | 公开 |
| `PASM-Lite` | 教学版 + 认知引擎接口 | 公开 |
| `PASM` | 核心引擎（七层仿生 / 世界模型） | 私有 |
| `pasm-qclaw` | 桌面应用发行通道 | 公开 |

本包只依赖**公开**的 `pasm-skills`，不依赖私有核心。
装了核心的机器会自动从 `light` 档升到 `bionic` 档，没有也能正常跑。

---

## 七、打包发布（维护者）

```bash
python -m pip install --upgrade build twine
python -m build                      # 产出 dist/*.whl 与 dist/*.tar.gz
twine check dist/*
twine upload dist/*                  # 需要 PyPI token
```

> GitHub Actions 流水线见 [`docs/publish-workflow.example.yml`](docs/publish-workflow.example.yml)
> （放到 `.github/workflows/publish.yml` 即生效；默认不放在那里是因为推送 workflow 需要
> PAT 带 `workflow` 权限）。

---

## 许可

MIT
