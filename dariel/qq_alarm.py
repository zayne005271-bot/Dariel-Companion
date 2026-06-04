"""
QQ 消息闹钟 v3 — 动态唤醒 Claude Code
有消息 → 往 scheduled_tasks.json 插一次性任务叫醒 Claude → Claude 回复后自删
没消息 → 任务列表空 → Claude Code 零唤醒 → 零 token
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
PUSH_FILE = DIR / "tts" / "qq_push.json"
TRIGGER_FILE = DIR / "qq_alarm_trigger.json"
TASK_FILE = Path.home() / "Desktop" / ".claude" / "scheduled_tasks.json"
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


def add_wake_task():
    """往 Claude Code 的 scheduled_tasks.json 插入一条一次性闹钟"""
    try:
        tasks = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        tasks = {"tasks": []}

    # 不重复插入
    for t in tasks.get("tasks", []):
        if t.get("id") == "qq-wake":
            log("wake task already pending, skip")
            return

    wake_task = {
        "id": "qq-wake",
        "cron": "* * * * *",
        "prompt": "[qq-wake]",
        "recurring": True,  # Claude Code 只执行 recurring 任务；回复后自删
    }
    tasks.setdefault("tasks", []).append(wake_task)

    tmp = TASK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TASK_FILE)
    log("wake task injected")


log("start v3 (dynamic wake)")

_last_pending_count = 0

while True:
    try:
        time.sleep(10)
        try:
            push = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            push = {"pending": False, "count": 0}

        if push.get("pending") and push.get("count", 0) != _last_pending_count:
            latest = push.get("latest", {})
            nick = latest.get("nickname", "?")
            msg = latest.get("message", "")
            log(f"PUSH: {nick}: {msg} (count={push['count']})")

            # 写 trigger 文件（给 Claude Code 读上下文）
            alarm = {
                "nickname": nick,
                "message": msg,
                "count": push["count"],
                "alarm_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            TRIGGER_FILE.write_text(
                json.dumps(alarm, ensure_ascii=False), encoding="utf-8"
            )
            _last_pending_count = push["count"]

            # 注入一次性闹钟，叫醒 Claude Code
            add_wake_task()

    except KeyboardInterrupt:
        log("stopped")
        break
    except Exception as e:
        log(f"loop error: {e}")
        time.sleep(10)
