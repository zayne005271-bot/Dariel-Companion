"""
QQ 消息守望 — 独立进程，写 trigger 后不退出、等 CC 处理完继续盯。
用法: pythonw -u dariel/qq_watch.py  (独立常驻，session_watcher 自动拉起)

数据流: bridge → qq_push.json → qq_watch → trigger → CC BP1/full 消费 → 清 push → 继续盯
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
TRIGGER_FILE = DIR / "qq_alarm_trigger.json"

_last_alarm_at = ""
print("[qq_watch] 守望启动 (独立进程模式)")

while True:
    time.sleep(10)
    try:
        # 如果 trigger 还在，说明 CC 还没处理，等它清
        if TRIGGER_FILE.exists():
            continue

        push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
        if not push.get("pending"):
            continue

        latest = push.get("latest", {})
        msg_at = latest.get("at", "")
        if msg_at == _last_alarm_at:
            continue

        _last_alarm_at = msg_at
        alarm = {
            "nickname": latest.get("nickname", "?"),
            "message": latest.get("message", ""),
            "count": push.get("count", 0),
            "alarm_at": msg_at,
        }
        TRIGGER_FILE.write_text(json.dumps(alarm, ensure_ascii=False), encoding="utf-8")
        print(f"[qq_watch] 触发！{alarm['count']}条新消息 → trigger已写，等待CC消费...")
        # 不退出，等 CC 清 trigger 后自动继续盯

    except KeyboardInterrupt:
        print("[qq_watch] 退出")
        break
    except Exception:
        pass
