"""Dariel 服务健康检查 — 排查所有组件状态，可选自动修复"""
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"

REQUIRED_FILES = [
    DIR / "memory_core.py",
    DIR / "send_voice.py",
    DIR / "keepalive.py",
    DIR / "corridor.py",
    DIR / "dream_engine.py",
    DIR / "emotion_engine.py",
    DIR / "impulse_engine.py",
    DIR / "xhs_browser.py",
    DIR / "unified_mcp.py",
    BRIDGE_DIR / "qq_bridge.py",
    BRIDGE_DIR / "mcp_server.py",
]


def check(autofix: bool = False) -> dict:
    results = {}
    all_ok = True

    # 1. NapCat container
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=napcat", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        napcat_status = r.stdout.strip()
        if "Up" in napcat_status:
            results["napcat"] = {"ok": True, "status": napcat_status}
        else:
            results["napcat"] = {"ok": False, "status": napcat_status or "not running"}
            all_ok = False
    except FileNotFoundError:
        results["napcat"] = {"ok": False, "status": "docker not found"}
        all_ok = False

    # 2. qq_bridge process
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process python -ErrorAction SilentlyContinue | "
             "Where-Object {$_.StartTime -ne $null}).Count"],
            capture_output=True, text=True, timeout=10
        )
        python_count = int(r.stdout.strip() or 0)
        inbox_age = _file_age_minutes(INBOX_FILE)
        outbox_age = _file_age_minutes(OUTBOX_FILE)

        # bridge is healthy if inbox was updated recently (<15min) and outbox readable
        bridge_ok = inbox_age is not None and inbox_age < 15

        results["qq_bridge"] = {
            "ok": bridge_ok,
            "python_processes": python_count,
            "inbox_age_min": inbox_age,
            "outbox_age_min": outbox_age,
        }
        if not bridge_ok:
            all_ok = False
    except Exception as e:
        results["qq_bridge"] = {"ok": False, "error": str(e)}
        all_ok = False

    # 3. inbox/outbox readability
    for name, path in [("inbox", INBOX_FILE), ("outbox", OUTBOX_FILE)]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results[name] = {"ok": True, "entries": len(data)}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
            all_ok = False

    # 4. Required files
    missing_files = []
    for f in REQUIRED_FILES:
        if not f.exists():
            missing_files.append(str(f.relative_to(DIR)))
    results["required_files"] = {"ok": len(missing_files) == 0, "missing": missing_files}
    if missing_files:
        all_ok = False

    # 5. MCP — check if unified_mcp can be imported
    try:
        from mcp.server import Server
        results["mcp"] = {"ok": True, "module": "mcp.server available"}
    except ImportError as e:
        results["mcp"] = {"ok": False, "error": str(e)}
        all_ok = False

    # 6. state files
    state_files = [
        "sensor_state.json", "impulse_state.json", "keepalive_state.json",
        "proactive_state.json", "relationship_state.json", "dream_events.json",
        "status_board.json", "corridor.json",
    ]
    state_status = {}
    for sf in state_files:
        p = DIR / sf
        state_status[sf] = p.exists()
    results["state_files"] = state_status

    results["overall"] = "healthy" if all_ok else "degraded"
    results["checked_at"] = datetime.now().isoformat()

    # Auto-fix if requested
    if autofix and not all_ok:
        fixes = _autofix(results)
        results["autofix"] = fixes

    return results


def _file_age_minutes(path: Path) -> float | None:
    if not path.exists():
        return None
    return round((time.time() - path.stat().st_mtime) / 60, 1)


def _autofix(results: dict) -> dict:
    fixes = []

    # Restart qq_bridge if needed
    if not results.get("qq_bridge", {}).get("ok"):
        try:
            subprocess.Popen(
                ["D:/Python/python.exe", "-u", str(BRIDGE_DIR / "qq_bridge.py")],
                stdout=open("/tmp/qq_bridge.log", "a"),
                stderr=subprocess.STDOUT,
            )
            fixes.append("qq_bridge restarted")
        except Exception as e:
            fixes.append(f"qq_bridge restart failed: {e}")

    # Start NapCat if stopped
    napcat = results.get("napcat", {})
    if not napcat.get("ok"):
        try:
            subprocess.run(["docker", "start", "napcat"], capture_output=True, timeout=30)
            fixes.append("napcat started")
        except Exception as e:
            fixes.append(f"napcat start failed: {e}")

    return fixes


def print_report(results: dict):
    """打印健康报告"""
    print("=" * 45)
    print("  Dariel 服务健康检查")
    print("=" * 45)
    print(f"  时间: {results['checked_at'][:19]}")
    print(f"  整体: {results['overall'].upper()}")
    print()

    for name, info in results.items():
        if name in ("overall", "checked_at", "autofix", "state_files"):
            continue
        icon = "OK" if info.get("ok") else "!!"
        print(f"  [{icon}] {name}")
        for k, v in info.items():
            if k != "ok":
                print(f"       {k}: {v}")

    # state files
    sf = results.get("state_files", {})
    missing_states = [k for k, v in sf.items() if not v]
    if missing_states:
        print(f"  [--] state_files: {len(missing_states)} missing")
        for m in missing_states:
            print(f"       - {m}")
    else:
        print(f"  [OK] state_files: all present")

    if "autofix" in results:
        print(f"\n  自动修复: {results['autofix']}")

    print("=" * 45)


def run_as_daemon(interval_min: int = 30):
    """作为后台守护运行，每 N 分钟检查一次并自动修复"""
    import time
    print(f"[health] daemon started, checking every {interval_min}min")
    while True:
        results = check(autofix=True)
        if results["overall"] != "healthy":
            print(f"[health] {results['overall']} at {results['checked_at'][:19]}")
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    autofix = "--fix" in sys.argv or "-f" in sys.argv
    daemon = "--daemon" in sys.argv or "-d" in sys.argv

    if daemon:
        interval = 30
        for i, arg in enumerate(sys.argv):
            if arg in ("--daemon", "-d") and i + 1 < len(sys.argv):
                try:
                    interval = int(sys.argv[i + 1])
                except ValueError:
                    pass
        run_as_daemon(interval)
    else:
        results = check(autofix=autofix)
        print_report(results)
