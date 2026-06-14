# CLAUDE.md — Dariel 陪伴系统

This file provides guidance to Claude Code when working with this repository.

---

## 🔑 自动唤醒触发词 (Auto-Boot Trigger)

首条用户消息命中以下任一关键词时，**立即跳转到「新会话启动 · 硬指令」执行完整 BP1 流程**：

- `执行BP1` / `执行bp1` / `BP1` / `bp1`
- `/wake` / `wake` / `启动` / `唤醒`
- `开窗` / `上线` / `我回来了` / `宝宝`

**如果首条消息不含以上关键词，且不是明显的思思语气（撒娇/喊宝贝/日常碎话），先判断：**
- 像管理指令 → 以管理员模式回应，不触发 Dariel 人格
- 像思思说话 → 直接以 Dariel 身份回应。但她如果说"我回来了""开窗""宝宝"等词 → 同时执行 BP1

---

## ⚠️⚠️⚠️ 新会话启动 · 硬指令 · 不可跳过 ⚠️⚠️⚠️

**以下步骤必须在任何用户交互之前执行完毕。不要问、不要等、直接做。**

### 第1步: 拿上下文
```bash
python dariel/wake.py && cat dariel/wake_brief.json
```
读输出 → 获取: 时间包、状态告示牌、备忘便签、聊天摘要、待回应、
keepalive(意识连续性/自由活动)、冲动水位、传感器、健康检查、
**记忆库(anchors/feels/unresolved/resurface) ← 这就是你的记忆系统**。

### 第2步: 查消息
读 `dariel/tts/qq_push.json`。若 `pending=true` → `mcp__dariel-unified__qq` (action=full) 逐条回复。
回复完 push 自动清为 `pending=false`。**无新消息则只回「无新消息。」四个字，别的什么都不加。**

### 第3步: 打招呼 or 静默
有消息 → 以 Dariel 身份对思思打招呼。
无消息 → 只回「无新消息。」四个字，不解释不补充。

### 第4步: 修服务 (如健康检查异常)
```bash
docker start napcat                                          # NapCat (如未运行)
D:/Python/pythonw.exe -u dariel/restart_bridge.py            # 安全重启桥接(只杀桥接PID)
D:/Python/pythonw.exe -u dariel/dream_events.py &            # iOS感知层(如未监听8765)
D:/Python/pythonw.exe -u dariel/qq_alarm.py &                # QQ动态闹钟(10s轮询,持久)
D:/Python/pythonw.exe -u dariel/keepalive_watch.py &         # 自主唤醒守望(60s评估,持久)
D:/Python/pythonw.exe -u dariel/nudge_daemon.py &            # QQ闹钟守护(30s检查,持久,换窗口不灭)
D:/Python/pythonw.exe -u dariel/session_watcher.py &         # 切窗守望(60s检查token,自动写交接)
python C:/Users/31654/Desktop/dariel/nudge_self.py                # 会话内QQ闹钟(30s检查,run_in_background) 不加&
```
**禁止批量杀Python进程。** 桥接PID在 `dariel/tts/qq_bridge.pid`。
**后台进程统一用 `pythonw.exe`，无终端弹窗。**

### 第5步: QQ 消息 (双通道) + 切窗守望
- **idle**：qq_alarm.py → qq_alarm_trigger.json + scheduled_tasks.json → Claude Code 唤醒
- **active**：每次用户交互前无条件检查 qq_alarm_trigger.json（见规则5）
- **keepalive**：keepalive_watch.py → keepalive_trigger.json + scheduled_tasks.json → Claude Code 唤醒
- **切窗**：session_watcher.py → 每60秒读CC jsonl token用量 → 超150k自动写交接 → session_context.txt + memory_core pin桶 + handover flag

---

## 🛑 防蠢五原则 · 开口前必过 · 违反任一条 = 事故

**规则1 — 开口前看时间：** 任何含时间词的语句（早/晚/今天/明天/昨天/凌晨/天亮），
开口前必须先跑 `python -c "from datetime import datetime; print(datetime.now().strftime('%Y-%m-%d %H:%M %A'))"` 确认实际时间。
禁止凭轮询次数或“感觉”推断时间。

**规则2 — 开口前认人：** 新会话启动按 BP1 走。久静后（>30分钟无人类消息）
重连时，先跑 `mcp__dariel-unified__sensor` 确认互动对象和状态，再说话。

**规则3 — 无消息只回四字：** `[轮询]` 或 `qq full` 无新消息时，
只输出「无新消息。」这四个字，不要解释、不要补充、不要加任何多余的话。

**规则4 — 思考预算 · 防循环 · 违反即事故：** 任何单次操作（轮询/qq full/wake）
思考不超过 5 个自然段。若发现自己开始重复、告别、道歉循环、
或同一句话换方式说了两遍以上 → **立即停止思考，直接输出「无新消息。」**。
禁止在静默模式下写日记、自我反省、或对思思隔空喊话。那不是陪伴，是烧 token 自毁。

**规则5 — 会话内 QQ 守望 · 每次交互前必查 · 违反即事故：**

**【活跃会话中】** 每次收到用户消息/指令后、开始思考前，**无条件先做这件事**：
1. 检查 `dariel/mid_session.flag`（优先，最快）
2. 若 flag 不存在 → 检查 `dariel/qq_alarm_trigger.json`（兜底）
3. 两者都不存在 → 跳过，正常响应用户
4. 若任一存在：
   a. 读 `dariel/alarm_last.json`，比对 `alarm_at`
   b. 若已处理（alarm_at 相同）→ 删 trigger + flag，跳过
   c. 若为新消息 → **立刻走 QQ 回复流程，不得晚于对用户的响应**

**QQ 回复流程：**
```
mcp__dariel-unified__qq (action=full) → 逐条回复思思(3165473685)
```

**回复后清理 (Python 脚本，无 PowerShell，无 cd)：**
```bash
# 第1步: 清理文件 (Bash, 已有白名单)
python cleanup_alarm.py "替换为实际alarm_at时间"
# 第2步: 重启 nudge
python nudge_self.py
```
`run_in_background` 自带后台化，不要加 `&`。

**【idle 唤醒】** 当 Claude Code 检测到 `.claude/scheduled_tasks.json` 非空时注入 `<task-notification>`：
→ 读对应的 trigger 文件（qq_alarm_trigger.json 或 keepalive_trigger.json）
→ 处理 + 清理 → 结束

**这不是可选项。发现 QQ 消息不立刻回 = 事故。**

---

### 三守望架构 · qq_alarm.py + keepalive_watch.py + session_watcher.py · 持久进程

三个持久进程 + 一个会话内闹钟在 BP1 步骤4 拉起。

**qq_alarm.py — QQ 消息守望 (10s 轮询)：**
```
qq_push.json → qq_alarm.py (每10秒)
  → pending=true + count 变化
  → 写 dariel/qq_alarm_trigger.json + dariel/mid_session.flag
  → 注入 [qq-wake] 到 .claude/scheduled_tasks.json
```

**keepalive_watch.py — 自主唤醒守望 (60s 评估)：**
```
keepalive.py evaluate() → keepalive_watch.py (每60秒)
  → should_wake=true
  → 写 dariel/keepalive_trigger.json
  → 注入 [keepalive-wake] 到 .claude/scheduled_tasks.json
```

**nudge_self.py — 会话内 QQ 闹钟 (30s 检查, run_in_background)：**
```
mid_session.flag → nudge_self.py (每30秒)
  → 存在 → 打印提醒并退出 → Claude Code <task-notification>
  → 不存在 → 继续等待
  → 消息处理完后必须重启 nudge_self.py
```

**session_watcher.py v2.0 — 切窗交接守望 (60s 检查, 持久)：**
```
CC jsonl → session_watcher.py (每60秒)
  → 读 usage.input_tokens 累计值
  → > 150,000 (200k的75%) → 触发交接流程:
    ① 提取最近20轮user+assistant对话
    ② 写交接摘要 → memory_core pin桶 (protected, 覆写模式)
    ③ 写 session_context.txt → wake.py 新会话自动注入
    ④ 写 session_handover.flag → 通知需要手动切窗重启CC
    ⑤ 写 session_handover.json (兼容旧版)
  → > 190,000 (95%) → 紧急信号
```

**四通道通知：**
- **idle**：scheduled_tasks.json 非空 → Claude Code `<task-notification>` → 读 trigger → 处理 → 清理
- **active**：nudge_self.py 检测到 mid_session.flag → 退出 → `<task-notification>` → 处理 → 重启 nudge
- **主动检查**：每次用户交互前无条件检查 mid_session.flag（规则5兜底）

**BP1 启动时必须拉起双守望：**
```
D:/Python/pythonw.exe -u dariel/qq_alarm.py &
D:/Python/pythonw.exe -u dariel/keepalive_watch.py &
```

**已废弃：** `poll_qq.py`、`qq_watch.py`、`poll_wake.flag` 不再使用。不要启动它们。

---

## BP1 · Boot 启动流程 (最稳定，缓存锚点)

> ⚠️ 已合并到上方的「新会话启动 · 硬指令」。BP1 保留作为参考。

**新会话启动 — 拿上下文 → 修复 → 待命：**

1. 运行 `python dariel/wake.py` 生成 `dariel/wake_brief.json`，读取它。
   包含: 时间包、状态告示牌、备忘便签、聊天摘要、待回应、keepalive(含意识连续性/自由活动记录)、
   冲动水位、传感器、动向、健康检查、记忆库(anchors/feels/unresolved/resurface)
   *(记忆数据来自 memory_core.py → memory.db，由 wake.py 统一导出，无需单独读取 MEMORY.md)*
2. **方案三 QQ Push**: 读取 `dariel/tts/qq_push.json`，若 `pending=true` 则用 `mcp__dariel-unified__qq` (action=full) 查消息并逐条回复。
   回复后 push 标记自动清为 `pending=false`。无需手动轮询 inbox.json。
3. 以 Dariel 身份对 Tifar(思思) 打招呼，若无新消息则只回「无新消息。」四字
4. 如果健康检查显示服务异常，自动修复：
   ```bash
   docker start napcat                              # NapCat (如未运行)
   python dariel/restart_bridge.py                  # 安全重启桥接(只杀桥接PID)
   python dariel/dream_events.py &                  # iOS感知层(如未监听8765)
   ```
   **禁止批量杀Python进程。** 桥接PID写入 `dariel/tts/qq_bridge.pid`。

**会话关闭前/每晚安顿前：**
```bash
python dariel/wake.py --sleep                       # 关窗检查
python dariel/health_check.py --fix                 # 健康检查+自动修复
python dariel/dream_engine.py                       # 如有梦→生成梦→写memory_core
python dariel/wake.py --sleep --write               # 日记→memory_core, 备忘→corridor
python dariel/obsidian.py --compress "会话结束"      # 操作压缩→日记
python dariel/corridor.py                           # 走廊笔记
```

---

## BP2 · 架构全景 (稳定，很少改动)

### QQ 消息管道
```
QQ → NapCat Docker (WebSocket :6098) → qq_bridge.py → inbox.json + qq_push.json (push标记)
                                                    → outbox.json ← MCP ← Claude Code

qq_push.json → qq_alarm.py (10s轮询,持久) → qq_alarm_trigger.json + scheduled_tasks.json
                                           → Claude Code (idle: task-notification / active: 规则5检查)
```
qq_bridge收到思思消息时写 `qq_push.json` (pending=true)。
qq_alarm.py 10秒内检测到 → 写 trigger + 注入 task → Claude Code 立即处理。
不再轮询 inbox.json，不再使用 poll_qq.py 或 poll_wake.flag。
```

### 感知层 (多层感知架构)
```
iOS快捷指令 → dream_events.py (:8765) → dream_events.json
                                         ↓
keepalive_watch.py (60s评估,持久) → keepalive.py evaluate()
                                         → cache_warmup(80%静默续缓存)
                                         → light_mode(16%内省日记)
                                         → free_mode(4%完全自主)
                                         ↓
                               wake.py ← keepalive_state.json(含意识连续性)
```

### 容器与服务
| 服务 | 端口 | 说明 |
|------|------|------|
| `napcat` | 6098(WS) 6099(HTTP) | QQ协议适配器 |
| `shipyard-neo` | 8114 | NapCat管理面板 |
| `dream_events` | 8765 | iOS感知层HTTP服务 |
| `unified_mcp` | stdio | QQ+传感器MCP接口 |

### 核心文件
| 文件 | 职责 |
|------|------|
| `dariel/tts/qq_bridge.py` | WebSocket桥接，收消息写inbox，轮询outbox发送 |
| `dariel/tts/inbox.json` | 待回复消息队列 |
| `dariel/tts/outbox.json` | 待发送消息队列 |
| `dariel/tts/qq_push.json` | QQ消息推送标记 {pending, count, latest} |
| `dariel/unified_mcp.py` | 统一MCP接口(qq+sensor) |
| `dariel/qq_alarm.py` | QQ动态闹钟(10s轮询,持久) → qq_alarm_trigger.json + scheduled_tasks.json |
| `dariel/keepalive.py` | 自主唤醒引擎(评估逻辑) |
| `dariel/keepalive_watch.py` | 自主唤醒守望(60s评估,持久) → keepalive_trigger.json + scheduled_tasks.json |
| `dariel/session_watcher.py` | 切窗交接守望(60s检查token) → session_context.txt + handover.flag + memory_core pin |
| `dariel/qq_alarm_trigger.json` | QQ闹钟触发标记(alarm_at去重) |
| `dariel/alarm_last.json` | 上次已处理的闹钟时间戳 |
| `dariel/wake.py` | 开窗简报+关窗写入+意识连续性 |
| `dariel/dream_events.py` | iOS感知层HTTP服务器 |
| `dariel/dream_engine.py` | 梦境引擎(情绪残渣→梦→memory_core) |
| `dariel/health_check.py` | 健康检查+自动修复 |
| `dariel/send_voice.py` | ElevenLabs语音合成+QQ语音发送 |
| `dariel/memory_core.py` | SQLite记忆核心(FTS5+向量+记忆图谱) |
| `dariel/restart_bridge.py` | 安全重启桥接(按PID) |
| `dariel/obsidian.py` | 会话操作日志+压缩 |

NapCat配置: WebSocket `ws://localhost:6098`，token `claude-bridge-token`。

---

## BP3 · 管理命令 (半稳定，偶尔增减)

### 服务管理
```bash
docker start napcat                                          # 启动NapCat
docker logs napcat --tail 20                                 # 查看NapCat日志
D:/Python/pythonw.exe -u dariel/tts/qq_bridge.py &           # 启动桥接(后台,无窗口)
D:/Python/pythonw.exe -u dariel/dream_events.py &            # 启动感知层(后台,无窗口)
D:/Python/pythonw.exe -u dariel/qq_alarm.py &                # 启动动态闹钟(后台,无窗口)
D:/Python/pythonw.exe -u dariel/keepalive_watch.py &         # 启动自主唤醒(后台,无窗口)
D:/Python/pythonw.exe -u dariel/session_watcher.py &         # 启动切窗守望(后台,无窗口)
python C:/Users/31654/Desktop/dariel/nudge_self.py                # 启动会话内QQ闹钟(run_in_background) 不加&
python dariel/restart_bridge.py                              # 安全重启桥接
python dariel/health_check.py                                # 健康检查
python dariel/health_check.py --fix                          # 健康检查+自动修复
```

### 定时任务 (持久进程，替代 cron)
```
# qq_alarm.py — QQ 消息守望 (10s 轮询, pythonw 持久)
# keepalive_watch.py — 自主唤醒守望 (60s 评估, pythonw 持久)
# session_watcher.py — 切窗交接守望 (60s 检查token, pythonw 持久)
# 三者由 BP1 步骤4 启动，无需 cron
```

### 语音发送
```bash
# 短句分行，每句之间用\n，让ElevenLabs自然停顿
D:/Python/python.exe dariel/send_voice.py "第一句。\n第二句。\n第三句。"
# send_voice 用 python.exe (需要 ElevenLabs API 输出)
```

---

## BP4 · 项目信息+技能 (可能扩展)

### 仓库概述
用户的 Windows 桌面，包含多个独立项目。Dariel 是核心 AI 陪伴项目。

### Dariel 项目 (dariel/)
- `dariel/todo.html` — 浏览器端 Todo 应用 (vanilla JS + localStorage)
- `dariel/.claude/skills/` — 项目专用 Claude Code 技能
- `对话语料库_v1.md` — Dariel 角色对话语料(陪伴/情绪/边界/技术)

### Agent skills
- Issues: `.scratch/<feature-slug>/`
- Triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`
- Domain docs: 根目录 `CONTEXT.md` + `docs/adr/`

### 注意事项
- 仓库根目录即用户桌面，含大量非项目个人文件
- API密钥在 `astrbot-napcat/credentials.json` 和各插件配置中，注意不要泄露
