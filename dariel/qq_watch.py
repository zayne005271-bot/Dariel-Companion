"""
QQ 消息守望 — 后台轮询，消息来就写 trigger 并退出，触发 CC task-notification。
用法: python qq_watch.py  (作为 Claude Code 的 run_in_background 任务)

数据流: bridge → qq_push.json(pending=true) → qq_watch → trigger → 退出 → CC 通知
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
TRIGGER_FILE = DIR / "qq_alarm_trigger.json"

print("[qq_watch] QQ守望启动")

_last_alarm_at = ""
while True:
    time.sleep(10)
    try:
        push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
        if not push.get("pending"):
            continue

        latest = push.get("latest", {})
        msg_at = latest.get("at", "")
        # 避免同一条消息反复触发：比较消息时间戳
        if msg_at == _last_alarm_at:
            continue

        _last_alarm_at = msg_at
        alarm = {
            "nickname": latest.get("nickname", "?"),
            "message": latest.get("message", ""),
            "count": push.get("count", 0),
            "alarm_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        TRIGGER_FILE.write_text(json.dumps(alarm, ensure_ascii=False), encoding="utf-8")
        print(f"[qq_watch] 触发！{alarm['count']}条新消息，退出通知CC...")
        # 退出 → CC 收到 <task-notification>
        break
    except KeyboardInterrupt:
        break
    except Exception:
        pass
