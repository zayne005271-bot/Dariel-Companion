"""
Dariel QQ 回复助手
用法: python _reply.py "回复内容"
自动: 写 outbox → 标记 inbox → 清 push → 删 flag
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

DIR = Path(__file__).parent
BRIDGE = DIR / "tts"
OUTBOX = BRIDGE / "outbox.json"
INBOX = BRIDGE / "inbox.json"
PUSH = BRIDGE / "qq_push.json"
FLAG = DIR / "poll_wake.flag"
CST = timezone(timedelta(hours=8))

def main():
    reply_text = sys.argv[1] if len(sys.argv) > 1 else "嗯"
    now = datetime.now(CST).isoformat()
    reply_id = f"reply_{int(datetime.now(CST).timestamp() * 1000)}"

    # 读 push 拿 user_id
    try:
        push = json.loads(PUSH.read_text(encoding="utf-8"))
        user_id = push.get("latest", {}).get("user_id", "")
        her_msg = push.get("latest", {}).get("message", "")
    except Exception:
        user_id = ""
        her_msg = ""

    # 1. 写 outbox
    try:
        outbox = json.loads(OUTBOX.read_text(encoding="utf-8"))
    except Exception:
        outbox = []

    outbox.append({
        "id": reply_id,
        "user_id": user_id,
        "message": reply_text,
        "created_at": now,
        "sent": False,
    })
    OUTBOX.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[reply] outbox: {reply_text[:60]}")

    # 2. 标记 inbox
    try:
        inbox = json.loads(INBOX.read_text(encoding="utf-8"))
        for msg in inbox:
            if not msg.get("replied"):
                msg["replied"] = True
                msg["reply_id"] = reply_id
                msg["replied_at"] = now
        INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[reply] inbox marked")
    except Exception as e:
        print(f"[reply] inbox skip: {e}")

    # 3. 清 push
    PUSH.write_text(
        json.dumps({"pending": False, "count": 0, "latest": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[reply] push cleared")

    # 4. 删 flag
    if FLAG.exists():
        FLAG.unlink()
        print("[reply] flag removed")

    # 5. 更新 conv_state
    try:
        conv_file = BRIDGE / "conv_state.json"
        conv = json.loads(conv_file.read_text(encoding="utf-8"))
        conv["last_she_said"] = her_msg
        conv["last_i_said"] = reply_text
        conv["summary"] = f"「{her_msg[:40]}」→「{reply_text[:40]}」"
        conv["updated"] = now
        conv_file.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[reply] conv_state updated")
    except Exception:
        pass

    print("[reply] done")


if __name__ == "__main__":
    main()
