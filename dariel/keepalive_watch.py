"""Keepalive 守望 --- 每60秒评估一次，有触发则注入 scheduled_tasks.json

替代 Linux cron，在 Windows 上持久运行。
qq_alarm.py 负责 QQ 消息唤醒，本脚本只负责 keepalive 自主唤醒。
"""

import time
import json
import sys
import os as _os
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))

from keepalive import (
    load_state, save_state, update_last_chat, evaluate, format_wakeup_prompt,
    save_json, now_cst, cache_warmup, session_handover, HANDOVER_ON_FREE,
)

TASK_FILE = Path.home() / "Desktop" / ".claude" / "scheduled_tasks.json"
TRIGGER_FILE = DIR / "keepalive_trigger.json"
PID_FILE = DIR / "keepalive_watch.pid"
LOG_FILE = DIR / "keepalive_watch.log"


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def inject_task(task_id, reason):
    try:
        tasks = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        tasks = {"tasks": []}

    for t in tasks.get("tasks", []):
        if t.get("id") == task_id:
            return False  # already pending

    tasks.setdefault("tasks", []).append({
        "id": task_id,
        "cron": "* * * * *",
        "prompt": f"[{task_id}]",
        "recurring": True,
    })
    tmp = TASK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TASK_FILE)
    log(f"task injected: {task_id} ({reason})")
    return True


def main():
    PID_FILE.write_text(str(_os.getpid()), encoding="utf-8")
    log(f"start PID={_os.getpid()} interval=60s")

    while True:
        try:
            state = load_state()
            state = update_last_chat(state)

            should_wake, reason, context = evaluate(state)

            if should_wake:
                mode = context.get("mode", "")
                # 自由模式: 先自动切窗落地，再唤醒AI
                if HANDOVER_ON_FREE and mode == "free":
                    try:
                        handover_result = session_handover()
                        log(f"handover: {handover_result['steps']}")
                    except Exception as e:
                        log(f"handover_failed: {e}")

                prompt = format_wakeup_prompt(state, reason, context)
                trigger = {
                    "reason": reason,
                    "context": context,
                    "prompt": prompt,
                    "timestamp": now_cst().isoformat(),
                }
                save_json(TRIGGER_FILE, trigger)
                inject_task("keepalive-wake", reason)
                # 更新状态，防止下一轮重复触发
                state["last_keepalive_at"] = now_cst().isoformat()
                state["keepalive_count_today"] = state.get("keepalive_count_today", 0) + 1
                save_state(state)
                log(f"fired: {reason} (mode={mode})")
            else:
                # 不唤醒也更新 last_keepalive_at，防止重复评估
                if reason == "cache_warmup":
                    warmed = cache_warmup()
                    if warmed:
                        log(f"cache_warmup: {warmed} files")
                state["last_keepalive_at"] = now_cst().isoformat()
                save_state(state)

            time.sleep(60)

        except KeyboardInterrupt:
            log("stopped")
            break
        except Exception as e:
            log(f"err: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
