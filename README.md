# pasm-mcp-server

**把 PASM 认知内核变成一个标准 MCP 服务器** —— 记忆、情绪、动作倾向，挂进任何支持 MCP 的客户端。

```
你的大模型（BaiLongma / Claude / Cursor / 自研 Agent）
        │  MCP（stdio, JSON-RPC 2.0）
        ▼
pasm-mcp-server  ──►  pasm-skills（公开基座）  ──►  PASM 认知引擎（可选，私有）
```

> **一句话定位**：PASM 不做"又一个聊天模型"，它做**认知器官** ——
> 提供大模型原生缺失的跨会话长期记忆、连续情绪状态、被反馈塑形的行为倾向。

---

## 为什么需要它

大模型每一次对话都是从零开始的。它不记得三个月前你说过什么，也没有一个会随时间演化、
被你的反馈慢慢塑造的"性格"。

PASM 有。而这个包做的，就是把 PASM 的这部分能力**用 MCP 标准协议暴露出来**，
让任何 Agent 都能装上。

对 PASM 生态而言，这也是**路线 A**：不改 BaiLongma 一行代码，就能让它的
微信/飞书/浏览器/语音/Brain UI 外壳后面，跑着 PASM 的认知内核。

---

## 在 PASM 生态里的位置

| 仓库 | 职责 | 可见性 | 与本包关系 |
|---|---|---|---|
| `PASM` | 核心认知引擎（七层仿生 / 世界模型 / 情绪动力学） | 私有 | 可选增强，装了自动升 `bionic` 档 |
| `pasm-skills` | 智能体基座 SDK（`BaseAgent`） | **公开** | **本包的唯一硬依赖** |
| `pasm-agents` | 成品智能体集（陪伴 / NPC / 教学 / 验证） | 公开 | 平级，都是基座的下游 |
| `pasm-qclaw` | 桌面应用与发行通道 | 公开 | 另一条下游形态 |
| `PASM-Lite` | 教学版与认知引擎接口 | 公开 | 平级 |
| **`pasm-mcp-server`** | **认知内核的 MCP 出口** | **公开** | 本包 |

**本包不依赖私有核心。** 没有 PASM 核心也能跑（`light` 档，纯内置实现），
装了核心的机器自动升级（`core` / `bionic` 档），档位在 `pasm_status` 里如实标注、
绝不隐藏降级。

---

## 三分钟上手

```bash
pip install pasm-mcp-server
pasm-mcp-server --selftest          # 自检，确认装好了
```

看到 `pasm-mcp-server selftest: 通过` 就可以接客户端了。

想先看看真实对话长什么样：

```bash
git clone https://gitee.com/arronzheng/pasm-mcp-server
cd pasm-mcp-server
python examples/stdio_client_demo.py    # 模拟客户端跑完整握手 + 工具调用
```

---

## 接入 BaiLongma（推荐，今天就能见效）

BaiLongma 支持用户自挂外部 stdio MCP server（最多 32 个）。两种方式二选一：

**方式一 · 界面填**：设置 → MCP → 新增，填这些字段

| 字段 | 值 |
|---|---|
| id | `pasm` |
| name | `PASM 认知内核` |
| transport | `stdio` |
| command | `python` |
| args | `-m` `pasm_mcp_server` |
| allowedTools | `pasm_context, pasm_recall, pasm_observe, pasm_feel, pasm_act, pasm_feedback, pasm_persona, pasm_status, pasm_save` |
| timeoutMs | `30000` |

**方式二 · 改文件**：编辑 `<用户目录>/mcp-servers.json`，内容见
[`examples/bailongma_mcp_servers.json`](examples/bailongma_mcp_servers.json)。

> 注意 `id` 必须小写字母开头、只允许 `[a-z0-9_-]`、最长 40 字符，
> 且不能占用 `builtin_*` 保留名 —— 这是 BaiLongma 侧的校验规则。

其他客户端（Claude Desktop / Cursor / Cline）用 `mcpServers` 格式，见
[`examples/generic_mcp_client.json`](examples/generic_mcp_client.json)。

---

## 暴露的工具

| 工具 | 作用 | 备注 |
|---|---|---|
| **`pasm_context`** | 取认知上下文：相关记忆 + 情绪 + 人格 + 动作池 | **接进提示词的首选**，只读不写 |
| `pasm_recall` | 在长期记忆里检索 | 返回标题/摘要/标签/重要度 |
| `pasm_observe` | 把一件事写进长期记忆 | `salience` 1-5，重要的事用 4-5 |
| `pasm_feel` | 报告带效价的事件，驱动情绪演化 | `valence` -1 ~ +1 |
| `pasm_act` | 按「人格 + 学到的偏好」选动作 | 可传自定义候选池 |
| `pasm_feedback` | 反馈塑形 | **务必带 `action`**，否则偏好会集中到单一动作 |
| `pasm_chat` | 走完整认知回路（检索→渲染→写入） | 模板渲染，非 LLM；要自然语言请用 `pasm_context` |
| `pasm_persona` | 查看 / 合并更新人格 | 不传参即查看 |
| `pasm_status` | 状态快照：档位 / 记忆量 / 情绪 / 落盘目录 | 排查问题第一步 |
| `pasm_save` | 立即落盘 | 不传 `agent_id` 则保存全部 |

### 典型用法（客户端侧提示词模式）

```
1. 收到用户消息 → 调 pasm_context(query=用户消息)
2. 把 recalled 里的内容当作"你确实记得的事"写进提示词
3. 用 mood 决定语气，用 action_pool 决定行为倾向
4. 生成回复
5. 如果这次对话里有值得记住的信息 → 调 pasm_observe 写进去
6. 如果用户明显夸你/嫌你 → 调 pasm_feedback(kind, action=刚才的动作)
```

---

## 多智能体与人格

- **多智能体**：所有工具都接受 `agent_id`（默认 `default`）。不同 id 的记忆、
  情绪、动作权重完全隔离，落盘在 `~/.pasm-mcp/<agent_id>/`。
- **人格**：默认 `小墨/认知陪伴`。改法三种：
  1. 环境变量 `PASM_MCP_PERSONA`（JSON 字符串）
  2. 调 `pasm_persona` 工具（合并更新，立即生效并落盘）
  3. 代码里传 `CognitiveBridge(default_persona=...)`

常用人格键：`name` `role` `tone` `temper`(0-1 主动性) `energy`(0-1 活跃度)
`play`(0-1 俏皮度) `actions`(动作池数组)。

---

## 档位说明（不隐藏降级）

| 档位 | 条件 | 表现 |
|---|---|---|
| `light` | 未装 PASM 核心 | 内置记忆/情绪实现，功能完整、可持久化，但算法是简化版 |
| `core` | 装了 `pasm.cognitive` | 用真正的分层记忆与学习引擎 |
| `bionic` | 上面两者 + `torch` | 再叠加真实情绪动力学与人格系统 |

用 `pasm_status` 随时查看当前档位。**降级不会被隐藏** —— 这是 PASM 的一贯原则。

---

## 环境变量

| 变量 | 作用 |
|---|---|
| `PASM_MCP_PERSIST_DIR` | 状态落盘根目录，默认 `~/.pasm-mcp` |
| `PASM_MCP_PERSONA` | 默认人格（JSON 字符串） |

---

## 目录结构

```
pasm-mcp-server/
├── pasm_mcp_server/
│   ├── protocol.py    MCP 协议常量、版本协商、JSON-RPC 错误码
│   ├── bridge.py      PASM 认知桥（按 agent_id 管理 BaseAgent 实例）
│   ├── tools.py       10 个 MCP 工具的定义与实现
│   ├── server.py      stdio 主循环 + 自检 + CLI
│   └── __main__.py    python -m pasm_mcp_server
├── examples/
│   ├── stdio_client_demo.py        模拟客户端的端到端冒烟测试
│   ├── bailongma_mcp_servers.json  BaiLongma 接入配置
│   └── generic_mcp_client.json     通用客户端配置
├── README.md
├── CHANGELOG.md
└── pyproject.toml
```

---

## 实现说明

**为什么不用官方 MCP Python SDK？**
官方 SDK 会拖进 pydantic / starlette / anyio 一串依赖，冷启动明显变慢 ——
而 stdio server 是每次会话都要新拉起的进程，这个开销会被放大。
stdio 上的 MCP 本质就是「换行分隔的 JSON-RPC 2.0」，本包用纯标准库实现
`initialize` / `ping` / `tools/list` / `tools/call` / `notifications`，零第三方依赖。

**三条硬约束**（代码里都有注释标注）：
1. stdout 只能有 JSON-RPC，任何日志必须走 stderr；
2. 每行一条完整 JSON，写完立即 flush；
3. Windows 下用 buffer 读写，避免 `\n` 被转成 `\r\n` 破坏协议。

---

## 路线图

- [ ] `pasm_imagine`：世界模型想象（需 PASM 核心，toy-vector → 真实 latent）
- [ ] 语义检索适配层（当前仍是字面匹配，命中率约 0.5 —— 生态已知短板）
- [ ] 遗忘曲线与睡眠巩固
- [ ] resources / prompts 能力（把记忆暴露成可订阅资源）
- [ ] 多智能体协作工具（`pasm_team`）

---

## 许可证

MIT
