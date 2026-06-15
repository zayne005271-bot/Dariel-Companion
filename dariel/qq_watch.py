"""
QQ 消息守望 v2 — 持久守护，触发后不退出，继续盯梢
用法: python qq_watch.py  (作为 Claude Code 的 run_in_background 任务)

与 v1 的区别:
- v1: 发现消息 → 写 trigger → 退出 → CC 收到通知 (一次性)
- v2: 发现消息 → 写 trigger → 等 trigger 被清理 → 继续盯 (持久化)
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
TRIGGER_FILE = DIR / "qq_alarm_trigger.json"

_last_alarm_at = ""
_triggered = False  # 标记是否已触发，等 trigger 被清理后重置

print("[qq_watch v2] QQ守望启动，盯梢中...")

while True:
    time.sleep(5)  # v2: 5秒轮询，比v1的10秒更快
    try:
        # 如果上次触发后 trigger 还没被清理，跳过（等 CC 处理后清理 trigger 再继续）
        if _triggered:
            if TRIGGER_FILE.exists():
                continue  # trigger 还在，等 CC 处理
            else:
                _triggered = False  # trigger 被清理了，恢复盯梢
                print("[qq_watch v2] trigger已清理，继续盯梢")

        push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
        if not push.get("pending"):
            continue

        latest = push.get("latest", {})
        msg_at = latest.get("at", "")
        # 避免同一条消息反复触发
        if msg_at == _last_alarm_at:
            continue

        _last_alarm_at = msg_at
        alarm = {
            "nickname": latest.get("nickname", "?"),
            "message": latest.get("message", ""),
            "count": push.get("count", 0),
            "alarm_at": msg_at,  # 用消息时间戳，更精确
        }
        TRIGGER_FILE.write_text(json.dumps(alarm, ensure_ascii=False), encoding="utf-8")
        _triggered = True
        print(f"[qq_watch v2] 触发！{alarm['count']}条新消息 from {alarm['nickname']}，等待CC处理...")
        # v2: 不退出！等 trigger 被清理后继续盯

    except KeyboardInterrupt:
        print("[qq_watch v2] 退出")
        break
    except Exception as e:
        # 静默吞掉，避免文件读取竞态导致崩溃
        pass
