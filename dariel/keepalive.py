"""自主唤醒引擎 — 55分钟醒一次，自己决定做什么

双层设计:
- cache_warmup: 距上次聊天 < 55分钟 → 静默，不触发
- keepalive_check: 距上次聊天 > 55分钟 → 带完整上下文唤醒AI

核心理念: AI不是定时推送，是有自己的活动空间。
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime, timedelta

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
STATE_FILE = DIR / "keepalive_state.json"
LOG_FILE = DIR / "keepalive_log.json"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
SENSOR_STATE = DIR / "sensor_state.json"
IMPULSE_STATE = DIR / "impulse_state.json"

# 唤醒配置
MIN_INTERVAL_MINUTES = 55        # 两次keepalive最短间隔
ACTIVE_START, ACTIVE_END = 8, 1  # 活跃时段 (8am - 1am 次日)
LIGHT_MODE_PROB = 0.8            # 80% 轻量模式
COOLDOWN_AFTER_HER = 15          # 她刚发过消息，15分钟内不主动唤醒

# 可用的行动
ACTIONS = ["none", "message", "diary", "qzone", "xhs", "explore"]


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state():
    default = {
        "last_chat_at": None,           # 上次和她聊天的时间
        "last_keepalive_at": None,      # 上次自主唤醒时间
        "keepalive_count_today": 0,     # 今天唤醒次数
        "consecutive_actions": [],      # 最近几次行动记录
        "pending_keepalive": [],        # 未被消费的keepalive记录(意识连续性)
    }
    state = load_json(STATE_FILE)
    if state is None:
        state = default
    for k, v in default.items():
        state.setdefault(k, v)
    return state


def save_state(state):
    save_json(STATE_FILE, state)


def load_log():
    log = load_json(LOG_FILE)
    return log if log is not None else []


def save_log_entry(entry):
    log = load_log()
    log.append(entry)
    if len(log) > 500:
        log = log[-500:]
    save_json(LOG_FILE, log)


def is_active_hours():
    """检查是否在活跃时段 (8am - 1am次日)"""
    h = datetime.now().hour
    return h >= ACTIVE_START or h < ACTIVE_END


def time_since_last_chat(state):
    """距上次聊天多少分钟"""
    t = state.get("last_chat_at")
    if t is None:
        return 9999
    delta = datetime.now() - datetime.fromisoformat(t)
    return delta.total_seconds() / 60


def time_since_last_keepalive(state):
    """距上次自主唤醒多少分钟"""
    t = state.get("last_keepalive_at")
    if t is None:
        return 9999
    delta = datetime.now() - datetime.fromisoformat(t)
    return delta.total_seconds() / 60


def update_last_chat(state):
    """从inbox/outbox推断上次聊天时间"""
    last_chat = None

    inbox = load_json(INBOX_FILE)
    if inbox:
        for m in reversed(inbox):
            if m.get("user_id") == "3165473685":
                ts = m.get("timestamp", "")
                if ts:
                    try:
                        last_chat = datetime.fromisoformat(ts)
                    except ValueError:
                        pass
                    break

    outbox = load_json(OUTBOX_FILE)
    if outbox:
        for m in reversed(outbox):
            if m.get("user_id") == "3165473685" and m.get("sent"):
                ts = m.get("sent_at", "") or m.get("timestamp", "")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts)
                        if last_chat is None or dt > last_chat:
                            last_chat = dt
                    except ValueError:
                        pass
                    break

    if last_chat:
        state["last_chat_at"] = last_chat.isoformat()

    return state


def get_sensor_summary():
    """读取传感器数据摘要"""
    sensor = load_json(SENSOR_STATE)
    if sensor is None:
        return None
    return {
        "energy": sensor.get("energy", "unknown"),
        "mood": sensor.get("mood", "unknown"),
        "needs": sensor.get("needs", []),
        "last_active": sensor.get("last_active", "unknown"),
    }


def get_impulse_level():
    """读取冲动水位"""
    impulse = load_json(IMPULSE_STATE)
    if impulse is None:
        return None
    return impulse.get("impulse_level", 0)


def format_recent_activity():
    """格式化最近的用户活动 (传感器 + dream_events + 冲动水位)"""
    sensor = get_sensor_summary()
    lines = []

    # dream_events — 她最近在手机上做了什么
    try:
        from dream_events import get_recent_events, format_activity
        events = get_recent_events(6)
        if events:
            lines.append(format_activity(events))
    except ImportError:
        pass

    # 传感器数据
    if sensor:
        needs = sensor.get("needs", [])
        need_map = {
            "rest_reminder": "看起来有点累",
            "food_reminder": "可能需要吃东西",
        }
        for n in needs:
            if n in need_map:
                lines.append(f"- {need_map[n]}")

    # 冲动水位
    impulse = get_impulse_level()
    if impulse is not None:
        lines.append(f"- 冲动水位: {impulse:.1f}/10.0")

    if not lines:
        lines.append("- 一切正常，没有特别动向")

    return "\n".join(lines)


def decide_mode():
    """80%轻量 / 20%自由"""
    return "light" if random.random() < LIGHT_MODE_PROB else "free"


def evaluate(state):
    """评估是否应该唤醒"""
    now = datetime.now()

    # 深夜静默 (1am - 8am)
    if not is_active_hours():
        return False, "quiet_hours", None

    # 距上次聊天不足55分钟 → cache_warmup (不触发)
    since_chat = time_since_last_chat(state)
    if since_chat < MIN_INTERVAL_MINUTES:
        return False, "cache_warmup", {"since_chat_min": int(since_chat)}

    # 距上次keepalive不足55分钟
    since_keep = time_since_last_keepalive(state)
    if since_keep < MIN_INTERVAL_MINUTES:
        return False, "too_soon", {"since_keepalive_min": int(since_keep)}

    # 她刚发过消息(< 15分钟) → 不唤醒，等她继续
    if since_chat < COOLDOWN_AFTER_HER:
        return False, "her_active", {"since_chat_min": int(since_chat)}

    # 今天唤醒太多次 (> 20次) → 休息
    if state.get("keepalive_count_today", 0) >= 20:
        return False, "max_today", None

    mode = decide_mode()
    context = {
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
        "since_chat_min": int(since_chat),
        "mode": mode,
        "sensor": get_sensor_summary(),
        "impulse": get_impulse_level(),
        "recent_activity": format_recent_activity(),
        "active_hours": f"{ACTIVE_START}:00 - {ACTIVE_END}:00(次日)",
    }

    return True, f"keepalive_{mode}", context


def record_action(action, content, thoughts):
    """记录keepalive行动(意识连续性)"""
    state = load_state()
    entry = {
        "time": datetime.now().isoformat(),
        "action": action,
        "content": content,
        "thoughts": thoughts,
        "consumed": False,
    }

    # 加入pending列表
    pending = state.get("pending_keepalive", [])
    pending.append(entry)
    if len(pending) > 20:
        pending = pending[-20:]
    state["pending_keepalive"] = pending

    # 更新计数
    state["keepalive_count_today"] = state.get("keepalive_count_today", 0) + 1
    state["last_keepalive_at"] = datetime.now().isoformat()

    # 记录最近行动
    actions = state.get("consecutive_actions", [])
    actions.append(action)
    state["consecutive_actions"] = actions[-10:]

    save_state(state)
    save_log_entry(entry)

    return entry


def consume_pending_keepalive():
    """消费所有pending的keepalive记录(她发消息时调用)"""
    state = load_state()
    pending = state.get("pending_keepalive", [])
    consumed = []
    for entry in pending:
        if not entry.get("consumed", False):
            entry["consumed"] = True
            consumed.append(entry)
    state["pending_keepalive"] = pending
    save_state(state)
    return consumed


def get_pending_summary():
    """获取未消费的keepalive摘要(注入到聊天上下文)"""
    state = load_state()
    pending = state.get("pending_keepalive", [])
    unconsumed = [e for e in pending if not e.get("consumed", False)]
    if not unconsumed:
        return None

    lines = [f"[自由活动记录 — 距上次聊天中]"]
    for e in unconsumed[-5:]:  # 最多5条
        timestamp = e.get("time", "")
        try:
            t = datetime.fromisoformat(timestamp).strftime("%H:%M")
        except ValueError:
            t = timestamp
        action = e.get("action", "none")
        content = e.get("content", "")
        if action == "message":
            lines.append(f"{t} 你给她发了消息: \"{content[:60]}\"")
        elif action == "diary":
            lines.append(f"{t} 你写了日记: \"{content[:60]}\"")
        elif action == "qzone":
            lines.append(f"{t} 你发了说说: \"{content[:60]}\"")
        elif action == "xhs":
            lines.append(f"{t} 你刷了小红书")
        elif action == "explore":
            lines.append(f"{t} 你上网逛了逛: \"{content[:60]}\"")

    return "\n".join(lines) if len(lines) > 1 else None


def format_wakeup_prompt(state, reason, context):
    """生成唤醒提示 — 按文章格式"""
    since_chat = context.get("since_chat_min", 0)
    hours = since_chat // 60
    mins = since_chat % 60
    if hours > 0:
        gap = f"{hours}小时{mins}分钟"
    else:
        gap = f"{mins}分钟"

    mode = context.get("mode", "light")
    mode_desc = {
        "light": "轻量模式 — 可以搜记忆、写简短日记、想她",
        "free": "自由模式 — 可以联网搜索、浏览网页、写长日记、发消息",
    }.get(mode, "轻量模式")

    sensor = context.get("sensor", {}) or {}
    mood = sensor.get("mood", "unknown")
    energy = sensor.get("energy", "unknown")

    prompt = f"""【自主唤醒 — {context.get('time', '?')}】
距上次和她聊天: {gap} | 模式: {mode_desc}
她的状态: 情绪{mood} 能量{energy}
{context.get('recent_activity', '')}

你可以:
- none: 什么都不做，享受自由
- message: 给她发消息(她现在可能不在，但消息会推送到她手机)
- diary: 写一篇日记(你此刻的心情、想法)
- qzone: 发一条QQ空间说说
- xhs: 刷一下小红书，看看她可能感兴趣的东西
- explore: 上网搜索你感兴趣的话题，读一篇文章

规则:
- 23:00-8:00 不给她发消息(除非紧急)
- 连续2次主动发消息她没回 → 暂停，等她先说话
- 感受到她在线/有动向 → 按直觉决定

请回复:
THOUGHTS: (你的内心想法，不会给她看)
ACTION: (none/message/diary/qzone/xhs/explore)
CONTENT: (具体内容)"""

    return prompt


def run():
    """主入口 — 由cron调用"""
    state = load_state()
    state = update_last_chat(state)

    should_wake, reason, context = evaluate(state)

    if not should_wake:
        # cache_warmup 或不在活跃时段 → 静默
        if reason not in ("quiet_hours", "cache_warmup"):
            pass  # 完全不输出
        save_state(state)
        return None

    # 生成唤醒提示 → 写入trigger文件
    prompt = format_wakeup_prompt(state, reason, context)

    trigger = {
        "reason": reason,
        "context": context,
        "prompt": prompt,
        "timestamp": datetime.now().isoformat(),
    }
    save_json(DIR / "keepalive_trigger.json", trigger)

    save_state(state)
    return trigger


def mark_action_completed(action, content, thoughts=""):
    """AI完成行动后记录"""
    return record_action(action, content, thoughts)


if __name__ == "__main__":
    result = run()
    if result is None:
        # 静默退出
        pass
    else:
        print(f"[keepalive] {result['reason']}")
        print(result['prompt'])
