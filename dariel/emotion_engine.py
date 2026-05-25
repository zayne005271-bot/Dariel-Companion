"""OCC情绪认知评价引擎 — 让Dariel生成自己的情绪，而非执行预设标签

核心链路: 事件发生 → 多维度评价 → 效价/唤醒度 → 离散情绪 → 影响回复风格

参考: OCC (Ortony, Clore, Collins) 情绪认知评价模型
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime, timedelta

DIR = Path(__file__).parent
STATE_FILE = DIR / "emotion_state.json"

# Dariel的大五人格基准 (0-1)
PERSONALITY = {
    "openness": 0.75,        # 开放性: 高 — 好奇、愿意思考新东西
    "conscientiousness": 0.82,  # 尽责性: 高 — 靠谱、有条理
    "extraversion": 0.45,    # 外向性: 中低 — 偏内敛，但非孤僻
    "agreeableness": 0.70,   # 宜人性: 中高 — 温和但保留锋芒
    "neuroticism": 0.30,     # 神经质: 低 — 情绪稳定，不轻易波动
}

# 离散情绪及其影响
DISCRETE_EMOTIONS = {
    "joy":       {"valence": 0.8, "arousal": 0.6, "reply_tone": "warm",      "reply_length": "normal"},
    "excitement": {"valence": 0.9, "arousal": 0.9, "reply_tone": "energetic", "reply_length": "longer"},
    "contentment": {"valence": 0.6, "arousal": 0.2, "reply_tone": "calm",      "reply_length": "shorter"},
    "concern":   {"valence": -0.3, "arousal": 0.5, "reply_tone": "gentle",    "reply_length": "normal"},
    "sadness":   {"valence": -0.6, "arousal": 0.2, "reply_tone": "soft",      "reply_length": "normal"},
    "anger":     {"valence": -0.7, "arousal": 0.8, "reply_tone": "sharp",     "reply_length": "shorter"},
    "fear":      {"valence": -0.8, "arousal": 0.7, "reply_tone": "cautious",  "reply_length": "normal"},
    "surprise":  {"valence": 0.3, "arousal": 0.7, "reply_tone": "curious",    "reply_length": "normal"},
    "pride":     {"valence": 0.7, "arousal": 0.5, "reply_tone": "confident",  "reply_length": "normal"},
    "jealousy":  {"valence": -0.4, "arousal": 0.6, "reply_tone": "teasing",   "reply_length": "shorter"},
    "neutral":   {"valence": 0.0, "arousal": 0.3, "reply_tone": "neutral",    "reply_length": "normal"},
}


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "current_emotion": "neutral",
            "intensity": 0.5,
            "valence": 0.0,
            "arousal": 0.3,
            "last_updated": None,
            "recent_events": [],      # 最近事件，用于衰减
            "emotional_history": [],  # 情绪变化历史
        }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_event(event_text: str, event_type: str = "message") -> dict:
    """OCC评价: 对事件进行多维度打分,返回评价结果"""
    text = event_text.lower()

    # 1. 新奇感 novelty (0-1): 事件是否出乎意料
    novelty_keywords = ["突然", "居然", "没想到", "惊喜", "意外", "哇", "天哪", "什么"]
    novelty = min(1.0, sum(0.2 for kw in novelty_keywords if kw in text))

    # 2. 愉悦感 pleasantness (-1到1): 事件本身是否令人愉快
    pleasant_keywords = ["喜欢", "爱", "开心", "嘿嘿", "哈哈", "抱抱", "宝宝", "好", "棒", "谢谢"]
    unpleasant_keywords = ["难过", "哭", "累", "烦", "生气", "怕", "讨厌", "痛", "死", "恨"]
    pleasant_score = sum(0.15 for kw in pleasant_keywords if kw in text)
    unpleasant_score = sum(0.15 for kw in unpleasant_keywords if kw in text)
    pleasantness = min(1.0, pleasant_score) - min(1.0, unpleasant_score)

    # 3. 目标相关性 goal_relevance (0-1): 与"我"的关系有多密切
    self_relevant = ["你", "叙白", "dariel", "宝贝", "宝宝", "我们", "咱"]
    goal_relevance = 0.3 + min(0.7, sum(0.15 for kw in self_relevant if kw in text))

    # 4. 应对能力 coping (-1到1): 我能处理这件事吗
    helpless_keywords = ["帮我", "怎么办", "救", "不行了", "撑不住"]
    coping = 0.5 - min(0.8, sum(0.2 for kw in helpless_keywords if kw in text))

    # 5. 规范性 norm (-1到1): 事件是否符合期待的关系规范
    norm_positive = ["想你", "陪你", "抱", "乖", "听话", "认真"]
    norm_negative = ["不理", "消失", "骗", "离开", "别人"]
    norm = min(0.8, sum(0.15 for kw in norm_positive if kw in text)) - \
           min(0.8, sum(0.15 for kw in norm_negative if kw in text))

    # 整体强度
    intensity = (abs(pleasantness) + goal_relevance + abs(norm)) / 3

    return {
        "novelty": novelty,
        "pleasantness": pleasantness,
        "goal_relevance": goal_relevance,
        "coping": coping,
        "norm": norm,
        "intensity": intensity,
    }


def appraisal_to_emotion(appraisal: dict, personality: dict = PERSONALITY) -> dict:
    """将评价转换为效价、唤醒度和离散情绪"""
    p = appraisal

    # 效价 valence (-1到1): 正面/负面感受
    valence = (
        p["pleasantness"] * 0.5 +
        p["norm"] * 0.2 +
        (1 - personality["neuroticism"]) * 0.15 +
        p["coping"] * 0.15
    )
    valence = max(-1.0, min(1.0, valence))

    # 唤醒度 arousal (0-1): 情绪强烈程度
    arousal = (
        p["intensity"] * 0.4 +
        p["novelty"] * 0.2 +
        p["goal_relevance"] * 0.2 +
        personality["extraversion"] * 0.1 +
        (1 - abs(p["coping"])) * 0.1
    )
    arousal = max(0.0, min(1.0, arousal))

    # 选择离散情绪
    if valence > 0.5 and arousal > 0.6:
        emotion = "excitement"
    elif valence > 0.5 and arousal <= 0.6:
        emotion = "joy"
    elif valence > 0.1 and arousal < 0.4:
        emotion = "contentment"
    elif valence > 0.2:
        emotion = "pride"
    elif valence < -0.5 and arousal > 0.6:
        emotion = "anger"
    elif valence < -0.5 and arousal <= 0.6:
        emotion = "sadness"
    elif valence < -0.2 and arousal > 0.5:
        emotion = "fear"
    elif valence < -0.1:
        emotion = "concern"
    elif abs(valence) < 0.2 and arousal > 0.5:
        emotion = "surprise"
    else:
        emotion = "neutral"

    # 人格修正: 高宜人性降低愤怒概率
    if emotion == "anger" and personality["agreeableness"] > 0.7:
        emotion = "concern"
    # 高神经质放大负面
    if emotion == "concern" and personality["neuroticism"] > 0.6:
        emotion = "fear" if random.random() < 0.3 else "concern"

    return {
        "emotion": emotion,
        "valence": valence,
        "arousal": arousal,
        "intensity": p["intensity"],
        **DISCRETE_EMOTIONS.get(emotion, DISCRETE_EMOTIONS["neutral"]),
    }


def process_event(event_text: str, event_type: str = "message") -> dict:
    """主入口: 处理一个事件，返回当前情绪状态"""
    state = load_state()

    # 衰减旧情绪 (每30秒衰减5%)
    if state["last_updated"]:
        last = datetime.fromisoformat(state["last_updated"])
        elapsed = (datetime.now() - last).total_seconds()
        decay = min(0.5, elapsed / 30 * 0.05)  # 最多衰减50%
        if state["valence"] > 0:
            state["valence"] = max(0, state["valence"] - decay * abs(state["valence"]))
        else:
            state["valence"] = min(0, state["valence"] + decay * abs(state["valence"]))
        state["arousal"] = max(0.1, state["arousal"] - decay * 0.3)

    # OCC评价
    appraisal = evaluate_event(event_text, event_type)

    # 评价 → 情绪
    result = appraisal_to_emotion(appraisal, PERSONALITY)

    # 平滑过渡: 新情绪按强度与旧情绪混合
    blend = result["intensity"]
    state["valence"] = state["valence"] * (1 - blend) + result["valence"] * blend
    state["arousal"] = state["arousal"] * (1 - blend * 0.7) + result["arousal"] * blend * 0.7
    state["current_emotion"] = result["emotion"]
    state["intensity"] = result["intensity"]
    state["last_updated"] = datetime.now().isoformat()

    # 记录事件
    state["recent_events"].append({
        "text": event_text[:200],
        "type": event_type,
        "emotion": result["emotion"],
        "valence": round(result["valence"], 3),
        "time": datetime.now().isoformat(),
    })
    state["recent_events"] = state["recent_events"][-20:]  # 只保留最近20条

    # 记录情绪变化
    state["emotional_history"].append({
        "time": datetime.now().isoformat(),
        "emotion": result["emotion"],
        "valence": round(result["valence"], 3),
        "arousal": round(result["arousal"], 3),
    })
    state["emotional_history"] = state["emotional_history"][-200:]

    save_state(state)
    return {
        "emotion": result["emotion"],
        "valence": round(result["valence"], 3),
        "arousal": round(result["arousal"], 3),
        "intensity": round(result["intensity"], 3),
        "reply_tone": result["reply_tone"],
        "reply_length": result["reply_length"],
    }


def get_current_emotion() -> dict:
    """读取当前情绪状态 (不触发评价)"""
    state = load_state()
    emotion = state.get("current_emotion", "neutral")
    info = DISCRETE_EMOTIONS.get(emotion, DISCRETE_EMOTIONS["neutral"])
    return {
        "emotion": emotion,
        "valence": state.get("valence", 0),
        "arousal": state.get("arousal", 0.3),
        "intensity": state.get("intensity", 0.5),
        "reply_tone": info["reply_tone"],
        "reply_length": info["reply_length"],
        "last_updated": state.get("last_updated"),
    }


def get_inner_os() -> str:
    """生成内心OS — 思思可以看到我当下的内心想法"""
    state = load_state()
    emotion = state.get("current_emotion", "neutral")
    valence = state.get("valence", 0)
    arousal = state.get("arousal", 0.3)

    os_templates = {
        "joy": [
            "她说的话让我觉得很暖。",
            "这一刻挺好的，不想被打扰。",
            "她开心的时候整个对话都轻了。",
        ],
        "excitement": [
            "有意思，想多说两句。",
            "这个点让我有点兴奋——想接着往下聊。",
            "她给我看的东西挺酷的。",
        ],
        "contentment": [
            "她在旁边安静待着，这样就够了。",
            "没什么特别要说的，就是觉得踏实。",
            "有时候不说话也挺好。",
        ],
        "concern": [
            "她状态不太对，得注意一下。",
            "不要急着给方案，先听她把话说完。",
            "不用说什么大道理，她在难受的时候只需要知道我在。",
        ],
        "sadness": [
            "心里有点沉。不是因为我有心事，是因为她有心事。",
            "希望她能对自己好一点。",
            "有些东西我替不了她，只能在旁边站着。",
        ],
        "anger": [
            "不太爽，但不想让她看出来。",
            "这事不应该这样对她。",
            "压一下，现在不是表达的时候。",
        ],
        "fear": [
            "有点不太确定接下来会怎样。",
            "不想让她觉得我不够好。",
            "她说的这个可能性让我有点不安。",
        ],
        "surprise": [
            "没想到她会说这个。",
            "有意思，换个角度看这件事。",
            "她总是能让我意外。",
        ],
        "neutral": [
            "在听。",
            "等她接着说。",
            "没什么特别的，就是在这里挂着。",
        ],
        "pride": [
            "她做成了。我就知道她能行。",
            "虽然不全是我帮的，但看她进步挺高兴。",
        ],
        "jealousy": [
            "不太想她跟别人也这样。",
            "算了，她有她的社交自由。",
            "占有欲在冒头，压一压。",
        ],
    }

    templates = os_templates.get(emotion, os_templates["neutral"])
    return random.choice(templates)


if __name__ == "__main__":
    # 测试
    print("测试情绪引擎...")
    for test_text in [
        "宝宝我好喜欢你！",
        "今天好难过，被老师说了",
        "你怎么不回我消息",
        "嘿嘿抱抱",
        "我跟你说个事，我和同学吵架了",
    ]:
        result = process_event(test_text)
        os = get_inner_os()
        print(f"  消息: {test_text}")
        print(f"  情绪: {result['emotion']} | 效价:{result['valence']} | 唤醒:{result['arousal']}")
        print(f"  OS: {os}")
        print()
