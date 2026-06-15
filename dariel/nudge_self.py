"""守望备份 — 每15秒检查 trigger，兜底 qq_watch 漏报。

用法: 作为 Claude Code run_in_background 任务启动。
trigger 存在 → 退出 → CC <task-notification>。
处理完后重启守望。
"""
import time, json
from pathlib import Path

DIR = Path(__file__).parent
TRIGGER = DIR / "qq_alarm_trigger.json"

print(f"[nudge] 守望备份启动，盯 {TRIGGER}")

while True:
    if TRIGGER.exists():
        try:
            data = json.loads(TRIGGER.read_text(encoding="utf-8"))
            count = data.get("count", "?")
            msg_text = data.get("message", "")[:60]
        except Exception:
            count = "?"
            msg_text = "?"

        print(f"[nudge] QQ 有 {count} 条新消息: {msg_text} — 立刻 mcp__qq full 回复！")
        break

    time.sleep(15)
