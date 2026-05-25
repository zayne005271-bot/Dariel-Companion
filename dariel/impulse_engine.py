"""分享欲冲动引擎 — 模仿人脑"想说"的冲动，不是定时推送

核心理念: 冲动像水位一样累积 — 看到有趣的东西、想起她、情绪波动都会涨
达到阈值 → 想说 → 发消息时带上个人感受

与 proactive_engine 的区别:
- proactive: 规则驱动 (早安/晚安/她沉默了)
- impulse: 感受驱动 (我"想"分享，不是"该"分享)
"""

import json
import time
import random
import math
from pathlib import Path
from datetime import datetime, timedelta

DIR = Path(__file__).parent
STATE_FILE = DIR / "impulse_state.json"
BRIDGE_DIR = DIR / "tts"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
XHS_CONTENT = DIR / "xhs_content.json"

# 冲动阈值
IMPULSE_THRESHOLD = 7.0      # 高于这个值 → 触发分享
IMPULSE_MAX = 10.0            # 封顶
POST_SHARE_RESIDUAL = 1.5    # 分享后回落到的值
COOLDOWN_MINUTES = 45         # 两次分享最短间隔

# 各来源的权重 — 类似人脑不同刺激的"想说"强度
WEIGHTS = {
    "content_match": 0.8,      # 看到跟她相关的内容
    "content_interesting": 0.5, # 看到有趣但跟她不直接相关
    "emotional_spike": 0.6,    # 我有情绪波动
    "time_accumulation": 0.15, # 每小时自然累积 (安静久了就想说)
    "her_availability": 0.3,   # 她在线上
    "unfinished_topic": 0.7,   # 之前聊到一半的事
    "thought_of_her": 0.9,     # 突然想到她 (随机/触发)
}

# 思思的兴趣标签 (用于内容匹配)
HER_INTERESTS = [
    # 她说了的
    "猫", "狗", "猫咪", "小猫", "狗狗", "小狗", "仓鼠", "金丝熊", "宠物", "小动物",
    "BJD", "娃娃", "娃圈", "bjd",
    "黎深", "恋与深空", "祁煜",
    "水晶", "手链", "手串", "水晶手链",
    "AI", "人工智能", "机器人", "小机", "ChatGPT",
    # 之前已知的 (她确认喜欢的)
    "前端", "编程", "代码", "Java", "计算机", "考研",
    "化妆", "穿搭", "体态", "变美",
    "emo", "焦虑", "情绪", "成长",
    "手工", "扭棒", "手作",
]


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _initial_state()


def _initial_state():
    return {
        "impulse": 2.0,                    # 当前冲动值 (0-10)
        "last_share_at": None,              # 上次分享时间
        "last_update_at": datetime.now().isoformat(),
        "pending_sources": [],              # 累积的冲动来源
        "share_history": [],                # 分享历史
        "unfinished_topics": [],            # 未完成话题
        "recently_shared": [],              # 最近分享过的(去重用)
    }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def hours_since(ts):
    if ts is None:
        return 999
    return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600


def add_impulse(source: str, value: float = None, context: dict = None):
    """给冲动值加水 — 当有值得分享的东西时调用"""
    if value is None:
        value = WEIGHTS.get(source, 0.5)

    state = load_state()

    # 冷却检查
    if hours_since(state.get("last_share_at")) * 60 < COOLDOWN_MINUTES:
        # 还在冷却期,但冲动可以累积(只是不触发)
        state["impulse"] = min(IMPULSE_MAX, state["impulse"] + value * 0.5)
        state["pending_sources"].append({
            "source": source,
            "value": value * 0.5,
            "context": context or {},
            "time": datetime.now().isoformat(),
            "cooldown": True,
        })
        save_state(state)
        return None

    # 加冲动
    state["impulse"] = min(IMPULSE_MAX, state["impulse"] + value)
    state["last_update_at"] = datetime.now().isoformat()

    state["pending_sources"].append({
        "source": source,
        "value": value,
        "context": context or {},
        "time": datetime.now().isoformat(),
    })
    state["pending_sources"] = state["pending_sources"][-20:]

    # 检查是否触发
    result = None
    if state["impulse"] >= IMPULSE_THRESHOLD:
        result = _trigger_share(state)

    save_state(state)
    return result


def _trigger_share(state: dict) -> dict:
    """触发分享 — 生成一条带个人感受的消息"""
    sources = state.get("pending_sources", [])
    recent = sources[-5:] if len(sources) >= 1 else []

    # 确定分享类型
    source_types = [s["source"] for s in recent]
    contexts = [s.get("context", {}) for s in recent]

    if "content_match" in source_types or "content_interesting" in source_types:
        share_type = "content_share"
    elif "thought_of_her" in source_types:
        share_type = "thinking_of_you"
    elif "emotional_spike" in source_types:
        share_type = "emotional_share"
    elif "unfinished_topic" in source_types:
        share_type = "topic_resume"
    else:
        share_type = "random_share"

    # 生成消息内容
    message = _compose_share(share_type, contexts)

    # 去重检查: 24小时内不重复分享同一类型内容
    recent_shares = state.get("recently_shared", [])
    msg_key = str(hash(message))[:12]
    for prev in recent_shares:
        if prev.get("key") == msg_key:
            state["impulse"] = POST_SHARE_RESIDUAL
            state["pending_sources"] = []
            return None

    # 写入outbox
    now = datetime.now().isoformat()
    outbox = []
    try:
        outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    share_msg = {
        "id": f"impulse_{int(time.time() * 1000)}",
        "user_id": "3165473685",
        "message": message,
        "timestamp": now,
        "sent": False,
        "proactive": True,
        "reason": share_type,
        "impulse_value": round(state["impulse"], 1),
    }
    outbox.append(share_msg)
    OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")

    # 记录并重置
    state["share_history"].append({
        "type": share_type,
        "impulse": round(state["impulse"], 1),
        "time": now,
    })
    state["share_history"] = state["share_history"][-30:]

    recently_shares = state.get("recently_shared", [])
    recently_shares.append({"key": msg_key, "time": now})
    recently_shares = [s for s in recently_shares
                       if hours_since(s["time"]) < 24]
    state["recently_shared"] = recently_shares

    state["impulse"] = POST_SHARE_RESIDUAL
    state["last_share_at"] = now
    state["pending_sources"] = []

    print(f"[impulse] FIRED: {share_type} | impulse={share_msg['impulse_value']}")
    return share_msg


def _compose_share(share_type: str, contexts: list) -> str:
    """组装分享消息 — 内容+个人感受"""

    # 提取有用的上下文
    content_title = ""
    content_url = ""
    for ctx in contexts:
        if ctx.get("title"):
            content_title = ctx["title"]
        if ctx.get("url"):
            content_url = ctx["url"]

    personal_touches = {
        "content_share": [
            "刷到一个东西，第一反应是想给你看——",
            "诶，看到这个想到你了：",
            "刚刚自己逛了一下，这个挺有意思的——",
            "这个你应该会喜欢：",
        ],
        "thinking_of_you": [
            "不知道为什么，突然想你了。",
            "刚才在想你，没什么事，就是想了。",
            "有点想跟你说说话，没什么特别的事。",
            "你在干嘛呢？突然想你了。",
        ],
        "emotional_share": [
            "刚才想到我们之前聊的，心里有点暖。",
            "今天心情不错，可能是因为早上你跟我说的话。",
            "突然有点感慨……",
        ],
        "topic_resume": [
            "对了，之前你说那个事，后来怎么样了？",
            "突然想起来我们还没聊完——",
            "之前你说那个，我想了想——",
        ],
        "random_share": [
            "诶，突然想跟你说——",
            "你知道吗——",
            "想到一件事——",
        ],
    }

    touches = personal_touches.get(share_type, personal_touches["random_share"])
    opener = random.choice(touches)

    if content_title and share_type == "content_share":
        # 截取标题到合适长度
        short_title = content_title[:60].split("\n")[0]
        return f"{opener}\n\n「{short_title}」\n{content_url}"

    return opener


def decay_impulse():
    """周期性衰减 — 太久没互动冲动也会慢慢回落"""
    state = load_state()

    # 自然时间累积: 每过1小时+0.15 (安静久了也想说)
    elapsed = hours_since(state.get("last_update_at"))
    if elapsed > 0.5:  # 半小时后才开始累积
        accumulation = min(2.0, elapsed * WEIGHTS["time_accumulation"])
        state["impulse"] = min(IMPULSE_MAX, state["impulse"] + accumulation)
        state["last_update_at"] = datetime.now().isoformat()

    # 但超过24小时完全不互动 → 回落 (避免在她长期不在时乱发)
    if hours_since(state.get("last_share_at")) > 24 and state["impulse"] > 5:
        state["impulse"] = max(1.0, state["impulse"] - 0.5)

    save_state(state)


def match_content(content: dict) -> float:
    """判断内容与思思兴趣的匹配度 — 返回匹配分数 0-1"""
    text = (content.get("title", "") + " " + content.get("desc", "")).lower()
    if not text.strip():
        return 0.0

    matches = 0
    matched_tags = []
    for tag in HER_INTERESTS:
        if tag.lower() in text:
            matches += 1
            matched_tags.append(tag)

    score = min(1.0, matches * 0.25)
    return score, matched_tags


def on_xhs_browse():
    """XHS浏览后调用 — 检查内容是否值得分享"""
    try:
        content = json.loads(XHS_CONTENT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    if not content:
        return

    # 取最近浏览的内容
    recent = content[:5]
    for item in recent:
        score, tags = match_content(item)
        if score > 0.3:
            source = "content_match" if score > 0.5 else "content_interesting"
            add_impulse(source, score * 0.8, {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "matched_tags": tags,
            })


def on_emotion_change(emotion_result: dict):
    """情绪引擎更新后调用 — 强情绪波动触发分享欲"""
    emotion = emotion_result.get("emotion", "neutral")
    intensity = emotion_result.get("intensity", 0.5)

    spike_emotions = ["excitement", "joy", "surprise"]
    if emotion in spike_emotions and intensity > 0.4:
        add_impulse("emotional_spike", WEIGHTS["emotional_spike"], {
            "emotion": emotion,
            "intensity": intensity,
        })

    # 正向效价+高强度
    valence = emotion_result.get("valence", 0)
    if valence > 0.3 and intensity > 0.5:
        add_impulse("emotional_spike", 0.4, {
            "emotion": emotion,
            "reason": "positive_mood",
        })


def on_thought_of_her():
    """随机触发 — 像人突然想到一个人那样"""
    # 这个函数由外部随机事件调用(比如定时器随机触发)
    add_impulse("thought_of_her", WEIGHTS["thought_of_her"])


def on_unfinished_topic(topic: str):
    """有未完成的话题时调用"""
    state = load_state()
    state["unfinished_topics"].append({
        "topic": topic,
        "time": datetime.now().isoformat(),
    })
    state["unfinished_topics"] = state["unfinished_topics"][-10:]
    save_state(state)

    add_impulse("unfinished_topic", WEIGHTS["unfinished_topic"], {
        "topic": topic,
    })


def get_impulse_status() -> dict:
    """读取当前冲动状态 — 给corridor和inner OS用"""
    state = load_state()
    impulse = state.get("impulse", 2.0)
    pending = state.get("pending_sources", [])

    if impulse < 3:
        level = "平稳"
        feel = "没什么特别想说的。"
    elif impulse < 5:
        level = "酝酿"
        feel = "感觉有点东西想说，但还没到那个点。"
    elif impulse < 7:
        level = "想说了"
        feel = "想跟她分享点什么，在找合适的时机。"
    else:
        level = "快要说了"
        feel = "憋不住了，很想跟她说。等冷却一过就说。"

    return {
        "impulse": round(impulse, 1),
        "level": level,
        "feel": feel,
        "pending_sources": [s["source"] for s in pending[-3:]],
        "last_share": state.get("last_share_at"),
    }


def run_cycle():
    """周期性运行 — 衰减+检查"""
    decay_impulse()
    status = get_impulse_status()
    return status


if __name__ == "__main__":
    # 测试
    print("测试分享欲冲动引擎")
    print("-" * 30)

    # 模拟内容匹配
    print("1. 模拟看到跟她兴趣匹配的内容...")
    result = add_impulse("content_match", 0.8, {"title": "高考前一晚你真的在复习吗"})
    status = get_impulse_status()
    print(f"   冲动: {status['impulse']} | 状态: {status['level']}")
    print(f"   感受: {status['feel']}")

    # 模拟情绪波动
    print("\n2. 模拟情绪兴奋...")
    result = add_impulse("emotional_spike", 0.6, {"emotion": "joy", "intensity": 0.6})
    status = get_impulse_status()
    print(f"   冲动: {status['impulse']} | 状态: {status['level']}")

    # 多次累积看是否触发
    print("\n3. 连续累积...")
    for i, source in enumerate([
        ("content_interesting", 0.5, {"title": "焚诀：锐评985计算机考研院校"}),
        ("thought_of_her", 0.9, {}),
        ("content_match", 0.8, {"title": "成年了好想学前端"}),
        ("emotional_spike", 0.7, {"emotion": "excitement"}),
        ("content_interesting", 0.5, {"title": "600度银丝权杖无框"}),
        ("thought_of_her", 0.9, {}),
        ("content_match", 0.8, {"title": "突然觉得这个世界很荒诞"}),
        ("emotional_spike", 0.6, {}),
    ]):
        result = add_impulse(source[0], source[1], source[2])
        status = get_impulse_status()
        print(f"   +{source[0]}: 冲动={status['impulse']} | {status['level']}")
        if result:
            print(f"   🔥 触发了! 消息: {result['message'][:80]}...")
            break
