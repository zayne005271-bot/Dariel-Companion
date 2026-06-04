"""
统一看门狗 — 同时盯 QQ 消息 + keepalive 触发
每 3 分钟查 QQ push，每 30 秒查 keepalive trigger。
有动静写统一 flag，Claude Code 里一个 bash 闹钟全搞定。
"""

import json
import time
import os as _os
from pathlib import Path
from datetime import datetime, timezone, timedelta

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
KA_TRIGGER = DIR / "keepalive_trigger.json"
FLAG_FILE = DIR / "poll_wake.flag"
PID_FILE = DIR / "poll_qq.pid"
LOG_FILE = DIR / "poll_qq.log"

CST = timezone(timedelta(hours=8))
QQ_INTERVAL = 180   # QQ 3 分钟查一次
KA_INTERVAL = 30    # keepalive 30 秒查一次 (更频繁，不miss)
_qq_last = 0
_ka_last = 0


def pid():
    PID_FILE.write_text(str(_os.getpid()), encoding="utf-8")


def now():
    return datetime.now(CST)


def active():
    t = now().hour * 60 + now().minute
    return t >= 360 or t < 120  # 6:00 - 02:00 次日 (凌晨2-6静默)


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


def check_qq():
    """检查 QQ 消息，有则写 flag"""
    try:
        push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    if not push.get("pending"):
        return

    latest = push.get("latest", {})
    flag = {
        "type": "qq",
        "pending": True,
        "count": push.get("count", 0),
        "nickname": latest.get("nickname", ""),
        "user_id": latest.get("user_id", ""),
        "message": latest.get("message", ""),
        "at": latest.get("at", ""),
        "flagged_at": now().isoformat(),
    }
    FLAG_FILE.write_text(json.dumps(flag, ensure_ascii=False), encoding="utf-8")
    log(f"QQ flag: {push.get('count')} msg(s) from {latest.get('nickname','?')}")


def check_keepalive():
    """检查 keepalive trigger，有则写 flag"""
    try:
        trigger = json.loads(KA_TRIGGER.read_text(encoding="utf-8"))
    except Exception:
        return

    flag = {
        "type": "keepalive",
        "pending": True,
        "reason": trigger.get("reason", ""),
        "prompt": trigger.get("prompt", "")[:500],
        "timestamp": trigger.get("timestamp", ""),
        "flagged_at": now().isoformat(),
    }
    FLAG_FILE.write_text(json.dumps(flag, ensure_ascii=False), encoding="utf-8")
    log(f"KA flag: {trigger.get('reason','?')}")


def main():
    global _qq_last, _ka_last
    pid()
    log(f"start PID={_os.getpid()} QQ={QQ_INTERVAL}s KA={KA_INTERVAL}s active=6:00-02:00")
    t0 = time.time()

    while True:
        try:
            if not active():
                time.sleep(30)
                continue

            elapsed = time.time() - t0

            # QQ: 每 3 分钟
            if elapsed - _qq_last >= QQ_INTERVAL:
                check_qq()
                _qq_last = elapsed

            # keepalive: 每 30 秒
            if elapsed - _ka_last >= KA_INTERVAL:
                check_keepalive()
                _ka_last = elapsed

            time.sleep(5)

        except KeyboardInterrupt:
            log("stopped")
            break
        except Exception as e:
            log(f"err: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
