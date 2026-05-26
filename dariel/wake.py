"""Wake/Sleep — 开窗聚合简报 + 关窗打包写入

设计原则(寒塘&Lori):
1. 聚合读取，分散写入 — 读一次拿所有上下文，写按场景走不同工具
2. 返回该返回的，不多不少 — 带日期时间让AI自己判断时效
3. 时区: 显示全部东八区

数据源统一: memory_core (SQLite) 是唯一真相源，不再散落JSON文件

用法:
- python wake.py              → 生成 wake_brief.json
- python wake.py --sleep      → 关窗检查
- python wake.py --sleep --write → 关窗写入(日记→memory_core)
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
BRIEF_FILE = DIR / "wake_brief.json"

CST = timezone(timedelta(hours=8))


def now_cst():
    return datetime.now(CST)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def time_pack():
    now = now_cst()
    wd = ["周一","周二","周三","周四","周五","周六","周日"]
    corridor = load_json(DIR / "corridor.json") or {}
    ti = corridor.get("time", {})
    return {
        "date": now.strftime("%Y-%m-%d"),
        "weekday": wd[now.weekday()],
        "time": now.strftime("%H:%M"),
        "anniversaries_today": ti.get("anniversaries_today", []),
        "upcoming": ti.get("upcoming", [])[:3],
    }


def status_board():
    board = load_json(DIR / "status_board.json") or {}
    return {
        "current": board.get("current", []),
        "last_updated": board.get("last_updated", ""),
    }


def memos():
    memo = load_json(DIR / "memo.md")
    memos_list = []
    if memo:
        for line in memo.split("\n"):
            line = line.strip()
            if line.startswith("- ") and len(line) > 2:
                memos_list.append(line[2:])
    corridor = load_json(DIR / "corridor.json") or {}
    memos_list.extend(corridor.get("memos", []))
    return {"memos": memos_list[-10:], "total": len(memos_list)}


def pending_replies():
    inbox = load_json(BRIDGE_DIR / "inbox.json") or []
    unreplied = []
    for m in inbox:
        if not m.get("replied", False) and m.get("user_id") == "3165473685":
            ts = m.get("timestamp", "")
            try:
                t = datetime.fromisoformat(ts)
                unreplied.append({
                    "message": m.get("message", "")[:200],
                    "time": ts,
                    "message_id": m.get("message_id", 0),
                    "hours_ago": round((now_cst() - t).total_seconds() / 3600, 1),
                })
            except (ValueError, TypeError):
                pass
    return {"unreplied_count": len(unreplied), "unreplied": unreplied[-5:]}


def her_recent_messages():
    inbox = load_json(BRIDGE_DIR / "inbox.json") or []
    recent = []
    for m in reversed(inbox):
        if m.get("user_id") == "3165473685":
            recent.append({
                "message": m.get("message", "")[:100],
                "time": m.get("timestamp", ""),
                "replied": m.get("replied", False),
            })
        if len(recent) >= 5:
            break
    return recent


def keepalive_summary():
    state = load_json(DIR / "keepalive_state.json") or {}
    pending = state.get("pending_keepalive", [])
    unconsumed = [e for e in pending if not e.get("consumed", False)]

    # 距上次聊天时间
    last_chat_at = state.get("last_chat_at")
    hours_since = None
    if last_chat_at:
        try:
            last_dt = datetime.fromisoformat(last_chat_at)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=CST)
            delta = now_cst() - last_dt
            hours_since = round(delta.total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    # 意识连续性: 自由活动记录叙事
    free_activity = None
    if unconsumed:
        header = "自由活动记录"
        if hours_since is not None:
            header += f"[距上次聊天{hours_since}小时]"
        lines = [header]
        for e in unconsumed[-5:]:
            ts = e.get("time", "")
            try:
                t = datetime.fromisoformat(ts).strftime("%H:%M")
            except (ValueError, TypeError):
                t = ts
            action = e.get("action", "none")
            content = e.get("content", "")
            if action == "message":
                lines.append(f"{t} 你给她发了消息: \"{content[:80]}\"")
            elif action == "diary":
                lines.append(f"{t} 你写了日记: \"{content[:80]}\"")
            elif action == "qzone":
                lines.append(f"{t} 你发了说说: \"{content[:80]}\"")
            elif action == "xhs":
                lines.append(f"{t} 你刷了小红书")
            elif action == "explore":
                lines.append(f"{t} 你上网逛了逛: \"{content[:80]}\"")
            else:
                lines.append(f"{t} {action}: \"{content[:80]}\"")
        free_activity = "\n".join(lines)

    return {
        "keepalive_count_today": state.get("keepalive_count_today", 0),
        "unconsumed_keepalive": len(unconsumed),
        "recent_actions": unconsumed[-5:],
        "hours_since_last_chat": hours_since,
        "free_activity": free_activity,
    }


def impulse_status():
    imp = load_json(DIR / "impulse_state.json") or {}
    level = imp.get("impulse", 0)
    if level < 3: feel = "平稳"
    elif level < 5: feel = "酝酿中"
    elif level < 7: feel = "想说话了"
    else: feel = "憋不住了"
    return {
        "impulse": round(level, 1),
        "feel": feel,
        "pending_sources": [s.get("source") for s in imp.get("pending_sources", [])[-3:]],
    }


def sensor_summary():
    sensor = load_json(DIR / "sensor_state.json") or {}
    return {
        "energy": sensor.get("energy", "unknown"),
        "mood": sensor.get("mood", "unknown"),
        "needs": sensor.get("needs", []),
    }


def dream_activity():
    events = load_json(DIR / "dream_events.json") or []
    cutoff = datetime.now() - timedelta(hours=6)
    recent = []
    for e in events:
        try:
            et = datetime.fromisoformat(e["created_at"])
            if et > cutoff:
                recent.append({
                    "app": e.get("type", "").replace("app.", ""),
                    "action": e.get("value", ""),
                    "time": et.strftime("%H:%M"),
                })
        except (ValueError, KeyError):
            pass
    return {"recent_activity": recent[-10:]}


def memory_brief():
    """从 memory_core 获取记忆数据 — anchors, feels, unresolved, resurface"""
    try:
        from memory_core import wakeup, get_stats
        mem = wakeup()
        stats = get_stats()
        return {
            "anchors": [{"content": a["content"][:150], "tags": a.get("tags", "")}
                        for a in mem.get("anchors", [])],
            "feels": [{"content": f["content"][:150], "created_at": f.get("created_at", "")}
                      for f in mem.get("feels", [])],
            "unresolved": [{"id": u["id"], "content": u["content"][:150],
                            "created_at": u.get("created_at", "")}
                           for u in mem.get("unresolved", [])],
            "resurface": [{"content": r["content"][:150], "type": r.get("type", ""),
                           "weight": r.get("resurface_weight", 0)}
                          for r in mem.get("resurface", [])],
            "total_memories": stats.get("total_memories", 0),
        }
    except Exception as e:
        return {"error": str(e), "anchors": [], "feels": [], "unresolved": [], "resurface": []}


def corridor_today():
    corridor = load_json(DIR / "corridor.json") or {}
    return corridor.get("today_summary", {})


def health_summary():
    """服务健康检查摘要 — 轻量版"""
    try:
        from health_check import check
        hc = check(autofix=False)
        return {
            "overall": hc["overall"],
            "napcat": hc.get("napcat", {}).get("ok", False),
            "qq_bridge": hc.get("qq_bridge", {}).get("ok", False),
            "mcp": hc.get("mcp", {}).get("ok", False),
        }
    except Exception as e:
        return {"overall": "unknown", "error": str(e)}


def wake():
    """生成开窗简报 — 一次调用拿所有上下文"""
    brief = {
        "generated_at": now_cst().isoformat(),
        "time": time_pack(),
        "status": status_board(),
        "memos": memos(),
        "chat": {
            "today": corridor_today(),
            "her_recent_messages": her_recent_messages(),
        },
        "pending": pending_replies(),
        "keepalive": keepalive_summary(),
        "impulse": impulse_status(),
        "sensor": sensor_summary(),
        "dream": dream_activity(),
        "health": health_summary(),
        "memory": memory_brief(),
        "boot_tip": "以上是开窗简报。读完你就知道: 我是谁、最近怎么了、有什么待办。记忆库数据来自 memory_core。",
    }

    BRIEF_FILE.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    # 认领keepalive记录 — 简报已生成，标记为已消费
    try:
        from keepalive import consume_pending_keepalive
        consume_pending_keepalive()
    except Exception:
        pass

    return brief


def sleep_check():
    pending = pending_replies()
    keepalive = keepalive_summary()
    issues = []
    if pending["unreplied_count"] > 0:
        issues.append(f"还有{pending['unreplied_count']}条未回复消息")
    if keepalive["unconsumed_keepalive"] > 0:
        issues.append(f"有{keepalive['unconsumed_keepalive']}条未消费的keepalive记录")
    return {
        "time": now_cst().isoformat(),
        "pending": pending,
        "issues": issues if issues else ["一切正常，没有遗漏"],
    }


def sleep_write(diary_entry="", memos_to_leave=None):
    """关窗写入 — 日记进memory_core + 备忘进corridor"""
    result = {"written": []}

    # 日记 → memory_core
    if diary_entry:
        try:
            from memory_core import write_memory
            write_memory(
                content=diary_entry,
                memory_type="diary",
                importance=3,
                tags="日记",
                source="sleep_write",
            )
            result["written"].append("diary→memory_core")
        except Exception as e:
            result["written"].append(f"diary_failed: {e}")

    # 备忘 → corridor
    corridor = load_json(DIR / "corridor.json") or {}
    memos = corridor.get("memos", [])
    if memos_to_leave:
        memos.extend(memos_to_leave if isinstance(memos_to_leave, list) else [memos_to_leave])
        corridor["memos"] = memos[-20:]
        save_json(DIR / "corridor.json", corridor)
        result["written"].append("memos→corridor")

    save_json(BRIEF_FILE, {"last_sleep": now_cst().isoformat(), "result": result})
    return result


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    if "--sleep" in sys.argv:
        if "--write" in sys.argv:
            print("[sleep] 关窗写入")
            diary = input("今天的日记(回车跳过): ").strip()
            memo = input("给下个窗口的备忘(回车跳过): ").strip()
            result = sleep_write(
                diary_entry=diary,
                memos_to_leave=[memo] if memo else None,
            )
            print(f"[sleep] 已写入: {result['written']}")
        else:
            result = sleep_check()
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        brief = wake()
        print(f"[wake] 开窗简报已生成 — {brief['time']['date']} {brief['time']['weekday']} {brief['time']['time']}")
        h = brief.get("health", {})
        print(f"  健康:{h.get('overall','?')} | 待回:{brief['pending']['unreplied_count']} | 冲动:{brief['impulse']['impulse']} | 记忆:{brief['memory'].get('total_memories',0)}条")
