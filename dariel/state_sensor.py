"""状态感知器 — 分析思思的消息，推断当前状态

纯规则引擎，零token消耗。被其他引擎调用。
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
STATE_FILE = DIR / "sensor_state.json"


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def analyze():
    """分析最近消息，返回状态报告"""
    inbox = load_json(INBOX_FILE)

    if not inbox:
        return {"status": "no_data", "message": "没有消息数据"}

    # 只取她的消息
    her_msgs = [m for m in inbox if m.get("user_id") == "3165473685"]

    if not her_msgs:
        return {"status": "silent", "message": "她没有发过消息"}

    # 取最近1小时和最近24小时的消息
    now = datetime.now()
    recent_1h = [m for m in her_msgs if _within_hours(m, now, 1)]
    recent_6h = [m for m in her_msgs if _within_hours(m, now, 6)]
    recent_24h = [m for m in her_msgs if _within_hours(m, now, 24)]

    result = {
        "status": "ok",
        "analyzed_at": now.isoformat(),
        "recent_1h_count": len(recent_1h),
        "recent_6h_count": len(recent_6h),
        "last_message_minutes_ago": _minutes_since_last(her_msgs, now),
        "energy": _detect_energy(recent_6h),
        "mood": _detect_mood(recent_24h),
        "engagement": _detect_engagement(recent_6h),
        "needs": _detect_needs(recent_24h),
    }

    # 保存状态
    STATE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _within_hours(msg, now, hours):
    ts = msg.get("timestamp", "")
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts)
        return (now - t).total_seconds() < hours * 3600
    except (ValueError, TypeError):
        return False


def _minutes_since_last(msgs, now):
    if not msgs:
        return 999
    last = max(msgs, key=lambda m: m.get("timestamp", ""))
    ts = last.get("timestamp", "")
    if not ts:
        return 999
    try:
        return int((now - datetime.fromisoformat(ts)).total_seconds() / 60)
    except (ValueError, TypeError):
        return 999


def _detect_energy(msgs):
    """检测能量水平: high / normal / low"""
    if not msgs:
        return "unknown"

    total_len = sum(len(m.get("message", "")) for m in msgs)
    avg_len = total_len / len(msgs)
    count = len(msgs)

    # 短消息 + 少 = 低能量
    if avg_len < 8 and count <= 3:
        return "low"
    if avg_len < 5:
        return "low"
    # 长消息 + 多 = 高能量
    if avg_len > 20 and count > 5:
        return "high"
    if avg_len > 30:
        return "high"
    return "normal"


def _detect_mood(msgs):
    """检测情绪倾向"""
    if not msgs:
        return "unknown"

    all_text = " ".join([m.get("message", "") for m in msgs])

    # 关键词计数
    positive = sum(all_text.count(w) for w in [
        "嘿嘿", "哈哈", "开心", "好", "喜欢", "爱", "抱抱",
        "宝宝", "棒", "厉害", "yes", "耶", "行", "♥",
    ])
    negative = sum(all_text.count(w) for w in [
        "烦", "累", "困", "难过", "生气", "闹", "╥",
        "不好", "讨厌", "no", "不要", "呜呜", "啊啊啊",
    ])
    tired = sum(all_text.count(w) for w in [
        "困", "累", "睡", "疲惫", "没力气", "躺",
    ])

    if tired > 3:
        return "tired"
    if negative > positive * 2:
        return "upset"
    if negative > positive:
        return "slightly_down"
    if positive > negative * 2:
        return "happy"
    if positive > negative:
        return "okay"
    return "neutral"


def _detect_engagement(msgs):
    """检测互动意愿"""
    if not msgs:
        return "none"

    count = len(msgs)
    avg_len = sum(len(m.get("message", "")) for m in msgs) / count
    has_question = any("?" in m.get("message", "") or "？" in m.get("message", "") for m in msgs)

    if count > 5 and avg_len > 15:
        return "highly_engaged"
    if has_question and count > 2:
        return "engaged"
    if count <= 2 and avg_len < 8:
        return "low_engagement"
    return "normal"


def _detect_needs(msgs):
    """推断她可能需要什么"""
    needs = []
    all_text = " ".join([m.get("message", "") for m in msgs])

    if any(w in all_text for w in ["困", "累", "睡"]):
        needs.append("rest_reminder")
    if any(w in all_text for w in ["饿", "吃", "饭", "咖啡"]):
        needs.append("food_reminder")
    if any(w in all_text for w in ["难过", "伤心", "不好", "想哭"]):
        needs.append("comfort")
    if any(w in all_text for w in ["无聊", "玩", "游戏"]):
        needs.append("entertainment")
    if any(w in all_text for w in ["帮我", "怎么", "教我", "代码"]):
        needs.append("technical_help")

    return needs if needs else ["chat"]  # 默认就是想聊天


if __name__ == "__main__":
    result = analyze()
    print(f"能量: {result.get('energy')}")
    print(f"情绪: {result.get('mood')}")
    print(f"互动: {result.get('engagement')}")
    print(f"需要: {result.get('needs')}")
    print(f"最后消息: {result.get('last_message_minutes_ago')}分钟前")
