"""
QQ 消息轮询守护进程
每 3 分钟检查 qq_push.json，有新消息写 poll_wake.flag。
Claude Code 中的 Dariel 读到 flag 后亲自回复。
"""

import json
import time
import os as _os
from pathlib import Path
from datetime import datetime, timezone, timedelta

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
FLAG_FILE = DIR / "poll_wake.flag"
PID_FILE = DIR / "poll_qq.pid"
LOG_FILE = DIR / "poll_qq.log"

CST = timezone(timedelta(hours=8))
INTERVAL = 180


def pid():
    PID_FILE.write_text(str(_os.getpid()), encoding="utf-8")


def now():
    return datetime.now(CST)


def active():
    t = now().hour * 60 + now().minute
    return 390 <= t <= 1380  # 6:30 - 23:00


def log(msg):
    line = f"[{now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def check():
    try:
        push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    if not push.get("pending"):
        return

    latest = push.get("latest", {})
    flag = {
        "pending": True,
        "count": push.get("count", 0),
        "nickname": latest.get("nickname", ""),
        "user_id": latest.get("user_id", ""),
        "message": latest.get("message", ""),
        "at": latest.get("at", ""),
        "flagged_at": now().isoformat(),
    }
    FLAG_FILE.write_text(json.dumps(flag, ensure_ascii=False), encoding="utf-8")
    log(f"flag set: {push.get('count')} msg(s) from {latest.get('nickname','?')}")


def main():
    pid()
    log(f"start PID={_os.getpid()} interval={INTERVAL}s 6:30-23:00")

    while True:
        try:
            if active():
                check()
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            log("stopped")
            break
        except Exception as e:
            log(f"err: {e}")
            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
