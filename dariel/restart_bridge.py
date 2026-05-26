"""安全重启 qq_bridge — 只杀桥接进程，不动其他 Python 进程"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PID_FILE = Path(__file__).parent / "tts" / "qq_bridge.pid"
LOG_FILE = Path(__file__).parent / "tts" / "qq_bridge.log"


def get_bridge_pid():
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, FileNotFoundError):
        return None


def kill_bridge():
    pid = get_bridge_pid()
    if pid is None:
        print("[restart] no bridge PID found, nothing to kill")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[restart] killed bridge PID {pid}")
        time.sleep(1)
    except OSError as e:
        print(f"[restart] PID {pid} already dead: {e}")

    PID_FILE.unlink(missing_ok=True)


def start_bridge():
    bridge_script = Path(__file__).parent / "tts" / "qq_bridge.py"
    subprocess.Popen(
        ["D:/Python/python.exe", "-u", str(bridge_script)],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)
    pid = get_bridge_pid()
    if pid:
        print(f"[restart] bridge started, PID {pid}")
    else:
        print("[restart] bridge start failed? no PID file")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "restart"

    if action == "kill":
        kill_bridge()
    elif action == "start":
        start_bridge()
    else:  # restart
        kill_bridge()
        start_bridge()

    # show running pids for verification
    pid = get_bridge_pid()
    if pid:
        print(f"[restart] bridge PID: {pid}")
