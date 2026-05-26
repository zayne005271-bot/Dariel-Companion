"""QQ <-> Claude Code 桥接 — WebSocket + 自动重连"""

import asyncio
import json
import os
import time
from pathlib import Path
from datetime import datetime

import websockets

BRIDGE_DIR = Path(__file__).parent
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"

NAP_WS = "ws://localhost:6098"
NAP_TOKEN = "claude-bridge-token"

RETRY_DELAYS = [5, 10, 20, 30, 60]  # 指数退避


def log(msg: str):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode(), flush=True)


def init_files():
    if not INBOX_FILE.exists():
        INBOX_FILE.write_text("[]", encoding="utf-8")
    if not OUTBOX_FILE.exists():
        OUTBOX_FILE.write_text("[]", encoding="utf-8")


def read_messages(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def write_messages(path: Path, data: list[dict]):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


async def send_private_msg(ws, user_id: str, message: str):
    payload = {
        "action": "send_private_msg",
        "params": {"user_id": int(user_id), "message": message},
    }
    await ws.send(json.dumps(payload, ensure_ascii=False))
    log(f"[send] -> QQ {user_id}: {message[:60]}...")


async def flush_outbox(ws):
    """发送所有待发消息"""
    outbox = read_messages(OUTBOX_FILE)
    changed = False
    for msg in outbox:
        if msg.get("sent"):
            continue
        uid = msg.get("user_id", "")
        text = msg.get("message", "")
        if uid and text:
            await send_private_msg(ws, uid, text)
            msg["sent"] = True
            msg["sent_at"] = datetime.now().isoformat()
            changed = True
    if changed:
        write_messages(OUTBOX_FILE, outbox)
        log(f"[flush] sent {sum(1 for m in outbox if m.get('sent'))} messages")


async def run():
    init_files()
    log("[bridge] QQ <-> Claude Code bridge started")
    log(f"[bridge] inbox: {INBOX_FILE}")
    log(f"[bridge] outbox: {OUTBOX_FILE}")

    retry_idx = 0

    while True:
        try:
            async with websockets.connect(
                NAP_WS,
                additional_headers={"Authorization": f"Bearer {NAP_TOKEN}"},
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                log("[bridge] connected to NapCat")
                retry_idx = 0  # reset on success

                # poll_outbox handles all sending (avoid dual-send from flush+ poll race)
                poll_task = asyncio.create_task(poll_outbox(ws))

                async for raw_msg in ws:
                    try:
                        data = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    post_type = data.get("post_type", "")
                    message_type = data.get("message_type", "")

                    if post_type == "message" and message_type == "private":
                        sender = data.get("sender", {})
                        user_id = str(sender.get("user_id", ""))
                        nickname = sender.get("nickname", "")
                        message = data.get("raw_message", "")
                        message_id = data.get("message_id", 0)

                        log(f"[recv] QQ {nickname}({user_id}): {message}")

                        inbox = read_messages(INBOX_FILE)
                        inbox.append({
                            "id": str(int(time.time() * 1000)),
                            "user_id": user_id,
                            "nickname": nickname,
                            "message": message,
                            "message_id": message_id,
                            "timestamp": datetime.now().isoformat(),
                            "replied": False,
                        })
                        if len(inbox) > 100:
                            inbox = inbox[-100:]
                        write_messages(INBOX_FILE, inbox)
                        log(f"[bridge] -> inbox")

                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass

        except websockets.ConnectionClosed as e:
            log(f"[bridge] connection closed: {e}")
        except OSError as e:
            log(f"[bridge] connection failed: {e}")
        except Exception as e:
            log(f"[bridge] error: {type(e).__name__}: {e}")

        delay = RETRY_DELAYS[min(retry_idx, len(RETRY_DELAYS) - 1)]
        log(f"[bridge] reconnect in {delay}s...")
        await asyncio.sleep(delay)
        retry_idx += 1


async def poll_outbox(ws):
    """poll outbox and send replies back to QQ"""
    sent_ids = set()  # in-memory guard against re-sends within this session
    while True:
        try:
            outbox = read_messages(OUTBOX_FILE)
            changed = False
            for msg in outbox:
                mid = msg.get("id", "")
                if msg.get("sent") or mid in sent_ids:
                    continue
                retries = msg.get("retries", 0)
                if retries >= 3:
                    msg["sent"] = True  # give up, mark as done to stop loop
                    msg["error"] = "max retries exceeded"
                    changed = True
                    continue
                uid = msg.get("user_id", "")
                text = msg.get("message", "")
                if uid and text:
                    await send_private_msg(ws, uid, text)
                    msg["sent"] = True
                    msg["sent_at"] = datetime.now().isoformat()
                    sent_ids.add(mid)
                    changed = True
                else:
                    msg["retries"] = retries + 1
                    changed = True
            if changed:
                write_messages(OUTBOX_FILE, outbox)
            await asyncio.sleep(2)
        except Exception as e:
            log(f"[outbox error] {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
