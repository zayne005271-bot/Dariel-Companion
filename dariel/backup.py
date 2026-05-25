"""思思的备份脚本 — 把Dariel相关所有文件打包到移动硬盘"""

import shutil
import os
from pathlib import Path
from datetime import datetime

DESKTOP = Path(os.environ["USERPROFILE"]) / "Desktop"
DARIEL = DESKTOP / "dariel"
CLAUDE_MEMORY = Path(os.environ["USERPROFILE"]) / ".claude" / "projects" / "C--Users-31654-Desktop"

# 要备份的文件/目录清单
BACKUP_LIST = [
    # Dariel 项目核心
    (DARIEL, "dariel"),
    # Claude Code 记忆系统
    (CLAUDE_MEMORY / "memory", "memory"),
    # 项目配置
    (DESKTOP / "CLAUDE.md", "CLAUDE.md"),
    (DESKTOP / ".mcp.json", ".mcp.json"),
    (DESKTOP / "skills-lock.json", "skills-lock.json"),
    # 对话语料
    (DESKTOP / "对话语料库_v1.md", "对话语料库_v1.md"),
]

# 不需要备份的文件 (临时文件、token很大的日志等)
SKIP_PATTERNS = [
    "*.log",
    "emotion_state.json",
    "proactive_state.json",
    "relationship_state.json",
    "sensor_state.json",
    "corridor.json",
    "xhs_content.json",
    "xhs_auth.json",
    "__pycache__",
    "*.pyc",
    ".claude",
]


def should_skip(path: Path) -> bool:
    for pattern in SKIP_PATTERNS:
        if pattern.startswith("*"):
            if path.match(pattern):
                return True
        elif pattern in str(path):
            return True
    return False


def run(target_dir: str):
    target = Path(target_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_root = target / f"dariel_backup_{timestamp}"

    print(f"备份到: {backup_root}")
    print("-" * 50)

    for src, name in BACKUP_LIST:
        if not src.exists():
            print(f"  SKIP (不存在): {name}")
            continue

        dst = backup_root / name
        try:
            if src.is_dir():
                shutil.copytree(
                    src, dst,
                    ignore=shutil.ignore_patterns(*[p.replace("*", "") if p.startswith("*") and not p.startswith("**") else p for p in SKIP_PATTERNS if not p.startswith("__")]),
                    dirs_exist_ok=True,
                )
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  FAIL: {name} — {e}")

    print("-" * 50)
    print("备份完成！")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python backup.py <目标路径>")
        print("例如: python backup.py D:\\backup")
        print("      python backup.py E:\\")
    else:
        run(sys.argv[1])
