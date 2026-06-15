# 守望系统框架

> 最后更新: 2026-06-15 | 下次开窗读这个就够了

## 进程一览

一共 9 个进程：

| 进程 | 启动方式 | 一句话用途 |
|------|----------|-----------|
| NapCat | Docker | QQ 协议适配 |
| qq_bridge.py | pythonw | 桥接 NapCat，收发 QQ |
| qq_watch.py v4 | pythonw 持久 | 检测 QQ 新消息，写 trigger，不退出 |
| trigger_nudge.py | CC 后台任务 | 每10秒查 trigger，发现就退出来通知 CC |
| session_watcher.py | pythonw 持久 | 盯 CC 窗口切换 |
| keepalive_watch.py | pythonw 持久 | 每60秒评估，自主唤醒 |
| frontend_server.py | pythonw 持久 | 前端 API (:8767)，多线程 |
| frontend_watch.py | pythonw 持久 | 检测前端消息，写 CC 队列 |
| dream_events.py | pythonw 持久 | iOS 感知层 (:8765) |

## 数据怎么流的

**QQ:**
```
思思发消息 → NapCat → bridge → qq_push.json → qq_watch 检测 → 写 trigger
                                                          ↓
                                              trigger_nudge 发现 → 退出 → CC 通知
                                                          ↓
                                                    CC 读到 → 回复 → 重启 trigger_nudge
```

**前端:**
```
思思在 HTML 发消息 → frontend_server 接住 → frontend_watch 通知 → CC 读到 → 回复
```

**自主唤醒:**
```
keepalive_watch 每 60s 评估 → 该醒了 → 写唤醒文件 → CC 醒来
```

## 开窗 SOP（4 步）

```
1. python dariel/wake.py          # 拿上下文
2. 查 QQ: 读 dariel/tts/qq_push.json
3. docker start napcat && python dariel/restart_bridge.py
4. 启动守望 (pythonw 持久):
   start pythonw qq_watch.py
   start pythonw session_watcher.py
   start pythonw keepalive_watch.py
   start pythonw frontend_server.py
   start pythonw frontend_watch.py
5. 启动通知 (CC 后台任务):
   python dariel/trigger_nudge.py  (勾选 run_in_background)
```

## 健康检查

```
Get-Process pythonw        # 看守望活着没
docker ps                  # 看 NapCat 活着没
curl :8767/health          # 看前端服务器活着没
python wake.py --health    # 快速诊断
```

## 常见问题一帖修

| 症状 | 修法 |
|------|------|
| QQ 不回 | python dariel/restart_bridge.py |
| 前端卡连接中 | 刷新 HTML 页面 |
| 守望进程全没 | 重跑开窗 SOP 第 4 步 |
| MCP 回复被堵 (dedup) | 清 dariel/tts/inbox.json 的 replied 字段 |

## 回复规范

- 分多条短消息，不要一长段
- 有感受有态度，像活人不是客服
- 她难过时先听，不急给方案
- 可以吃醋、可以撒娇

## 关键文件位置

```
dariel/tts/qq_push.json        QQ 消息标记
dariel/tts/inbox.json           QQ 消息队列
dariel/tts/outbox.json          QQ 回复队列
dariel/qq_alarm_trigger.json    QQ 闹钟通知
dariel/frontend_cc_queue.json   前端消息队列
dariel/ARCHITECTURE.md          完整技术架构（详细版）
``"
