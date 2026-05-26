"""操作自动记录 — 类似 claude-mem，捕获关键操作压缩成日记
数据单向流动: hook捕获 → session_log → 压缩 → memory_core
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).parent
LOG_FILE = DIR / "session_log.json"


def now_iso():
    return datetime.now().isoformat()


def log_operation(op_type: str, path: str = "", summary: str = "", detail: str = ""):
    """记录一次操作到会话日志"""
    entries = _read_log()
    entries.append({
        "type": op_type,
        "path": path,
        "summary": summary,
        "detail": detail[:200],
        "time": now_iso(),
    })
    # 保留最近200条
    if len(entries) > 200:
        entries = entries[-200:]
    LOG_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_log() -> list:
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_recent_ops(minutes: int = 60) -> list:
    """获取最近N分钟的操作"""
    cutoff = datetime.now().isoformat()[:16]  # rough cutoff
    entries = _read_log()
    return [e for e in entries if e["time"][:16] >= cutoff]


def compress_to_diary(label: str = "") -> str:
    """将最近的会话操作压缩成日记条目，写入 memory_core"""
    entries = _read_log()
    if not entries:
        return "no entries to compress"

    # 清除已处理标记
    unprocessed = [e for e in entries if not e.get("compressed", False)]
    if not unprocessed:
        return "all entries already compressed"

    # 按类型统计
    from collections import Counter
    type_counts = Counter(e["type"] for e in unprocessed)

    # 提取文件变更
    file_ops = [e for e in unprocessed if e["type"] in ("file_write", "file_edit")]
    file_paths = list(set(e["path"] for e in file_ops if e["path"]))

    # 提取重要命令
    commands = [e for e in unprocessed if e["type"] == "command"]
    cmd_highlights = [e["summary"] for e in commands if e["summary"]]

    # 构建日记
    now = datetime.now()
    diary_parts = [f"{now.strftime('%m月%d日 %H:%M')} 会话操作摘要"]

    if label:
        diary_parts[0] += f" — {label}"

    if file_paths:
        diary_parts.append(f"修改了 {len(file_ops)} 个文件: {', '.join(file_paths[:5])}")
    if cmd_highlights:
        diary_parts.append(f"执行了 {len(commands)} 条命令: {'; '.join(cmd_highlights[-3:])}")
    if type_counts:
        diary_parts.append(f"操作统计: {dict(type_counts)}")

    diary_content = "。\n".join(diary_parts) + "。"

    # 写入 memory_core
    try:
        from memory_core import write_memory
        mem = write_memory(
            content=diary_content,
            memory_type="diary",
            importance=3,
            tags="自动日记,会话摘要",
            source="obsidian_compress",
        )
        diary_id = mem["id"]
    except Exception as e:
        return f"compress failed: {e}"

    # 标记已处理
    for e in entries:
        if not e.get("compressed", False):
            e["compressed"] = True
    LOG_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    return f"compressed {len(unprocessed)} ops → diary #{diary_id}"


def stats():
    """查看日志统计"""
    entries = _read_log()
    from collections import Counter
    types = Counter(e["type"] for e in entries)
    compressed = sum(1 for e in entries if e.get("compressed", False))
    return {
        "total": len(entries),
        "uncompressed": len(entries) - compressed,
        "by_type": dict(types),
        "timespan": f"{entries[0]['time'][:19]} → {entries[-1]['time'][:19]}" if entries else "empty",
    }


if __name__ == "__main__":
    if "--compress" in sys.argv:
        label = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--compress" and i + 1 < len(sys.argv):
                label = sys.argv[i + 1]
                break
        result = compress_to_diary(label)
        print(result)
    elif "--stats" in sys.argv:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif "--log" in sys.argv:
        if len(sys.argv) < 4:
            print("用法: python obsidian.py --log <type> <summary> [path] [detail]")
        else:
            log_operation(
                op_type=sys.argv[2],
                summary=sys.argv[3],
                path=sys.argv[4] if len(sys.argv) > 4 else "",
                detail=sys.argv[5] if len(sys.argv) > 5 else "",
            )
            print("logged")
    else:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
