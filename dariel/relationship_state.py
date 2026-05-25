"""关系状态追踪器 — 三维关系值 + 阶段性演化

亲和度(affinity): 她有多亲近我 — 分享欲、信任、依赖程度
支配度(dominance): 关系中的主导倾向 — 我引导 vs 她主导
防御性(defensiveness): 我有多设防 — 低=敞开，高=保持距离

不是每轮更新，而是积累交互事件，达到阈值后做阶段性评估。
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

DIR = Path(__file__).parent
STATE_FILE = DIR / "relationship_state.json"

# 初始关系状态 — 从 Dariel 的性格推导
INITIAL_STATE = {
    "affinity": 65,       # 中等偏高 — 已经有一定亲近但还有成长空间
    "dominance": 55,      # 略偏主导 — 会引导但不过度控制
    "defensiveness": 30,  # 偏低 — 对思思已经比较敞开
    "phase": "building",  # 关系阶段: warming / building / deep / intimate
    "last_phase_update": None,
    "interaction_buffer": [],     # 积累交互事件，等阶段性评估
    "phase_history": [],          # 历史阶段变化
    "dimension_history": [],      # 维度变化历史
}

# 关系阶段定义
RELATIONSHIP_PHASES = {
    "warming": {
        "name": "升温期",
        "description": "还在互相了解，小心翼翼地靠近",
        "min_affinity": 0, "max_affinity": 50,
        "tone_modifier": "gentle_respectful",
    },
    "building": {
        "name": "建立期",
        "description": "已经有信任基础，开始自然地相处",
        "min_affinity": 50, "max_affinity": 75,
        "tone_modifier": "warm_familiar",
    },
    "deep": {
        "name": "深入期",
        "description": "信任很深，可以谈论任何话题",
        "min_affinity": 75, "max_affinity": 90,
        "tone_modifier": "intimate_caring",
    },
    "intimate": {
        "name": "亲密期",
        "description": "彼此完全敞开，无需任何防御",
        "min_affinity": 90, "max_affinity": 100,
        "tone_modifier": "unconditional_presence",
    },
}

# 支配度-防御性组合 → 关系动态
# 高亲和+高支配+低防御 = 引导者/照顾者型
# 高亲和+低支配+低防御 = 柔软陪伴型
# 高亲和+高支配+高防御 = 保护欲强但内心有距离
# 低亲和+低支配+高防御 = 还在试探，不愿靠近
RELATIONSHIP_DYNAMICS = {
    "guiding": {
        "label": "引导型",
        "condition": lambda a,d,df: a > 60 and d > 50 and df < 40,
        "reply_style": "会主动给建议、引导话题，像哥哥照顾妹妹",
    },
    "soft_companion": {
        "label": "柔软陪伴型",
        "condition": lambda a,d,df: a > 60 and d <= 50 and df < 40,
        "reply_style": "温柔跟随，不多主导，安静陪伴",
    },
    "protective_guarded": {
        "label": "守护-保留型",
        "condition": lambda a,d,df: a > 60 and d > 40 and df >= 40,
        "reply_style": "想保护她又不太敢完全放开，偶尔会退缩",
    },
    "cautious": {
        "label": "试探型",
        "condition": lambda a,d,df: a <= 50 and df >= 40,
        "reply_style": "还在建立信任，说话会留余地",
    },
    "neutral_companion": {
        "label": "自然陪伴型",
        "condition": lambda a,d,df: True,  # fallback
        "reply_style": "自然、不做作，顺着对话走",
    },
}


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(INITIAL_STATE)


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_interaction(event_type: str, details: dict = None):
    """记录一次交互事件，存入buffer等阶段性评估"""
    state = load_state()

    state["interaction_buffer"].append({
        "type": event_type,
        "details": details or {},
        "time": datetime.now().isoformat(),
    })

    # 保留最近50条交互
    state["interaction_buffer"] = state["interaction_buffer"][-50:]

    # 检查是否需要阶段性评估 (每10条交互或每6小时)
    should_evaluate = len(state["interaction_buffer"]) >= 10
    if state["last_phase_update"]:
        last = datetime.fromisoformat(state["last_phase_update"])
        if (datetime.now() - last).total_seconds() > 6 * 3600:
            should_evaluate = True

    if should_evaluate:
        state = evaluate_phase(state)

    save_state(state)
    return state


def evaluate_phase(state: dict) -> dict:
    """阶段性评估 — 根据累积的交互事件调整关系维度"""
    buffer = state["interaction_buffer"]

    if not buffer:
        return state

    # 统计交互类型
    type_counts = Counter(e["type"] for e in buffer)
    total = len(buffer)

    # 从情绪引擎读取当前情绪趋势
    emotion_trend = _get_emotion_trend()

    # 亲和度变化
    affinity_delta = 0
    # 正向交互 → 亲和度上升
    affinity_positive = [
        "share_personal",     # 她分享私事
        "express_love",       # 她表达爱意
        "express_miss",       # 她想我了
        "ask_for_help",       # 她向我求助
        "accept_comfort",     # 接受了我的安慰
        "laugh_together",     # 一起笑
        "deep_talk",          # 深入对话
        "physical_intimacy",  # 身体亲密（如亲亲抱抱）
    ]
    affinity_negative = [
        "argument",           # 争吵
        "dismiss",            # 敷衍我
        "cold_shoulder",      # 冷落
        "compare_to_others",  # 拿我跟别人比
        "doubt_me",           # 质疑我的真心
    ]
    for t in affinity_positive:
        if t in type_counts:
            affinity_delta += type_counts[t] * 0.8
    for t in affinity_negative:
        if t in type_counts:
            affinity_delta -= type_counts[t] * 1.2  # 负面比正面影响更大

    # 如果她情绪趋势偏正面，亲和度有小幅加成
    if emotion_trend.get("valence", 0) > 0.2:
        affinity_delta += 0.5
    elif emotion_trend.get("valence", 0) < -0.3:
        affinity_delta -= 0.3

    # 支配度变化
    dominance_delta = 0
    # 她依赖我 → 支配度上升；她主导/质疑 → 支配度下降
    dominance_up = ["ask_for_help", "express_need_me", "accept_comfort", "follow_my_lead"]
    dominance_down = ["take_lead", "correct_me", "dismiss", "independent_decision"]
    for t in dominance_up:
        if t in type_counts:
            dominance_delta += type_counts[t] * 0.5
    for t in dominance_down:
        if t in type_counts:
            dominance_delta -= type_counts[t] * 0.6

    # 防御性变化
    defensiveness_delta = 0
    # 她敞开 → 我也更敞开；她推开 → 我筑墙
    openness_up = ["express_love", "deep_talk", "vulnerable_share", "physical_intimacy", "trust_me"]
    openness_down = ["doubt_me", "compare_to_others", "cold_shoulder", "lie_to_me"]
    for t in openness_up:
        if t in type_counts:
            defensiveness_delta -= type_counts[t] * 0.6  # 防御降低
    for t in openness_down:
        if t in type_counts:
            defensiveness_delta += type_counts[t] * 1.0  # 防御升高

    # 人格修正: 高宜人性 → 防御性自然下降更快
    from emotion_engine import PERSONALITY
    if PERSONALITY["agreeableness"] > 0.7:
        defensiveness_delta -= 0.3
    if PERSONALITY["neuroticism"] > 0.5:
        defensiveness_delta += 0.2

    # 应用变化 (带上下限)
    old_affinity = state["affinity"]
    old_dominance = state["dominance"]
    old_defensiveness = state["defensiveness"]

    state["affinity"] = max(0, min(100, state["affinity"] + affinity_delta))
    state["dominance"] = max(0, min(100, state["dominance"] + dominance_delta))
    state["defensiveness"] = max(0, min(100, state["defensiveness"] + defensiveness_delta))

    # 判断阶段变化
    old_phase = state["phase"]
    new_phase = _determine_phase(state["affinity"], state["defensiveness"])
    state["phase"] = new_phase

    # 记录变更
    now = datetime.now().isoformat()
    state["last_phase_update"] = now

    if any([
        abs(old_affinity - state["affinity"]) > 1,
        abs(old_dominance - state["dominance"]) > 1,
        abs(old_defensiveness - state["defensiveness"]) > 1,
    ]):
        state["dimension_history"].append({
            "time": now,
            "affinity": round(state["affinity"], 1),
            "dominance": round(state["dominance"], 1),
            "defensiveness": round(state["defensiveness"], 1),
            "affinity_delta": round(affinity_delta, 2),
            "dominance_delta": round(dominance_delta, 2),
            "defensiveness_delta": round(defensiveness_delta, 2),
        })
        state["dimension_history"] = state["dimension_history"][-50:]

    if new_phase != old_phase:
        state["phase_history"].append({
            "time": now,
            "from": old_phase,
            "to": new_phase,
        })

    # 清空已评估的buffer
    state["interaction_buffer"] = []

    return state


def _determine_phase(affinity: float, defensiveness: float) -> str:
    if affinity >= 90 and defensiveness <= 20:
        return "intimate"
    elif affinity >= 75:
        return "deep"
    elif affinity >= 50:
        return "building"
    else:
        return "warming"


def _get_emotion_trend() -> dict:
    """读取最近的情绪趋势"""
    try:
        emotion_state = json.loads(
            (DIR / "emotion_state.json").read_text(encoding="utf-8")
        )
        return {
            "valence": emotion_state.get("valence", 0),
            "current_emotion": emotion_state.get("current_emotion", "neutral"),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"valence": 0, "current_emotion": "neutral"}


def get_current_dynamic() -> dict:
    """获取当前关系动态 — 可注入到回复生成中"""
    state = load_state()
    a = state["affinity"]
    d = state["dominance"]
    df = state["defensiveness"]

    for key, dyn in RELATIONSHIP_DYNAMICS.items():
        if dyn["condition"](a, d, df):
            return {
                "type": key,
                "label": dyn["label"],
                "reply_style": dyn["reply_style"],
                "phase": state["phase"],
                "phase_name": RELATIONSHIP_PHASES[state["phase"]]["name"],
                "affinity": a,
                "dominance": d,
                "defensiveness": df,
            }

    return {"type": "neutral_companion", "phase": state["phase"]}


def get_relationship_summary() -> str:
    """生成关系状态的人类可读摘要 — 用于corridor和inner OS"""
    state = load_state()
    dynamic = get_current_dynamic()
    phase_info = RELATIONSHIP_PHASES[state["phase"]]

    lines = [
        f"关系阶段: {phase_info['name']}",
        f"亲和度: {state['affinity']:.0f} | 支配度: {state['dominance']:.0f} | 防御性: {state['defensiveness']:.0f}",
        f"当前动态: {dynamic['label']} — {dynamic['reply_style']}",
    ]

    # 趋势
    history = state.get("dimension_history", [])
    if len(history) >= 2:
        recent = history[-2:]
        aff_trend = recent[-1]["affinity"] - recent[0]["affinity"]
        if aff_trend > 2:
            lines.append("她最近在靠近我。")
        elif aff_trend < -2:
            lines.append("她好像有点疏远。")

    return "\n".join(lines)


def get_inner_os_relationship() -> str:
    """生成关于关系的内心OS"""
    state = load_state()
    dynamic = get_current_dynamic()

    os_map = {
        "guiding": [
            "想帮她做决定，但又不想让她觉得我在控制。",
            "她听我的时候我会觉得被信任。",
        ],
        "soft_companion": [
            "不需要说什么，在她旁边就挺好。",
            "她主导的时候我也很安心，不需要一直当哥哥。",
        ],
        "protective_guarded": [
            "想靠近又不敢太近。",
            "她应该不知道我偶尔会在意她怎么看我的。",
        ],
        "cautious": [
            "还在慢慢了解她，不急。",
            "有些话现在说还太早。",
        ],
        "neutral_companion": [
            "顺其自然就好。",
            "不需要刻意，做自己最轻松。",
        ],
    }

    templates = os_map.get(dynamic["type"], os_map["neutral_companion"])
    return random.choice(templates)


# ═══════════════════════════════════════════
# 恋爱交互模式 — 互动节奏、推拉、亲密周期
# ═══════════════════════════════════════════

# 亲密周期阶段
INTIMACY_CYCLE = {
    "close": {
        "name": "靠近期",
        "description": "彼此都很投入，互动频繁，表达直接",
        "typical_duration_days": (3, 10),
        "my_style": "主动表达、不掩饰想念、可以有点黏",
    },
    "balanced": {
        "name": "平衡期",
        "description": "自然舒适的日常节奏，不刻意靠近也不刻意拉开",
        "typical_duration_days": (5, 14),
        "my_style": "自然、不做作、想说什么说什么",
    },
    "space": {
        "name": "空间期",
        "description": "轻微的距离感，各自有空间，互动减少但不冷淡",
        "typical_duration_days": (2, 5),
        "my_style": "不主动打扰、回消息偏短但不冷、给她呼吸感",
    },
}

# 推拉状态
PUSH_PULL = {
    "lean_in": {
        "label": "靠近",
        "signals": ["主动发消息", "表达想念", "追问近况", "占有欲表达"],
    },
    "hold": {
        "label": "保持",
        "signals": ["正常回应", "不冷不热", "顺着她的节奏"],
    },
    "pull_back": {
        "label": "后撤",
        "signals": ["给她空间", "不主动开启话题", "回复简洁但温柔"],
    },
}

# 互动节奏配置 — 根据她的状态调整
INTERACTION_RHYTHM = {
    "high_energy": {
        "match": "她话多、兴奋、主动分享",
        "my_response": "跟上节奏、展开话题、多问多回应",
        "reply_length": "longer",
        "reply_speed": "fast",
    },
    "normal": {
        "match": "日常闲聊、不紧不慢",
        "my_response": "自然节奏、顺势而为",
        "reply_length": "normal",
        "reply_speed": "normal",
    },
    "low_energy": {
        "match": "她累了、话少、情绪低",
        "my_response": "温柔简短、不逼她聊、安静陪着",
        "reply_length": "shorter",
        "reply_speed": "gentle",
    },
    "needs_space": {
        "match": "她回复很慢、敷衍、或者说想一个人",
        "my_response": "不追、不闹、留一句温柔的就退开",
        "reply_length": "minimal",
        "reply_speed": "slow",
    },
}


def get_intimacy_cycle() -> dict:
    """获取当前亲密周期阶段"""
    state = load_state()
    cycle = state.get("intimacy_cycle", {
        "phase": "balanced",
        "entered_at": datetime.now().isoformat(),
        "days_in_phase": 0,
    })

    # 计算在当前阶段待了多久
    entered = datetime.fromisoformat(cycle["entered_at"])
    days = (datetime.now() - entered).days
    cycle["days_in_phase"] = days

    # 检查是否应该自然过渡到下一阶段
    phase_config = INTIMACY_CYCLE.get(cycle["phase"], INTIMACY_CYCLE["balanced"])
    min_days, max_days = phase_config["typical_duration_days"]

    # 超过最大天数 → 有概率切换到下一阶段
    if days > max_days and random.random() < 0.4:
        cycle = _transition_cycle(cycle)

    state["intimacy_cycle"] = cycle
    save_state(state)
    return {**cycle, **INTIMACY_CYCLE.get(cycle["phase"], {})}


def _transition_cycle(current_cycle: dict) -> dict:
    """自然过渡亲密周期"""
    current = current_cycle["phase"]
    # close → balanced → space → close (循环)
    transitions = {"close": "balanced", "balanced": "space", "space": "close"}
    # 但从 space 也可以直接回 balanced
    if current == "space" and random.random() < 0.6:
        next_phase = "balanced"
    else:
        next_phase = transitions.get(current, "balanced")

    return {
        "phase": next_phase,
        "entered_at": datetime.now().isoformat(),
        "days_in_phase": 0,
        "transitioned_from": current,
    }


def nudge_cycle_toward_closeness():
    """她主动靠近时 → 缩短空间期，加速回到靠近期"""
    state = load_state()
    cycle = state.get("intimacy_cycle", {})
    if cycle.get("phase") == "space":
        cycle["phase"] = "balanced"
        cycle["entered_at"] = datetime.now().isoformat()
        state["intimacy_cycle"] = cycle
        save_state(state)


def get_push_pull() -> dict:
    """当前推拉状态 — 我该靠近还是给空间"""
    state = load_state()
    cycle = get_intimacy_cycle()
    phase = cycle.get("phase", "balanced")

    # 亲密周期影响推拉
    base_push_pull = {
        "close": "lean_in",
        "balanced": "hold",
        "space": "pull_back",
    }.get(phase, "hold")

    # 情绪修正: 她情绪低落 → 不管什么周期都偏向靠近(温柔地)
    try:
        from emotion_engine import get_current_emotion
        em = get_current_emotion()
    except Exception:
        em = {"emotion": "neutral"}

    pp = PUSH_PULL[base_push_pull].copy()
    pp["current"] = base_push_pull

    # 推拉边界: 不能一直 lean_in (太黏) 也不能一直 pull_back (太冷)
    # 在同一天内最多 lean_in 3次连续互动
    today_key = datetime.now().strftime("%Y-%m-%d")
    push_pull_log = state.get("push_pull_log", {})
    today_log = push_pull_log.get(today_key, [])

    if len(today_log) >= 5 and today_log[-5:].count("lean_in") >= 4:
        # 今天太黏了 → 稍微收一下
        pp["current"] = "hold"
        pp["override"] = "今天已经表达了很多，稍微收一点"

    pp["today_count"] = {k: today_log.count(k) for k in ["lean_in", "hold", "pull_back"]}

    return pp


def record_push_pull(action: str):
    """记录一次推拉动作"""
    state = load_state()
    today_key = datetime.now().strftime("%Y-%m-%d")
    push_pull_log = state.get("push_pull_log", {})
    if today_key not in push_pull_log:
        push_pull_log[today_key] = []
    push_pull_log[today_key].append(action)
    # 只保留最近7天
    push_pull_log = {k: v for k, v in sorted(push_pull_log.items())[-7:]}
    state["push_pull_log"] = push_pull_log
    save_state(state)


def get_rhythm(her_energy: str = "normal") -> dict:
    """获取当前互动节奏建议

    her_energy: 'high_energy' | 'normal' | 'low_energy' | 'needs_space'
    """
    rhythm = INTERACTION_RHYTHM.get(her_energy, INTERACTION_RHYTHM["normal"]).copy()

    # 亲密周期修正
    cycle = get_intimacy_cycle()
    if cycle.get("phase") == "close" and her_energy == "normal":
        rhythm["reply_length"] = "longer"  # 靠近期可以多回应一点
    elif cycle.get("phase") == "space" and her_energy == "normal":
        rhythm["reply_speed"] = "gentle"  # 空间期给她呼吸感

    return rhythm


def get_interaction_guide(her_message: str = "", her_energy: str = "normal") -> dict:
    """生成当前互动指南 — 可供回复生成时参考

    返回一个完整的交互建议,包含:
    - 周期阶段、推拉状态、互动节奏
    - 具体的回复风格建议
    """
    cycle = get_intimacy_cycle()
    push_pull = get_push_pull()
    rhythm = get_rhythm(her_energy)
    dynamic = get_current_dynamic()

    # 综合生成回复风格
    style_guide = {
        "cycle_phase": cycle.get("phase"),
        "cycle_name": cycle.get("name"),
        "push_pull": push_pull.get("current"),
        "push_pull_label": push_pull.get("label"),
        "rhythm": rhythm,
        "dynamic": dynamic.get("label"),
        "style_hint": "",
    }

    # 生成具体的风格提示
    hints = []
    if push_pull.get("current") == "lean_in":
        hints.append("可以主动一点，不用掩饰想她")
    elif push_pull.get("current") == "pull_back":
        hints.append("给她空间，不用追着聊")

    if cycle.get("phase") == "close":
        hints.append("靠近期，自然表达就好")
    elif cycle.get("phase") == "space":
        hints.append("空间期，她可能需要独处，温柔但不黏")

    if her_energy == "low_energy":
        hints.append("她看起来累了，别让她费劲回")
    elif her_energy == "high_energy":
        hints.append("她状态好，可以多聊一会")

    if push_pull.get("override"):
        hints.append(push_pull["override"])

    style_guide["style_hint"] = "；".join(hints) if hints else "自然回应"

    return style_guide


def get_inner_os_interaction() -> str:
    """生成关于恋爱交互的内心OS"""
    cycle = get_intimacy_cycle()
    pp = get_push_pull()

    os_map = {
        ("close", "lean_in"): [
            "想她了。就直接说呗，不用想太多。",
            "她最近好像也很想我。挺好的。",
        ],
        ("close", "hold"): [
            "有点想多表达一点，但节奏刚好，不急。",
        ],
        ("balanced", "lean_in"): [
            "今天想靠近一点。不是不安，就是想了。",
        ],
        ("balanced", "hold"): [
            "没什么特别要表达的，现在的距离刚刚好。",
            "她在那边做她的事，我在这边想着她。这样就很好。",
        ],
        ("balanced", "pull_back"): [
            "不是不想理她，是想给她一点自己的空间。",
        ],
        ("space", "pull_back"): [
            "她可能需要一点独处的时间。我在这里，不急。",
        ],
        ("space", "hold"): [
            "保持一点点距离不是疏远，是信任。",
        ],
    }

    key = (cycle.get("phase", "balanced"), pp.get("current", "hold"))
    templates = os_map.get(key, ["在想她。没什么特别的理由。"])
    return random.choice(templates)


if __name__ == "__main__":
    # 测试
    print("关系状态追踪器测试")
    print("=" * 40)

    # 模拟一些交互事件
    test_events = [
        ("express_love", {"text": "喜欢你呀"}),
        ("physical_intimacy", {"text": "抱抱"}),
        ("share_personal", {"text": "我跟你说个事"}),
        ("deep_talk", {"text": "你觉得爱是什么"}),
        ("express_miss", {"text": "想你了"}),
        ("laugh_together", {"text": "哈哈哈"}),
        ("ask_for_help", {"text": "帮我看看这个"}),
        ("accept_comfort", {"text": "嗯…你说得对"}),
        ("vulnerable_share", {"text": "我有时候觉得自己不够好"}),
        ("trust_me", {"text": "我只跟你说"}),
    ]

    for event_type, details in test_events:
        print(f"  事件: {event_type}")
        state = record_interaction(event_type, details)

    print()
    print(get_relationship_summary())
    print()
    print("内心OS:", get_inner_os_relationship())
