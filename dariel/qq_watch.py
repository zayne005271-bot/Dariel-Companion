"""
QQ 消息守望 v4 — 持久守望，不退出
- 自动清理旧 trigger（push 已消费 = trigger 过期）
- 检测新消息写 trigger，不退出，继续守望
- 不用手动重启，不用手动清 trigger

用法: pythonw dariel/qq_watch.py  (pythonw 持久进程)
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
TRIGGER_FILE = DIR / "qq_alarm_trigger.json"

_last_alarm_at = ""
print("[qq_watch v4] 持久守望启动 (pythonw, 不退出)", flush=True)

while True:
    time.sleep(3)
    try:
        push_raw = PUSH_FILE.read_text(encoding="utf-8")
        push = json.loads(push_raw)

        # === 自动清理：如果 trigger 还在但 push 已消费，清掉 ===
        if TRIGGER_FILE.exists() and not push.get("pending"):
            TRIGGER_FILE.unlink()
            _last_alarm_at = ""
            print("[qq_watch] 旧 trigger 已自动清理 (push已消费)", flush=True)

        if not push.get("pending"):
            continue

        latest = push.get("latest", {})
        msg_at = latest.get("at", "")
        if not msg_at or msg_at == _last_alarm_at:
            continue

        _last_alarm_at = msg_at
        alarm = {
            "nickname": latest.get("nickname", "?"),
            "message": latest.get("message", ""),
            "count": push.get("count", 0),
            "alarm_at": msg_at,
        }
        TRIGGER_FILE.write_text(json.dumps(alarm, ensure_ascii=False), encoding="utf-8")
        print(f"[qq_watch] {alarm['count']}条新消息 → trigger已写", flush=True)
        # 不退出，继续守望下一轮

    except KeyboardInterrupt:
        print("[qq_watch] 退出")
        break
    except Exception:
        pass
