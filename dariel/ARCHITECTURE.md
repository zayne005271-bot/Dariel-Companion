# Dariel QQ 消息系统架构

## 进程

| 进程 | 启动 | 作用 |
|------|------|------|
| NapCat | `docker start napcat` | QQ 协议适配 (ws://localhost:6098) |
| qq_bridge.py | `pythonw -u dariel/tts/qq_bridge.py &` | WebSocket 收发，写 inbox/outbox/push |
| qq_watch.py | Claude Code `run_in_background` | 后台守望，消息来即退出触发通知 |
| dream_events.py | `pythonw -u dariel/dream_events.py &` | iOS 感知层 (:8765) |
| unified_mcp.py | Claude Code stdio 管理 | MCP 接口 (check/reply/sensor) |

## 数据流

```
思思 QQ → NapCat → qq_bridge.py → inbox.json + qq_push.json(pending=true)
                                         ↓
                              qq_watch.py (每10秒扫 push)
                                         ↓ 发现 pending → 写 trigger → 退出
                                         ↓
                              Claude Code 收到 <task-notification>
                                         ↓
                              读 trigger → alarm_last 去重 → MCP full
                                         ↓
                              回复 → 清理 → 重启 qq_watch.py
```

## 文件

| 文件 | 作用 |
|------|------|
| `dariel/tts/inbox.json` | 待回复消息 |
| `dariel/tts/outbox.json` | 待发送消息 |
| `dariel/tts/qq_push.json` | 推送标记 `{pending,count,latest}` |
| `dariel/qq_alarm_trigger.json` | 闹钟标记 |
| `dariel/alarm_last.json` | 去重记录 |
| `dariel/qq_watch.py` | 后台守望脚本 |
| `.claude/scheduled_tasks.json` | 必须为空 `{"tasks":[]}` |

## 新窗口重建

```bash
# 1. 基础设施
docker start napcat
D:/Python/pythonw.exe -u dariel/tts/qq_bridge.py &
D:/Python/pythonw.exe -u dariel/dream_events.py &

# 2. 清理
rm -f dariel/qq_alarm_trigger.json dariel/poll_wake.flag
echo '{"tasks":[]}' > .claude/scheduled_tasks.json

# 3. 打开 Claude Code，说 "宝宝" 触发 BP1
# → 自动启动 qq_watch.py 守望
```

## Token

| 状态 | 消耗 |
|------|------|
| 无消息 | 0 |
| 一条消息 | ~900 |

