"""QQ <-> Claude Code 桥接 — WebSocket + 自动重连"""

import asyncio
import json
import os
import time
from pathlib import Path
from datetime import datetime

import websockets

# 导入keepalive的update_last_chat，收消息时实时更新心跳状态
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from keepalive import update_last_chat, load_state, save_state as keepalive_save_state

BRIDGE_DIR = Path(__file__).parent
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
PID_FILE = BRIDGE_DIR / "qq_bridge.pid"
PUSH_FILE = BRIDGE_DIR / "qq_push.json"  # 方案三: push标记，避免轮询烧上下文

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


def push_notify(user_id: str, nickname: str, message: str):
    """方案三: 写push标记文件，让Claude在被唤醒时直接感知新消息，
    无需每3分钟轮询inbox.json烧上下文。

    v2: 直接写 alarm trigger + mid_session.flag，事件驱动零延迟。
    qq_alarm.py 保留作为兜底/健康检查。
    """
    now_iso = datetime.now().isoformat()
    push_data = {
        "pending": True,
        "count": 1,
        "latest": {
            "user_id": user_id,
            "nickname": nickname,
            "message": message[:200],
            "at": now_iso,
        },
    }
    # 如果已有未消费的push，累加count
    try:
        existing = json.loads(PUSH_FILE.read_text(encoding="utf-8"))
        if existing.get("pending"):
            push_data["count"] = existing.get("count", 0) + 1
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    tmp = PUSH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(push_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PUSH_FILE)
    log(f"[push] flag written for {nickname}({user_id}), count={push_data['count']}")

    # ── v2: 事件驱动 · 直接写 trigger，零延迟 ──
    _write_alarm_trigger(user_id, nickname, message, push_data["count"], now_iso)


def _write_alarm_trigger(user_id: str, nickname: str, message: str, count: int, alarm_at: str):
    """直接写 alarm trigger 文件，让 CC/nudge 立即感知，跳过 qq_alarm 轮询延迟。

    qq_alarm.py 保留作为兜底：如果 bridge 挂了重启后 trigger 没写，
    qq_alarm 仍能在 10s 内补写。
    """
    dariel_dir = BRIDGE_DIR.parent
    trigger_file = dariel_dir / "qq_alarm_trigger.json"
    mid_session_flag = dariel_dir / "mid_session.flag"
    tasks_file = Path.home() / ".claude" / "scheduled_tasks.json"

    trigger_data = {
        "nickname": nickname,
        "message": message[:200],
        "count": count,
        "alarm_at": alarm_at,
    }
    try:
        tmp = trigger_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(trigger_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(trigger_file)
        log(f"[bridge→trigger] qq_alarm_trigger.json written")
    except Exception as e:
        log(f"[bridge→trigger] FAIL: {e}")

    # mid_session.flag — 会话内 nudge 检测
    try:
        mid_session_flag.write_text(alarm_at)
        log(f"[bridge→trigger] mid_session.flag written")
    except Exception as e:
        log(f"[bridge→trigger] mid_session.flag FAIL: {e}")

    # scheduled_tasks.json — idle 唤醒
    try:
        tasks_dir = tasks_file.parent
        if not tasks_dir.exists():
            tasks_dir.mkdir(parents=True, exist_ok=True)
        if tasks_file.exists():
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
        else:
            tasks = {}
        tasks["qq-wake"] = {
            "type": "qq-wake",
            "trigger": "qq_alarm_trigger.json",
            "alarm_at": alarm_at,
            "created_at": alarm_at,
        }
        tmp = tasks_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(tasks_file)
        log(f"[bridge→trigger] scheduled_tasks.json updated")
    except Exception as e:
        log(f"[bridge→trigger] scheduled_tasks.json FAIL: {e}")


async def send_private_msg(ws, user_id: str, message: str):
    payload = {
        "action": "send_private_msg",
        "params": {"user_id": int(user_id), "message": message},
    }
    # ensure_ascii=True：中文转\uXXXX，避开WebSocket编码碎裂
    await ws.send(json.dumps(payload, ensure_ascii=True))
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
    # write PID for safe restarts — never kill all python, only kill this PID
    PID_FILE.write_text(str(os.getpid()))
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

                        # 思思的消息 → push标记 (由*/3轮询任务消费)
                        if user_id == "3165473685":
                            push_notify(user_id, nickname, message)
                            # 实时更新last_chat_at，修复心跳状态滞后bug
                            try:
                                st = load_state()
                                st = update_last_chat(st)
                                keepalive_save_state(st)
                            except Exception:
                                pass  # 不影响主流程

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
