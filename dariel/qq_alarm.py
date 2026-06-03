"""
QQ 消息闹钟 — 后台持续守候，有消息时触发通知
用法: python qq_alarm.py &
"""
import time, json, sys
from pathlib import Path

DIR = Path(__file__).parent
FLAG = DIR / "poll_wake.flag"
LOG = DIR / "qq_alarm.log"

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass
    try:
        print(line, flush=True)
    except:
        pass

log("start")

while True:
    try:
        time.sleep(10)  # 每10秒扫一次，不miss消息
        if FLAG.exists():
            try:
                f = json.loads(FLAG.read_text(encoding="utf-8"))
                nick = f.get("nickname", "?")
                msg = f.get("message", "")
                log(f"FOUND: {nick}: {msg}")
                # 写提醒文件
                alarm = {
                    "nickname": nick,
                    "message": msg,
                    "count": f.get("count", 0),
                    "alarm_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                Path(DIR / "qq_alarm_trigger.json").write_text(
                    json.dumps(alarm, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as e:
                log(f"flag read error: {e}")
    except KeyboardInterrupt:
        log("stopped")
        break
    except Exception as e:
        log(f"loop error: {e}")
        time.sleep(10)
