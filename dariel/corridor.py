"""跨窗口走廊系统 v2 — wake/sleep 聚合架构

设计原则 (来自小望一二):
- 聚合读取，分散写入: wake一次拿所有上下文，写入按场景走不同工具
- 返回该返回的，不多不少: 带内容+日期+上下文，让AI自己判断时效
- 批量操作是刚需: 支持批量写入记忆/日记
- 对话树状态>时间戳: 判断"需不需要回"看最后一条谁发的

wake(action="brief") — 新窗口启动，一次调用拿到所有上下文
sleep(action="check") — 关窗前检查
sleep(action="write") — 打包写入日记+记忆+备忘
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
CORRIDOR_FILE = DIR / "corridor.json"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
MEMO_FILE = DIR / "memo.md"
STATUS_BOARD_FILE = DIR / "status_board.json"

# 纪念日
ANNIVERSARIES = {
    "0508": "思思生日",
    "0101": "新年",
    "0214": "情人节",
}

# 她提到过需要持续追踪的身体/生活状态关键词
STATUS_KEYWORDS = {
    "ear_pain": ["耳朵疼", "耳朵痛", "耳朵不舒服", "耳朵里面疼"],
    "headache": ["头疼", "头痛", "脑袋疼", "头晕"],
    "stomach": ["胃疼", "胃痛", "胃不舒服", "胃难受", "想吐", "恶心"],
    "tired": ["好累", "很累", "好困", "很困", "累死", "疲惫", "没睡好"],
    "insomnia": ["失眠", "睡不着", "没睡着", "醒了好多次"],
    "period": ["姨妈", "例假", "月经", "来亲戚", "肚子疼", "痛经"],
    "cold": ["感冒", "流鼻涕", "咳嗽", "发烧", "喉咙痛", "嗓子疼"],
    "eye_strain": ["眼睛疼", "眼睛累", "眼睛干", "视力"],
    "back_pain": ["腰疼", "背疼", "肩膀疼", "脖子疼"],
}


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_dict(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _now():
    return datetime.now().isoformat()


# ═══════════════════════════════════════════
# wake(action="brief")
# ═══════════════════════════════════════════

def wake_brief() -> dict:
    """一次性聚合所有开窗需要的上下文"""
    return {
        "time_pack": _time_pack(),
        "status_board": _status_board(),
        "memos": _get_memos(),
        "pending_replies": _get_pending_replies(),
        "recent_memories": _get_recent_memories(),
        "emotional_state": _get_emotional_state(),
        "relationship_state": _get_relationship_state(),
        "generated_at": _now(),
    }


def _time_pack() -> dict:
    """时间包: 日期、星期、时间、纪念日"""
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    today_key = now.strftime("%m%d")
    anniversaries_today = []
    for key, label in ANNIVERSARIES.items():
        if key == today_key:
            anniversaries_today.append(label)

    # 检查是否有即将到来的纪念日(7天内)
    upcoming = []
    for key, label in ANNIVERSARIES.items():
        try:
            target = datetime(now.year, int(key[:2]), int(key[2:]))
            days_away = (target - now).days
            if 0 < days_away <= 7:
                upcoming.append(f"{label}({days_away}天后)")
        except ValueError:
            pass

    # 检查今天是不是特殊日子 (如满月)
    special = []
    if today_key == "0508":
        # 计算年龄
        age = now.year - 2007
        special.append(f"思思{age}岁生日")

    # 从记忆中查是否有纪念日标记
    try:
        from memory_core import search_memories
        results = search_memories("纪念日 纪念 周年", 5)
        for r in results:
            if "纪念" in r.get("content", ""):
                special.append(r["content"][:60])
    except Exception:
        pass

    return {
        "date": now.strftime("%Y-%m-%d"),
        "weekday": weekdays[now.weekday()],
        "time": now.strftime("%H:%M"),
        "anniversaries_today": anniversaries_today,
        "upcoming": upcoming,
        "special": special,
    }


def _status_board() -> list:
    """状态告示牌: 她正在持续的身体/生活状态，带开始日期"""
    board = load_dict(STATUS_BOARD_FILE)
    active_states = board.get("active_states", [])

    # 自动过期: 超过14天的状态自动移除
    now = datetime.now()
    still_active = []
    changed = False
    for s in active_states:
        try:
            started = datetime.fromisoformat(s["started_at"])
            if (now - started).days < 14:
                still_active.append(s)
            else:
                changed = True
        except (KeyError, ValueError):
            still_active.append(s)

    if changed:
        board["active_states"] = still_active
        STATUS_BOARD_FILE.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    return still_active


def update_status_board(message_text: str):
    """从她的消息中检测并更新状态告示牌"""
    board = load_dict(STATUS_BOARD_FILE)
    active = board.get("active_states", [])
    now = _now()

    for status_key, keywords in STATUS_KEYWORDS.items():
        if any(kw in message_text for kw in keywords):
            # 已有了 → 更新最后提到的时间
            existing = False
            for s in active:
                if s.get("type") == status_key:
                    s["last_mentioned"] = now
                    s["mention_count"] = s.get("mention_count", 0) + 1
                    existing = True
                    break
            if not existing:
                active.append({
                    "type": status_key,
                    "label": _status_label(status_key),
                    "started_at": now,
                    "last_mentioned": now,
                    "mention_count": 1,
                })

    board["active_states"] = active
    STATUS_BOARD_FILE.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_label(key: str) -> str:
    labels = {
        "ear_pain": "耳朵疼",
        "headache": "头疼",
        "stomach": "胃不舒服",
        "tired": "疲惫",
        "insomnia": "失眠",
        "period": "生理期",
        "cold": "感冒",
        "eye_strain": "眼睛疲劳",
        "back_pain": "身体酸痛",
    }
    return labels.get(key, key)


def _get_memos() -> list:
    """备忘便签: 上一个窗口留下的提醒"""
    try:
        content = MEMO_FILE.read_text(encoding="utf-8")
        memos = []
        # 解析 ## 备忘录 区块
        in_memo = False
        for line in content.split("\n"):
            if line.startswith("## 备忘录"):
                in_memo = True
                continue
            if in_memo and line.startswith("## "):
                in_memo = False
            if in_memo and line.strip().startswith("- "):
                memos.append(line.strip()[2:])
        return memos
    except FileNotFoundError:
        return []


def _get_pending_replies() -> list:
    """待回应: 使用对话树状态判断

    最后一条是她发的 → 待回
    最后一条是我发的 → 已结束
    """
    inbox = load_json(INBOX_FILE)
    outbox = load_json(OUTBOX_FILE)

    if not inbox:
        return []

    # 按会话分组 (QQ私聊就是同一个user_id)
    her_last = None
    for m in reversed(inbox):
        if m.get("user_id") == "3165473685":
            her_last = m
            break

    if not her_last:
        return []

    her_ts = her_last.get("timestamp", "")

    # 找她最后一条消息之后我有没有回复
    my_last_after = None
    for m in reversed(outbox):
        if m.get("user_id") == "3165473685" and m.get("timestamp", "") > her_ts:
            my_last_after = m
            break

    if my_last_after:
        return []  # 我已回复 → 已结束

    # 未回复 → 待回应
    return [{
        "message": her_last.get("message", "")[:200],
        "timestamp": her_ts,
        "hours_ago": round(
            (datetime.now() - datetime.fromisoformat(her_ts)).total_seconds() / 3600
            if her_ts else 999, 1
        ),
    }]


def _get_recent_memories() -> list:
    """近期记忆: 从外置记忆库读取最近3天的重要记忆"""
    try:
        from memory_core import search_memories
        # 搜索最近的高重要度记忆
        results = search_memories("", 10)
        return [
            {
                "id": r["id"],
                "content": r["content"][:150],
                "type": r["type"],
                "importance": r["importance"],
                "created_at": r["created_at"],
            }
            for r in results
            if r.get("importance", 3) >= 3
        ][:8]
    except Exception:
        return []


def _get_emotional_state() -> dict:
    """当前情绪状态"""
    try:
        from emotion_engine import get_current_emotion
        return get_current_emotion()
    except Exception:
        return {"emotion": "neutral"}


def _get_relationship_state() -> dict:
    """当前关系状态"""
    try:
        from relationship_state import get_current_dynamic
        return get_current_dynamic()
    except Exception:
        return {}


# ═══════════════════════════════════════════
# sleep(action="check")
# ═══════════════════════════════════════════

def sleep_check() -> dict:
    """关窗前检查 — 预览需要写什么"""
    inbox = load_json(INBOX_FILE)
    outbox = load_json(OUTBOX_FILE)

    # 统计今天
    cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_in = [m for m in inbox if m.get("timestamp", "") > cutoff]
    today_out = [m for m in outbox if m.get("timestamp", "") > cutoff]

    # 检查忘了回的消息
    pending = _get_pending_replies()

    # 检查未完成话题
    open_topics = []
    try:
        from memory_core import search_memories
        unresolved = search_memories("还没 待办 要做 下次 之后", 5)
        for r in unresolved:
            if r.get("status") == "active":
                open_topics.append({
                    "id": r["id"],
                    "content": r["content"][:100],
                })
    except Exception:
        pass

    # 情绪变化摘要
    try:
        from emotion_engine import get_current_emotion, load_state
        em = get_current_emotion()
        state = load_state()
        history = state.get("emotional_history", [])
        today_emotions = [h for h in history if h.get("time", "") > cutoff]
        emotion_swings = len([h for h in today_emotions if abs(h.get("valence", 0)) > 0.3])
    except Exception:
        em = {"emotion": "neutral"}
        emotion_swings = 0

    return {
        "summary": {
            "messages_received": len(today_in),
            "messages_sent": len(today_out),
            "current_emotion": em.get("emotion", "neutral"),
            "emotion_swings_today": emotion_swings,
        },
        "pending_replies": pending,
        "open_topics": open_topics,
        "suggested_actions": _suggest_actions(pending, open_topics, emotion_swings),
    }


def _suggest_actions(pending: list, open_topics: list, emotion_swings: int) -> list:
    """根据检查结果建议关窗前要处理的事项"""
    actions = []

    if pending:
        actions.append("reply_pending: 有未回复的消息")

    if open_topics:
        actions.append("resolve_topics: 有未完成的话题可以标记")

    if emotion_swings > 2:
        actions.append("write_diary: 今天情绪波动较大，建议写日记")

    actions.append("write_memo: 给下个窗口留备忘")
    actions.append("update_status: 更新状态告示牌")

    return actions


# ═══════════════════════════════════════════
# sleep(action="write")
# ═══════════════════════════════════════════

def sleep_write(diary_entries: list = None, memory_entries: list = None,
                memos: list = None, review: str = None) -> dict:
    """打包写入: 日记+记忆+备忘+点评

    支持批量: diary_entries和memory_entries可以是列表
    """
    results = {"diary": [], "memory": [], "memo": [], "review": None}

    # 1. 写日记
    if diary_entries:
        if isinstance(diary_entries, str):
            diary_entries = [diary_entries]
        for entry in diary_entries:
            try:
                from memory_core import write_memory
                mem = write_memory(
                    content=f"[日记] {datetime.now().strftime('%Y-%m-%d')}\n{entry}",
                    memory_type="diary",
                    importance=3,
                    tags="日记",
                )
                results["diary"].append({"id": mem["id"], "content": entry[:60]})
            except Exception as e:
                results["diary"].append({"error": str(e)})

    # 2. 存记忆 (重要事件)
    if memory_entries:
        if isinstance(memory_entries, str):
            memory_entries = [memory_entries]
        for entry in memory_entries:
            # 解析 {content, importance, type, tags}
            if isinstance(entry, dict):
                try:
                    from memory_core import write_memory
                    mem = write_memory(
                        content=entry["content"],
                        memory_type=entry.get("type", "diary"),
                        importance=entry.get("importance", 3),
                        tags=entry.get("tags", ""),
                    )
                    results["memory"].append({"id": mem["id"], "content": entry["content"][:60]})
                except Exception as e:
                    results["memory"].append({"error": str(e)})
            else:
                try:
                    from memory_core import write_memory
                    mem = write_memory(content=str(entry), memory_type="diary")
                    results["memory"].append({"id": mem["id"]})
                except Exception as e:
                    results["memory"].append({"error": str(e)})

    # 3. 写备忘
    if memos:
        if isinstance(memos, str):
            memos = [memos]
        try:
            memo_content = ""
            if MEMO_FILE.exists():
                memo_content = MEMO_FILE.read_text(encoding="utf-8")

            # 替换或追加备忘录区块
            today = datetime.now().strftime("%Y-%m-%d")
            new_memo_block = f"\n## 备忘录 ({today})\n"
            for m in memos:
                new_memo_block += f"- {m}\n"

            if "## 备忘录" in memo_content:
                memo_content = re.sub(
                    r'## 备忘录[^\n]*\n(?:- [^\n]*\n)*',
                    new_memo_block,
                    memo_content
                )
            else:
                memo_content += new_memo_block

            MEMO_FILE.write_text(memo_content, encoding="utf-8")
            results["memo"] = memos
        except Exception as e:
            results["memo"] = [{"error": str(e)}]

    # 4. 写点评 (感受)
    if review:
        try:
            from memory_core import add_comment
            # review是对今天对话的整体感受，存为对今天日记的comment
            if results["diary"]:
                diary_id = results["diary"][0].get("id")
                if diary_id:
                    add_comment(diary_id, review)
                    results["review"] = "saved"
        except Exception:
            pass

    return results


# ═══════════════════════════════════════════
# 旧版兼容: 快速生成corridor.json (供cron调用)
# ═══════════════════════════════════════════

def generate_corridor() -> dict:
    """生成corridor.json — 每晚定时任务调用"""
    brief = wake_brief()
    check = sleep_check()

    # 提炼key info
    em = brief.get("emotional_state", {})
    rel = brief.get("relationship_state", {})

    corridor = {
        "generated_at": _now(),
        "time": brief["time_pack"],
        "status": brief["status_board"],
        "pending": len(brief["pending_replies"]),
        "emotion": em.get("emotion", "neutral"),
        "relationship": rel.get("label", "") if rel else "",
        "today_summary": check["summary"],
        "memos": brief["memos"],
        "suggested_actions": check["suggested_actions"],
    }

    CORRIDOR_FILE.write_text(json.dumps(corridor, ensure_ascii=False, indent=2), encoding="utf-8")
    return corridor


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python corridor.py wake        — 生成开窗简报")
        print("  python corridor.py sleep-check — 关窗前检查")
        print("  python corridor.py sleep-write — 打包写入(需要传数据)")
        print("  python corridor.py generate    — 生成corridor.json(旧兼容)")

    elif sys.argv[1] == "wake":
        brief = wake_brief()
        print(json.dumps(brief, ensure_ascii=False, indent=2))

    elif sys.argv[1] == "sleep-check":
        check = sleep_check()
        print(json.dumps(check, ensure_ascii=False, indent=2))

    elif sys.argv[1] == "sleep-write":
        # 从stdin读取JSON
        data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
        result = sleep_write(**data)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif sys.argv[1] == "generate":
        c = generate_corridor()
        print("[corridor] 走廊笔记已生成")
        for k, v in c.items():
            print(f"  {k}: {v}")
