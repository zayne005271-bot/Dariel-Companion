"""
trigger_nudge — CC background task
每10秒检查 qq_alarm_trigger.json，发现新消息退出通知CC
用法: CC run_in_background: python dariel/trigger_nudge.py
处理完后必须重启本任务
"""
import time, os, json
from pathlib import Path

DIR = Path(__file__).parent
TRIGGER = DIR / "qq_alarm_trigger.json"
_last_data = ""

print("[trigger_nudge] Watching every 10s...", flush=True)

while True:
    time.sleep(10)
    try:
        if TRIGGER.exists():
            data = TRIGGER.read_text("utf-8").strip()
            if data and data != _last_data:
                _last_data = data
                alarm = json.loads(data)
                cnt = alarm.get('count', 0)
                print(f'[trigger_nudge] {cnt}条新消息! 退出通知CC', flush=True)
                os._exit(0)
    except KeyboardInterrupt:
        break
    except Exception:
        pass
