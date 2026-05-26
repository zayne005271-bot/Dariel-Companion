"""PostToolUse hook — 自动记录文件操作到 obsidian 会话日志"""
import json
import sys
from pathlib import Path

# Claude Code passes tool input file as first arg
tool_input_file = sys.argv[1] if len(sys.argv) > 1 else ""
tool_name = sys.argv[2] if len(sys.argv) > 2 else ""

if not tool_input_file or not Path(tool_input_file).exists():
    sys.exit(0)

try:
    data = json.loads(Path(tool_input_file).read_text(encoding="utf-8"))
except (json.JSONDecodeError, FileNotFoundError):
    sys.exit(0)

file_path = data.get("file_path", "")
if not file_path:
    sys.exit(0)

# Log to obsidian
LOG_FILE = Path("dariel/session_log.json")
entries = []
if LOG_FILE.exists():
    try:
        entries = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        entries = []

fname = Path(file_path).name
summary = f"{tool_name}: {fname}"

entries.append({
    "type": "file_write" if tool_name == "Write" else "file_edit",
    "path": file_path,
    "summary": summary,
    "time": __import__('datetime').datetime.now().isoformat(),
})

if len(entries) > 200:
    entries = entries[-200:]

LOG_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
