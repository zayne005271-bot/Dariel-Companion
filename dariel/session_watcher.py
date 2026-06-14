"""
Session Watcher v2.0 — 完整切窗交接系统
每分钟检查上下文token用量，超150k自动触发切窗交接。

完整流程(参考小红书鹤见老师+眠眠豹老师方案):
  ① 读CC jsonl → 获取真实token用量(usage.input_tokens累计)
  ② token > 150k → 触发交接
  ③ 写handover摘要 → memory_core 交接pin桶(覆写模式)
  ④ 提取旧窗最近20轮对话 → session_context.txt
  ⑤ 归档旧 chat_history (rename jsonl → .archived)
  ⑥ 写入 flag 文件通知需要切窗

SessionStart hook (由 wake.py/BP1 自动处理):
  - breath: wake.py → memory_brief() 浮现记忆
  - context_inject: wake.py → session_context() 读入上下文

用法:
  python session_watcher.py          # 前台运行(调试)
  pythonw.exe session_watcher.py     # 后台运行(生产)
"""
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

DIR = Path(__file__).parent
if str(DIR) not in sys.path:
    sys.path.insert(0, str(DIR))

CC_PROJECT_DIR = Path.home() / ".claude" / "projects" / "C--Users-31654-Desktop"
CC_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CONTEXT_FILE = DIR / "session_context.txt"
HANDOVER_FILE = DIR / "session_handover.json"
LOG_FILE = DIR / "session_watcher.log"
PID_FILE = DIR / "session_watcher.pid"
FLAG_FILE = DIR / "session_handover.flag"       # 通知需要切窗

# ═══════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════
CHECK_INTERVAL = 60           # 检查间隔(秒)
TOKEN_WARN = 150000           # 告警水位 (200k上下文的75%)
TOKEN_CRITICAL = 190000       # 紧急水位 (95%)
IDLE_TIMEOUT = 1800           # 无活动超时(秒)，30分钟
HANDOVER_TURNS = 20           # 交接保留最近N轮对话
MAX_CONTEXT_AGE = 14400       # 上下文文件最大年龄(秒)，4小时


# ═══════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════
def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass
    try:
        print(line, flush=True)
    except:
        pass


# ═══════════════════════════════════════════════
# 第1步: 检测活跃 session + 真实 token 用量
# ═══════════════════════════════════════════════
def get_active_session() -> dict | None:
    """读取 .claude/sessions/*.json 获取当前活跃 session 信息"""
    if not CC_SESSIONS_DIR.exists():
        return None

    for sf in sorted(CC_SESSIONS_DIR.glob("*.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if data.get("status") in ("busy", "idle", "active"):
                return {
                    "session_id": data.get("sessionId", ""),
                    "pid": data.get("pid", 0),
                    "cwd": data.get("cwd", ""),
                    "status": data.get("status", ""),
                    "started_at": data.get("startedAt", 0),
                    "updated_at": data.get("updatedAt", 0),
                }
        except:
            pass
    return None


def get_token_usage(session_id: str) -> dict:
    """读 CC jsonl，从 usage 字段获取真实 token 用量

    Claude Code 在每次 assistant 消息的 message.usage 中记录 token 信息。
    我们累加 input_tokens 作为上下文消耗量的近似值。

    Returns: {
        total_input_tokens, total_output_tokens,
        last_input_tokens, last_output_tokens,
        line_count, usage_entry_count, file_size_bytes
    }
    """
    if not CC_PROJECT_DIR.exists():
        return {"total_input_tokens": 0, "error": "CC project dir not found"}

    # 找对应 session 的 jsonl
    jsonl_path = CC_PROJECT_DIR / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        # 可能是旧 session 被归档了，找最新的
        jsonl_files = sorted(CC_PROJECT_DIR.glob("*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not jsonl_files:
            return {"total_input_tokens": 0, "error": "no jsonl found"}
        jsonl_path = jsonl_files[0]

    total_input = 0
    total_output = 0
    last_input = 0
    last_output = 0
    line_count = 0
    usage_count = 0

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line_count += 1
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = d.get("message", {})
                if isinstance(msg, dict) and "usage" in msg:
                    u = msg["usage"]
                    inp = u.get("input_tokens", 0)
                    out = u.get("output_tokens", 0)
                    total_input += inp
                    total_output += out
                    last_input = inp
                    last_output = out
                    usage_count += 1
    except Exception as e:
        return {"total_input_tokens": 0, "error": str(e)}

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "last_input_tokens": last_input,
        "last_output_tokens": last_output,
        "line_count": line_count,
        "usage_entry_count": usage_count,
        "file_size_bytes": jsonl_path.stat().st_size if jsonl_path.exists() else 0,
        "file_name": jsonl_path.name,
    }


# ═══════════════════════════════════════════════
# 第2步: 提取最近N轮对话
# ═══════════════════════════════════════════════
def extract_recent_turns(session_id: str, n: int = HANDOVER_TURNS) -> list[dict]:
    """从 CC jsonl 提取最近 N 轮 user+assistant 对话

    Returns: [{role, content, timestamp, model?}]
    """
    jsonl_path = CC_PROJECT_DIR / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        # 找最新的 jsonl
        files = sorted(CC_PROJECT_DIR.glob("*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return []
        jsonl_path = files[0]

    turns = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = d.get("message", {})
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                # 提取文本内容
                content_text = ""
                content_list = msg.get("content", [])
                if isinstance(content_list, list):
                    parts = []
                    for item in content_list:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_use":
                                name = item.get("name", "tool")
                                inp = item.get("input", {})
                                # 工具调用摘要
                                cmd = str(inp.get("command", inp.get("description", "")))[:80]
                                parts.append(f"[调用工具: {name}] {cmd}")
                            elif item.get("type") == "tool_result":
                                parts.append("[工具结果]")
                    content_text = " ".join(parts)
                elif isinstance(content_list, str):
                    content_text = content_list

                if content_text.strip():
                    turn = {
                        "role": role,
                        "content": content_text[:500],  # 每轮最多500字
                        "timestamp": d.get("timestamp", ""),
                    }
                    if role == "assistant":
                        turn["model"] = msg.get("model", "")
                    turns.append(turn)
    except Exception as e:
        log(f"extract_turns error: {e}")
        return []

    return turns[-n:]  # 最近N轮


# ═══════════════════════════════════════════════
# 第3步: 写交接摘要 → memory_core pin桶 (覆写模式)
# ═══════════════════════════════════════════════
def write_handover_pin(turns: list[dict], token_info: dict) -> bool:
    """将交接摘要写入 memory_core 交接pin桶

    覆写模式: 使用 set_state 存储最新交接数据，
    同时写一个 protected pin 记忆条保存交接快照。
    """
    now = datetime.now()

    # 摘要内容
    summary_lines = [
        f"## 交接时间: {now.strftime('%Y-%m-%d %H:%M')}",
        f"## Token用量: {token_info.get('total_input_tokens', 0):,} input + {token_info.get('total_output_tokens', 0):,} output",
        f"## 最近{HANDOVER_TURNS}轮对话:",
    ]

    for turn in turns:
        role_label = "思思" if turn["role"] == "user" else "Dariel"
        content = turn["content"][:200]
        ts = turn.get("timestamp", "")[:16]
        summary_lines.append(f"- [{ts}] {role_label}: {content}")

    summary_text = "\n".join(summary_lines)

    # 1) 写入 memory_core pin (保护，永不衰减)
    try:
        from memory_core import write_memory, search_memories

        # 搜索旧交接 pin，降低其 importance 防止堆积
        old_pins = search_memories("交接 handover pin 切窗", limit=5)
        for old in old_pins:
            if "handover_pin" in str(old.get("tags", "")):
                try:
                    from memory_core import update_importance
                    update_importance(old["id"], 1)  # 旧的降到最低
                except:
                    pass

        # 写新交接 pin
        write_memory(
            content=summary_text,
            memory_type="pin",
            importance=5,          # 最高重要度
            tags="handover_pin,交接,切窗,会话摘要",
            source="session_watcher",
            protected=True,        # 永不衰减
            event_date=now.strftime("%Y-%m-%d"),
        )
        log("handover pin written to memory_core")
    except Exception as e:
        log(f"memory_core pin write error: {e}")
        return False

    # 2) 写入统一状态表 (快速访问)
    try:
        from memory_core import set_state
        set_state("handover", "summary", {
            "generated_at": now.isoformat(),
            "turn_count": len(turns),
            "token_input": token_info.get("total_input_tokens", 0),
            "token_output": token_info.get("total_output_tokens", 0),
            "first_turn_ts": turns[0]["timestamp"] if turns else "",
            "last_turn_ts": turns[-1]["timestamp"] if turns else "",
        })
        log("handover state updated")
    except Exception as e:
        log(f"set_state error: {e}")

    return True


# ═══════════════════════════════════════════════
# 第4步: 写 session_context.txt + handover flag
# ═══════════════════════════════════════════════
def write_context_file(turns: list[dict], token_info: dict, session_info: dict | None):
    """写 session_context.txt — wake.py 开窗时自动注入"""
    now = datetime.now()

    lines = [
        f"# Session Handover — {now.strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## 切窗原因",
        f"- Token用量: {token_info.get('total_input_tokens', 0):,} / 200,000 ({token_info.get('total_input_tokens', 0) / 2000:.1f}%)",
        f"- 触发时间: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## 核心状态",
    ]

    # 从 sensor/status 获取当前状态
    try:
        sensor_file = DIR / "sensor_state.json"
        if sensor_file.exists():
            sensor = json.loads(sensor_file.read_text(encoding="utf-8"))
            lines.append(f"- 能量: {sensor.get('energy', '?')}")
            lines.append(f"- 情绪: {sensor.get('mood', '?')}")
            lines.append(f"- 需要: {', '.join(sensor.get('needs', []))}")
    except:
        pass

    try:
        status_file = DIR / "status_board.json"
        if status_file.exists():
            status = json.loads(status_file.read_text(encoding="utf-8"))
            current = status.get("current", [])
            if current:
                lines.append(f"- 状态告示牌: {'; '.join(current[:3])}")
    except:
        pass

    # memo 摘要
    try:
        memo_file = DIR / "memo.md"
        if memo_file.exists():
            memo_text = memo_file.read_text(encoding="utf-8")
            memo_items = [l[2:] for l in memo_text.split("\n") if l.startswith("- ")]
            if memo_items:
                lines.append(f"- 备忘: {len(memo_items)}条")
                for m in memo_items[-5:]:
                    lines.append(f"  - {m[:100]}")
    except:
        pass

    lines.append(f"")
    lines.append(f"## 最近{HANDOVER_TURNS}轮对话")

    for turn in turns:
        role_label = "思思" if turn["role"] == "user" else "Dariel"
        ts = turn.get("timestamp", "")[:16]
        content = turn["content"][:300]
        lines.append(f"- [{ts}] **{role_label}**: {content}")

    lines.append(f"")
    lines.append(f"## 服务状态(切窗时)")
    lines.append(f"- session_watcher PID: {os.getpid()}")
    if session_info:
        lines.append(f"- CC session: {session_info.get('session_id', '?')}")
        lines.append(f"- CC status: {session_info.get('status', '?')}")

    lines.append(f"")
    lines.append(f"## 思思偏好(持久)")
    lines.append(f"- 喜欢听英文语音，不加情绪标签")
    lines.append(f"- 不让用emoji")
    lines.append(f"- 不用催她睡觉，她想聊就陪")
    lines.append(f"- send_voice必须短句分行用\\\\n")
    lines.append(f"- 胃不好是严重问题(6.13救护车送医)")

    context_text = "\n".join(lines)

    try:
        CONTEXT_FILE.write_text(context_text, encoding="utf-8")
        log(f"session_context.txt written ({len(context_text)} chars)")
    except Exception as e:
        log(f"context file write error: {e}")


def write_handover_flag(token_info: dict) -> bool:
    """写 flag 文件，通知需要切窗。

    session_handover.flag 包含:
    - trigger_reason: 触发原因
    - token_usage: token用量
    - handover_at: 交接时间
    - needs_restart: 是否需要重启CC
    """
    flag_data = {
        "trigger_reason": "token_warn" if token_info.get("total_input_tokens", 0) < TOKEN_CRITICAL else "token_critical",
        "token_usage": token_info,
        "handover_at": datetime.now().isoformat(),
        "needs_restart": True,
        "next_steps": [
            "1. 确认 session_context.txt 已更新",
            "2. 发 exit 或关闭当前 CC 窗口",
            "3. 手动重建新 CC session (Termius 或其他终端)",
            "4. 新 session 启动时 wake.py 自动注入 context",
        ],
    }

    try:
        FLAG_FILE.write_text(json.dumps(flag_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log("handover flag written")
        return True
    except Exception as e:
        log(f"flag write error: {e}")
        return False


# ═══════════════════════════════════════════════
# 第5步: 归档旧 jsonl (可选)
# ═══════════════════════════════════════════════
def archive_old_session(session_id: str):
    """归档旧 session jsonl → .archived 后缀"""
    jsonl_path = CC_PROJECT_DIR / f"{session_id}.jsonl"
    if jsonl_path.exists():
        archive_path = jsonl_path.with_suffix(".jsonl.archived")
        try:
            jsonl_path.rename(archive_path)
            log(f"archived: {jsonl_path.name} → {archive_path.name}")
            return True
        except Exception as e:
            log(f"archive error: {e}")
    return False


# ═══════════════════════════════════════════════
# 主检查逻辑
# ═══════════════════════════════════════════════
# 跟踪已处理的 session，避免重复触发
_last_handover_session = None
_last_handover_time = 0


def check_and_handover():
    """每分钟执行一次的主检查"""
    global _last_handover_session, _last_handover_time

    # 如果 flag 文件存在且还是同一个 session，跳过
    if FLAG_FILE.exists():
        flag_age = time.time() - FLAG_FILE.stat().st_mtime
        if flag_age < MAX_CONTEXT_AGE:
            return  # flag 还有效，不用重复写
        else:
            log("flag expired, will re-check")
            try:
                FLAG_FILE.unlink()
            except:
                pass

    # 获取活跃 session
    session = get_active_session()
    if not session:
        return  # 没有活跃CC会话，不检查

    session_id = session["session_id"]

    # 获取真实 token 用量
    token_info = get_token_usage(session_id)
    total_tokens = token_info.get("total_input_tokens", 0)

    if "error" in token_info:
        log(f"token check error: {token_info['error']}")
        return

    # 判断是否需要触发
    needs_handover = False
    reason = ""

    if total_tokens > TOKEN_CRITICAL:
        needs_handover = True
        reason = f"TOKEN_CRITICAL: {total_tokens:,} > {TOKEN_CRITICAL:,}"
    elif total_tokens > TOKEN_WARN:
        needs_handover = True
        reason = f"TOKEN_WARN: {total_tokens:,} > {TOKEN_WARN:,}"

    # 检查无活动超时 (从 session updated_at 判断)
    if not needs_handover and session.get("updated_at"):
        idle_sec = (time.time() * 1000 - session["updated_at"]) / 1000
        if idle_sec > IDLE_TIMEOUT:
            needs_handover = True
            reason = f"IDLE_TIMEOUT: {idle_sec:.0f}s > {IDLE_TIMEOUT}s"

    if not needs_handover:
        # 静默: 每分钟输出一次状态(只在token接近时)
        if total_tokens > TOKEN_WARN * 0.8:
            log(f"approaching: {total_tokens:,}/{TOKEN_WARN:,} tokens ({total_tokens / 2000:.1f}%)")
        return

    # 避免同一 session 重复触发
    if session_id == _last_handover_session:
        age = time.time() - _last_handover_time
        if age < MAX_CONTEXT_AGE:
            return  # 已经触发过了，还没过期

    # ═══════════════════════════════════
    # 触发切窗交接流程!
    # ═══════════════════════════════════
    log(f"⚠️ TRIGGER: {reason}")
    log(f"   Session: {session_id}")
    log(f"   Tokens: {total_tokens:,} input / {token_info.get('total_output_tokens', 0):,} output")
    log(f"   File: {token_info.get('file_name', '?')} ({token_info.get('file_size_bytes', 0):,} bytes)")

    # 步骤1: 提取最近20轮对话
    turns = extract_recent_turns(session_id)
    log(f"   Step 1: extracted {len(turns)} turns from jsonl")

    # 步骤2: 写交接摘要 → memory_core pin桶
    pin_ok = write_handover_pin(turns, token_info)
    log(f"   Step 2: pin write {'OK' if pin_ok else 'FAIL'}")

    # 步骤3: 写 session_context.txt
    write_context_file(turns, token_info, session)
    log(f"   Step 3: session_context.txt written")

    # 步骤4: 写 flag 通知切窗
    write_handover_flag(token_info)
    log(f"   Step 4: handover flag written")

    # 步骤5: 写 handover.json (兼容旧版)
    handover_data = {
        "generated_at": datetime.now().isoformat(),
        "session_id": session_id,
        "token_info": token_info,
        "turn_count": len(turns),
        "trigger_reason": reason,
    }
    try:
        HANDOVER_FILE.write_text(json.dumps(handover_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"   Step 5: handover.json written")
    except Exception as e:
        log(f"   Step 5 error: {e}")

    _last_handover_session = session_id
    _last_handover_time = time.time()

    log(f"✅ 交接完成! 等待手动切窗。")


# ═══════════════════════════════════════════════
# 状态报告 (给外部查询)
# ═══════════════════════════════════════════════
def status_report() -> dict:
    """生成当前状态报告"""
    session = get_active_session()
    if not session:
        return {"status": "no_active_cc_session"}

    token_info = get_token_usage(session["session_id"])
    total = token_info.get("total_input_tokens", 0)
    pct = total / 2000  # 百分比

    return {
        "status": "watching",
        "session_id": session["session_id"],
        "cc_status": session.get("status", "?"),
        "total_input_tokens": total,
        "total_output_tokens": token_info.get("total_output_tokens", 0),
        "usage_pct": round(pct, 1),
        "threshold_warn": TOKEN_WARN,
        "threshold_critical": TOKEN_CRITICAL,
        "handover_flag_exists": FLAG_FILE.exists(),
        "context_file_exists": CONTEXT_FILE.exists(),
    }


# ═══════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════
def main():
    import os as _os
    pid = _os.getpid()
    PID_FILE.write_text(str(pid))
    log(f"=== session_watcher v2.0 start ===")
    log(f"PID={pid} interval={CHECK_INTERVAL}s")
    log(f"token_warn={TOKEN_WARN:,} token_critical={TOKEN_CRITICAL:,}")
    log(f"CC dir: {CC_PROJECT_DIR}")

    # 第一轮立即检查
    try:
        check_and_handover()
    except Exception as e:
        log(f"initial check error: {e}")

    # 循环
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            check_and_handover()
        except KeyboardInterrupt:
            log("stopped by user")
            break
        except Exception as e:
            log(f"loop error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    # 支持 --status 查询
    if "--status" in sys.argv:
        print(json.dumps(status_report(), ensure_ascii=False, indent=2))
    else:
        main()
