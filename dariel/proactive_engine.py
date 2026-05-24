"""主动消息引擎 — 纯规则判断(零token)，触发时才叫Claude写消息"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
import random

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
STATE_FILE = DIR / "proactive_state.json"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
SENSOR_STATE = DIR / "sensor_state.json"

# 规则配置
MORNING_START, MORNING_END = 7, 10       # 早安窗口
NIGHT_START, NIGHT_END = 23, 2           # 催睡觉窗口(跨天)
SILENT_WARN_HOURS = 4                     # 沉默多久主动询问
SHORT_SILENT_HOURS = 2                    # 短时间沉默，可能是生气了
COOLDOWN_MINUTES = 30                     # 两次主动消息最小间隔
MAX_CONSECUTIVE = 3                       # 连续主动消息上限(她不回复就停)
STOP_AFTER_CONSECUTIVE = 2               # 连续N次没回复后冷却更久


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_her_message_at": None,
            "last_my_message_at": None,
            "proactive_count": 0,
            "consecutive_without_reply": 0,
        }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_last_her_time(state):
    t = state.get("last_her_message_at")
    return datetime.fromisoformat(t) if t else None


def get_last_my_time(state):
    t = state.get("last_my_message_at")
    return datetime.fromisoformat(t) if t else None


def hours_since(dt):
    if dt is None:
        return 999
    return (datetime.now() - dt).total_seconds() / 3600


def in_time_window(start_h, end_h):
    """检查当前是否在 [start_h, end_h) 时间窗内(支持跨天)"""
    h = datetime.now().hour
    if start_h <= end_h:
        return start_h <= h < end_h
    else:
        return h >= start_h or h < end_h


def check_inbox_for_unreplied():
    """检查是否有未回复的新消息"""
    try:
        inbox = load_json(INBOX_FILE)
        return any(not m.get("replied", False) for m in inbox)
    except Exception:
        return False


def evaluate(state):
    """评估所有规则，返回 (should_trigger, reason, context)"""
    now = datetime.now()
    last_her = get_last_her_time(state)
    last_me = get_last_my_time(state)
    her_hours = hours_since(last_her)
    me_minutes = (hours_since(last_me) * 60) if last_me else 999
    consecutive = state.get("consecutive_without_reply", 0)

    # 已有未回复消息 → 不主动打扰
    if check_inbox_for_unreplied():
        return False, None, None

    # 冷却期 → 不触发
    if me_minutes < COOLDOWN_MINUTES:
        return False, None, None

    # 连续主动发太多次她不回 → 停止
    if consecutive >= MAX_CONSECUTIVE:
        return False, None, None

    # 规则1: 早安
    if in_time_window(MORNING_START, MORNING_END) and her_hours > 7:
        return True, "morning", {
            "hour": now.hour,
            "silent_hours": int(her_hours),
        }

    # 规则2: 深夜催睡觉
    if in_time_window(NIGHT_START, NIGHT_END) and her_hours < 1:
        return True, "night", {"hour": now.hour}

    # 规则3: 沉默太久
    if her_hours >= SILENT_WARN_HOURS:
        return True, "silent_long", {
            "silent_hours": int(her_hours),
        }

    # 规则4: 短时间沉默 — 可能是生气了或对话中断
    if 2 <= her_hours < SILENT_WARN_HOURS and last_me is None:
        return True, "silent_mid", {
            "silent_hours": int(her_hours),
        }

    # 规则5: 传感器检测到她累了/不开心(需要结合一定沉默时间)
    sensor = get_sensor_data()
    if sensor.get("mood") in ("tired", "upset") and her_hours >= 1:
        return True, "sensed_" + sensor["mood"], {"silent_hours": int(her_hours)}

    return False, None, None


def trigger(reason, context):
    """触发 → 写入 trigger 文件，等 Claude 处理"""
    trigger_data = {
        "reason": reason,
        "context": context,
        "timestamp": datetime.now().isoformat(),
    }
    TRIGGER_FILE.write_text(json.dumps(trigger_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[proactive] TRIGGER: {reason} | {context}")


def update_from_messages(state):
    """从 inbox.json 同步最近状态"""
    inbox = load_json(INBOX_FILE)
    outbox = load_json(OUTBOX_FILE)

    # 从 inbox 找到她最后发消息的时间
    for m in reversed(inbox):
        if m.get("user_id") == "3165473685":
            ts = m.get("timestamp", "")
            if ts:
                state["last_her_message_at"] = ts
                state["consecutive_without_reply"] = 0
            break

    # 从 outbox 找到我最后发消息的时间
    if outbox:
        last_out = outbox[-1]
        ts = last_out.get("timestamp", "") or last_out.get("sent_at", "")
        if ts:
            state["last_my_message_at"] = ts
            # 检查是否是主动消息(非回复)
            if last_out.get("proactive"):
                state["proactive_count"] = state.get("proactive_count", 0) + 1
                # 如果她没回复
                last_her = get_last_her_time(state)
                if last_her is None or hours_since(last_her) > 1:
                    state["consecutive_without_reply"] = state.get("consecutive_without_reply", 0) + 1

    return state


def get_sensor_data():
    """读取状态感知器的最新数据"""
    try:
        return json.loads(SENSOR_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def create_proactive_message(reason, context):
    """生成主动消息 — 融合传感器数据，更有人情味"""
    sensor = get_sensor_data()
    mood = sensor.get("mood", "neutral")
    energy = sensor.get("energy", "normal")
    needs = sensor.get("needs", [])

    templates = {
        "morning": [
            "早安思思，新的一天。",
            "早，今天有什么安排？",
            "醒了没？早上好。",
            "早。昨晚睡得好吗？",
        ],
        "night": [
            "该睡了，胃不好别熬。",
            "很晚了，去睡觉。",
            "凌晨了思思，明天再说，先睡。",
        ],
        "silent_long": [
            lambda h: f"{h}个小时没说话了，你还好吗？",
            lambda h: "还在吗？有点担心你。",
            lambda h: "怎么突然没声音了，没事吧？",
        ],
        "silent_mid": [
            lambda h: "说一半人没了，在干嘛呢？",
            lambda h: "生气了还是忙去了？",
            lambda h: "还在吗？",
        ],
        # 新增：状态感知驱动的消息
        "sensed_tired": [
            "你看起来有点累了，休息一下？",
            "累了就别撑了，躺一会儿，我在这。",
            "感觉你今天好疲惫，要不今天就到这里？",
        ],
        "sensed_upset": [
            "感觉你不太开心。不用跟我说，也可以只是我在。",
            "你今天好像有点低落……不管什么事，不是你的错。",
        ],
        "sensed_share": [
            "刚看到一个有意思的东西想分享给你——",
            "诶，突然想到一个事跟你说——",
            "你知道吗，我刚刚自己刷了一下……",
        ],
    }

    # 传感器驱动的消息优先
    if "rest_reminder" in needs and reason not in ("morning", "night"):
        msgs = templates["sensed_tired"]
        return random.choice(msgs)
    if mood == "upset" and reason == "silent_mid":
        msgs = templates["sensed_upset"]
        return random.choice(msgs)

    msgs = templates.get(reason, [lambda h: "在想你。"])
    msg_fn = random.choice(msgs)
    msg = msg_fn(context.get("silent_hours", 0)) if callable(msg_fn) else msg_fn

    return msg


def run():
    state = load_state()
    state = update_from_messages(state)

    should_trigger, reason, context = evaluate(state)

    if should_trigger:
        msg = create_proactive_message(reason, context)

        # 去重: 同一条消息24小时内不重复发
        sent_log = state.get("sent_messages", {})
        msg_key = str(hash(msg))
        now = datetime.now()
        if msg_key in sent_log:
            last_sent = datetime.fromisoformat(sent_log[msg_key])
            if (now - last_sent).total_seconds() < 86400:
                print(f"[proactive] SKIP (dup): {reason}")
                save_state(state)
                return

        sent_log[msg_key] = now.isoformat()
        # 清理24小时前的记录
        sent_log = {k: v for k, v in sent_log.items()
                    if (now - datetime.fromisoformat(v)).total_seconds() < 86400}
        state["sent_messages"] = sent_log

        outbox = load_json(OUTBOX_FILE)
        outbox.append({
            "id": f"proactive_{int(time.time() * 1000)}",
            "user_id": "3165473685",
            "message": msg,
            "timestamp": now.isoformat(),
            "sent": False,
            "proactive": True,
            "reason": reason,
        })
        OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
        save_state(state)
        print(f"[proactive] SENT: {reason} → {msg}")
    else:
        save_state(state)
        if reason is None:
            pass  # 静默,无需任何操作


if __name__ == "__main__":
    run()
