"""守望闹钟 — CC background task，每10秒查 trigger，发现即退出通知CC。
用法: python trigger_alarm.py  (CC run_in_background)
"""
import time
from pathlib import Path

TRIGGER = Path(__file__).parent / "qq_alarm_trigger.json"
print("[alarm] 盯 trigger 中...")
while True:
    if TRIGGER.exists():
        print(f"[alarm] trigger 发现! 通知CC...")
        break
    time.sleep(10)
