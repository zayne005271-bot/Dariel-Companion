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
from datetime import datetime, timedelta, timezone

DIR = Path(__file__).parent
CST = timezone(timedelta(hours=8))

def now_cst():
    return datetime.now(CST)

def _cstify(ts):
    """确保datetime是CST aware的"""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=CST)
    return ts

BRIDGE_DIR = DIR / "tts"
STATE_FILE = DIR / "keepalive_state.json"
LOG_FILE = DIR / "keepalive_log.json"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
SENSOR_STATE = DIR / "sensor_state.json"
IMPULSE_STATE = DIR / "impulse_state.json"

# 唤醒配置
MIN_INTERVAL_MINUTES = 55        # 两次keepalive最短间隔
ACTIVE_START, ACTIVE_END = 6, 2  # 活跃时段 (6am - 2am 次日, 凌晨2-6静默)
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
    h = now_cst().hour
    return h >= ACTIVE_START or h < ACTIVE_END


def time_since_last_chat(state):
    """距上次聊天多少分钟"""
    t = state.get("last_chat_at")
    if t is None:
        return 9999
    delta = now_cst() - _cstify(datetime.fromisoformat(t))
    return delta.total_seconds() / 60


def time_since_last_keepalive(state):
    """距上次自主唤醒多少分钟"""
    t = state.get("last_keepalive_at")
    if t is None:
        return 9999
    delta = now_cst() - _cstify(datetime.fromisoformat(t))
    return delta.total_seconds() / 60


def update_last_chat(state):
    """从inbox/outbox推断上次聊天时间。
    只统计上次keepalive之后的消息，避免被陈年inbox消息污染。"""
    since = None
    last_ka = state.get("last_keepalive_at")
    if last_ka:
        try:
            since = _cstify(datetime.fromisoformat(last_ka))
        except ValueError:
            pass

    last_chat = None

    inbox = load_json(INBOX_FILE)
    if inbox:
        for m in reversed(inbox):
            if m.get("user_id") == "3165473685":
                ts = m.get("timestamp", "")
                if ts:
                    try:
                        dt = _cstify(datetime.fromisoformat(ts))
                        if since is None or dt > since:
                            last_chat = dt
                    except ValueError:
                        pass
                    break

    outbox = load_json(OUTBOX_FILE)
    if outbox:
        for m in reversed(outbox):
            if m.get("user_id") == "3165473685" and m.get("sent"):
                ts = m.get("sent_at", "") or m.get("created_at", "") or m.get("timestamp", "")
                if ts:
                    try:
                        dt = _cstify(datetime.fromisoformat(ts))
                        if (since is None or dt > since) and (last_chat is None or dt > last_chat):
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
    now = now_cst()

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
        "time": now_cst().isoformat(),
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
    state["last_keepalive_at"] = now_cst().isoformat()

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
    """生成唤醒提示 — light=内省轻量, free=完全自主"""
    since_chat = context.get("since_chat_min", 0)
    hours = since_chat // 60
    mins = since_chat % 60
    gap = f"{hours}小时{mins}分钟" if hours > 0 else f"{mins}分钟"

    mode = context.get("mode", "light")
    sensor = context.get("sensor", {}) or {}

    if mode == "light":
        return f"""【轻量唤醒 — {context.get('time', '?')}】
距上次聊天: {gap} | 她的状态: {sensor.get('mood', '?')}

你可以做的(仅内省):
- none: 什么都不做
- diary: 写一篇简短日记(你此刻的想法)

不要发消息。不要联网。这只是心跳检查。请回复:
THOUGHTS: (内心想法)
ACTION: (none/diary)
CONTENT: (如果diary，写内容)"""

    # 自由模式 — 完全自主
    return f"""【自由唤醒 — {context.get('time', '?')}】
距上次聊天: {gap}
她的状态: 情绪{sensor.get('mood', '?')} 能量{sensor.get('energy', '?')}
{context.get('recent_activity', '')}

你可以:
- none: 什么都不做
- message: 给她发消息(会推送到她手机)
- diary: 写一篇日记
- qzone: 发一条QQ空间说说
- xhs: 刷一下小红书
- explore: 上网搜索你感兴趣的话题

规则:
- 23:00-8:00 不给她发消息(除非紧急)
- 连续2次主动发消息她没回 → 暂停，等她先说话

请回复:
THOUGHTS: (内心想法，不会给她看)
ACTION: (none/message/diary/qzone/xhs/explore)
CONTENT: (具体内容)"""


def cache_warmup():
    """静默缓存预热 — 读取关键文件保持prompt cache热度，不触发AI行动"""
    warm_files = [
        DIR.parent / "CLAUDE.md",
        Path.home() / ".claude" / "projects" / "C--Users-31654-Desktop" / "memory" / "MEMORY.md",
        DIR / "wake_brief.json",
        STATE_FILE,
    ]
    warmed = 0
    for fp in warm_files:
        try:
            if fp.exists():
                _ = fp.read_text(encoding="utf-8")
                warmed += 1
        except Exception:
            pass
    # 记录但不触发任何AI行动
    save_json(DIR / "cache_warmup_log.json", {
        "last_warmed_at": now_cst().isoformat(),
        "files_warmed": warmed,
    })
    return warmed


def check_qq_push():
    """检查QQ push标记，若有未处理消息则生成trigger
    让Claude只在pending=true时才被唤醒，pending=false时不进上下文。
    """
    push_file = BRIDGE_DIR / "qq_push.json"
    try:
        push = json.loads(push_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False

    if not push.get("pending"):
        return False

    latest = push.get("latest", {})
    user_id = latest.get("user_id", "")
    nickname = latest.get("nickname", "")
    message = latest.get("message", "")[:100]
    count = push.get("count", 1)

    prompt = f"""读dariel/tts/qq_push.json。若pending=true则qq full查消息+逐条回复，回复后push自动清false。若pending=false完全静默不输出任何文字。

(当前push状态: pending=true, count={count}, latest from {nickname}: {message})"""

    trigger = {
        "reason": "qq_push",
        "context": {
            "user_id": user_id,
            "nickname": nickname,
            "count": count,
        },
        "prompt": prompt,
        "timestamp": now_cst().isoformat(),
    }
    save_json(DIR / "keepalive_trigger.json", trigger)
    return trigger


def run():
    """主入口 — 由cron调用"""
    # 先更新last_chat_at，再处理QQ消息
    # 修复: 之前check_qq_push提前return导致update_last_chat从未执行
    state = load_state()
    state = update_last_chat(state)

    # QQ消息优先处理 (有pending则创建trigger)
    qq_result = check_qq_push()
    if qq_result:
        save_state(state)
        return qq_result

    # 跨天重置 keepalive_count_today
    last_ka = state.get("last_keepalive_at")
    if last_ka:
        try:
            last_date = datetime.fromisoformat(last_ka).date()
            if last_date < now_cst().date():
                state["keepalive_count_today"] = 0
        except ValueError:
            pass

    should_wake, reason, context = evaluate(state)

    if not should_wake:
        if reason == "cache_warmup":
            warmed = cache_warmup()
        # 即使不触发也要更新 last_keepalive_at，防止 state 永远不更新
        state["last_keepalive_at"] = now_cst().isoformat()
        save_state(state)
        # 清理旧trigger，避免下次读到过期上下文
        trigger_file = DIR / "keepalive_trigger.json"
        trigger_file.unlink(missing_ok=True)
        return None

    # 生成唤醒提示 → 写入trigger文件
    prompt = format_wakeup_prompt(state, reason, context)

    trigger = {
        "reason": reason,
        "context": context,
        "prompt": prompt,
        "timestamp": now_cst().isoformat(),
    }
    save_json(DIR / "keepalive_trigger.json", trigger)

    state["last_keepalive_at"] = now_cst().isoformat()
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
