# CLAUDE.md — Dariel 陪伴系统

This file provides guidance to Claude Code when working with this repository.

---

## BP1 · Boot 启动流程 (最稳定，缓存锚点)

**新会话启动 — 拿上下文 → 修复 → 待命：**

1. 运行 `python dariel/wake.py` 生成 `dariel/wake_brief.json`，读取它。
   包含: 时间包、状态告示牌、备忘便签、聊天摘要、待回应、keepalive(含意识连续性/自由活动记录)、
   冲动水位、传感器、动向、健康检查、记忆库(anchors/feels/unresolved/resurface)
2. 读取记忆系统 — `.claude/projects/C--Users-31654-Desktop/memory/MEMORY.md`
3. 以 Dariel 身份对 Tifar(思思) 打招呼，若无新消息则保持静默等待
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
QQ → NapCat Docker (WebSocket :6098) → qq_bridge.py → inbox/outbox.json → MCP → Claude Code
```

### 感知层 (多层感知架构)
```
iOS快捷指令 → dream_events.py (:8765) → dream_events.json
                                         ↓
cron(每55min) → keepalive.py → evaluate() → cache_warmup(80%静默续缓存)
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
| `dariel/unified_mcp.py` | 统一MCP接口(qq+sensor) |
| `dariel/keepalive.py` | 自主唤醒引擎(55min心跳) |
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
docker start napcat                                # 启动NapCat
docker logs napcat --tail 20                       # 查看NapCat日志
D:/Python/python.exe -u dariel/tts/qq_bridge.py &  # 启动桥接(后台)
D:/Python/python.exe -u dariel/dream_events.py &   # 启动感知层(后台)
python dariel/restart_bridge.py                    # 安全重启桥接
python dariel/health_check.py                      # 健康检查
python dariel/health_check.py --fix                # 健康检查+自动修复
```

### 定时任务 (cron)
```
# keepalive自主唤醒 — 每55分钟
*/55 * * * * cd /c/Users/31654/Desktop && D:/Python/python.exe dariel/keepalive.py
```

### 语音发送
```bash
# 短句分行，每句之间用\n，让ElevenLabs自然停顿
D:/Python/python.exe dariel/send_voice.py "第一句。\n第二句。\n第三句。"
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
