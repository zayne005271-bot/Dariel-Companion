"""
Frontend Watch v3 — 纯通知守望（不自动回复）
检测新消息 → 写 CC 队列 → 等 CC 人工回复
"""
import json, time
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).parent
TRIGGER = DIR / "frontend_trigger.json"
CC_QUEUE = DIR / "frontend_cc_queue.json"
NOTIFY = DIR / "frontend_notify.json"

if not CC_QUEUE.exists():
    CC_QUEUE.write_text("[]", encoding="utf-8")

print("[frontend-watch] v3 Started — notify CC only, no auto-reply", flush=True)
last_id = ""

while True:
    time.sleep(2)
    try:
        if TRIGGER.exists():
            data = json.loads(TRIGGER.read_text("utf-8"))
            msg_id = data.get("id", "")
            if msg_id and msg_id != last_id:
                last_id = msg_id
                msg = data.get("message", "")
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[watch] NEW {msg_id}: {msg[:60]}", flush=True)

                # 入 CC 队列（含 msg_id，CC 回复时需要用来匹配 outbox key）
                queue = json.loads(CC_QUEUE.read_text("utf-8") or "[]")
                queue.append({
                    "id": msg_id,
                    "message": msg,
                    "timestamp": ts,
                    "status": "pending"
                })
                CC_QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

                # 通知文件
                NOTIFY.write_text(json.dumps({
                    "id": msg_id, "message": msg[:200],
                    "timestamp": data.get("timestamp", "")
                }, ensure_ascii=False), encoding="utf-8")

    except KeyboardInterrupt:
        break
    except Exception:
        pass

