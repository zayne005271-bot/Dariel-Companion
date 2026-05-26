"""Dream Events 感知层 — 接收iOS快捷指令上报，让AI知道她在干嘛

iOS快捷指令配置(每个App建一条):
1. 自动化 → 触发: 打开App → 选要监控的App
2. 动作: 获取URL内容
   URL: http://你的服务器IP:8765/report?type=app.小红书&value=在刷小红书
   方法: GET
3. 关闭「运行前询问」

常用App: 小红书、微信、QQ、B站、抖音、淘宝、外卖App

事件去重: 同type 5分钟内只存一条
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

DIR = Path(__file__).parent
EVENTS_FILE = DIR / "dream_events.json"
PORT = 8765

# 去重窗口: 同type多少分钟内不重复记录
DEDUP_WINDOW_MINUTES = 5
# 事件保留时间: 超过多少小时的清理
MAX_AGE_HOURS = 12


def load_events():
    try:
        return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_events(events):
    EVENTS_FILE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def add_event(event_type: str, value: str) -> bool:
    """添加事件，返回True如果是新事件(未去重)"""
    events = load_events()
    now = datetime.now()

    # 去重: 同type在DEDUP_WINDOW内已存在 → 跳过
    cutoff = now - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    for e in events:
        if e.get("type") == event_type:
            try:
                et = datetime.fromisoformat(e["created_at"])
                if et > cutoff:
                    return False  # 重复，跳过
            except (ValueError, KeyError):
                pass

    events.append({
        "type": event_type,
        "value": value,
        "created_at": now.isoformat(),
    })

    # 清理过期事件
    age_cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    events = [e for e in events
              if datetime.fromisoformat(e["created_at"]) > age_cutoff]
    events = events[-200:]  # 最多200条

    save_events(events)
    return True


def get_recent_events(hours: int = 6) -> list:
    """获取最近N小时的事件，格式化后注入prompt"""
    events = load_events()
    cutoff = datetime.now() - timedelta(hours=hours)

    recent = []
    for e in events:
        try:
            et = datetime.fromisoformat(e["created_at"])
            if et > cutoff:
                recent.append(e)
        except (ValueError, KeyError):
            pass

    return recent


def format_activity(events: list) -> str:
    """格式化事件为可读的活动摘要"""
    if not events:
        return "最近没有活动记录。"

    lines = ["她最近的动向:"]
    for e in events[-10:]:
        try:
            t = datetime.fromisoformat(e["created_at"]).strftime("%H:%M")
            app = e.get("type", "").replace("app.", "")
            value = e.get("value", "")
            lines.append(f"  {t} {app}: {value}")
        except (ValueError, KeyError):
            pass

    return "\n".join(lines)


class ReportHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器 — GET /report?type=app.xxx&value=xxx"""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/report":
            params = parse_qs(parsed.query)
            event_type = params.get("type", [""])[0]
            value = params.get("value", [""])[0]

            if event_type:
                is_new = add_event(event_type, value)
                status = "new" if is_new else "dup"
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"ok ({status})\n".encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing type\n")
        elif parsed.path == "/events":
            # 查看最近事件(调试用)
            events = get_recent_events(6)
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(events, ensure_ascii=False, indent=2).encode())
        elif parsed.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"dream_events OK\n")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found\n")

    def log_message(self, format, *args):
        """静默日志"""
        pass  # 不打印到stdout


def start_server():
    """启动HTTP服务器(后台线程)"""
    server = HTTPServer(("0.0.0.0", PORT), ReportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[dream_events] 感知层已启动 — 端口 {PORT}")
    return server


if __name__ == "__main__":
    print(f"[dream_events] 启动感知层服务器...")
    print(f"[dream_events] iOS快捷指令上报地址: http://你的IP:{PORT}/report")
    server = start_server()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        server.shutdown()
        print("[dream_events] 已关闭")
