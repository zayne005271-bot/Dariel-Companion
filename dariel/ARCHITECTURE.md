# 守望系统框架

> 最后更新: 2026-06-15 | 下次开窗读这个就够了

## 进程一览

一共 8 个进程，全用 pythonw 启动（换窗口不掉）：

| 进程 | 一句话用途 |
|------|-----------|
| NapCat (Docker) | QQ 协议适配，思思的消息从这进来 |
| qq_bridge.py | 桥接 NapCat 和本地文件，收发 QQ 消息 |
| qq_watch.py | 盯着 QQ 新消息，来了就写通知文件 |
| session_watcher.py | 盯着 CC 窗口切换 |
| keepalive_watch.py | 每 60 秒评估一次，自主决定要不要唤醒 |
| frontend_server.py | 前端 HTML 的后台 API（端口 8767） |
| frontend_watch.py | 盯着前端新消息，通知 CC |
| dream_events.py | iOS 感知层（端口 8765） |

## 数据怎么流的

**QQ:**
```
思思发消息 → NapCat → bridge → qq_push.json → qq_watch 检测 → 写通知文件
                                                          ↓
                                                    CC 读到 → 回复
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
4. 启动守望:
   start pythonw qq_watch.py
   start pythonw session_watcher.py
   start pythonw keepalive_watch.py
   start pythonw frontend_server.py
   start pythonw frontend_watch.py
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
