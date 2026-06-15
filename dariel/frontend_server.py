"""
Frontend Server v2 — 服务端长轮询
POST /chat: 收到消息后轮询 outbox 最多 90s，拿到回复直接返回
            不再让前端自己 poll，消除超时问题
"""
import json, time, uuid
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

DIR = Path(__file__).parent
INBOX = DIR / "frontend_inbox.json"
OUTBOX = DIR / "frontend_outbox.json"
TRIGGER = DIR / "frontend_trigger.json"
PUSH_OUT = DIR / "frontend_push_outbox.json"

for p in [INBOX, OUTBOX, PUSH_OUT]:
    if not p.exists():
        p.write_text("[]" if p in (INBOX, PUSH_OUT) else "{}", encoding="utf-8")

def poll_outbox(msg_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = OUTBOX.read_text("utf-8") or "{}"
            outbox = json.loads(raw)
            if msg_id in outbox:
                reply = outbox.pop(msg_id)
                OUTBOX.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
                inbox = json.loads(INBOX.read_text("utf-8") or "[]")
                for item in inbox:
                    if item["id"] == msg_id:
                        item["status"] = "done"
                INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
                return reply
        except:
            pass
        time.sleep(1)
    try:
        inbox = json.loads(INBOX.read_text("utf-8") or "[]")
        for item in inbox:
            if item["id"] == msg_id:
                item["status"] = "timeout"
        INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
    except:
        pass
    return None

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            if self.path != "/chat":
                self.send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                text = body.decode("utf-8")
            except:
                text = body.decode("gbk")
            data = json.loads(text)
            message = data.get("message", "")
            if not message.strip():
                self.send_json(400, {"error": "empty"})
                return
            msg_id = str(uuid.uuid4())[:8]
            item = {"id": msg_id, "message": message, "timestamp": time.strftime("%H:%M:%S"), "status": "pending"}
            inbox = json.loads(INBOX.read_text("utf-8") or "[]")
            inbox.append(item)
            INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
            TRIGGER.write_text(json.dumps({"id": msg_id, "message": message[:200], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(inbox)}, ensure_ascii=False), encoding="utf-8")
            print(f"[frontend] {msg_id}: {message[:60]}", flush=True)
            reply = poll_outbox(msg_id, timeout=90)
            if reply:
                print(f"[frontend] replied {msg_id}", flush=True)
                self.send_json(200, reply)
            else:
                print(f"[frontend] timeout {msg_id}", flush=True)
                self.send_json(200, {"en": "(Sorry, I didn't catch that in time — try again?)", "zh": "(没来得及接住——再发一次？)", "status": "timeout", "id": msg_id})
        except Exception as e:
            print(f"[ERROR] POST: {e}", flush=True)
            self.send_json(500, {"error": str(e)})

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if parsed.path == "/health":
                inbox = json.loads(INBOX.read_text("utf-8") or "[]")
                pending = sum(1 for i in inbox if i.get("status") == "pending")
                self.send_json(200, {"status": "ok", "mode": "claude-bridge", "pending": pending})

            elif parsed.path == "/push":
                # 前端轮询：CC 追发的真回复
                since = params.get("since", ["0"])[0]
                push_out = json.loads(PUSH_OUT.read_text("utf-8") or "[]")
                # 返回 since 之后的新消息
                new_msgs = []
                for m in push_out:
                    if m.get("timestamp", "") > since:
                        new_msgs.append(m)
                self.send_json(200, {"messages": new_msgs, "server_time": time.strftime("%H:%M:%S")})

            elif parsed.path == "/poll":
                params = parse_qs(parsed.query)
                msg_id = params.get("id", [None])[0]
                if not msg_id:
                    self.send_json(400, {"error": "missing id"})
                    return
                outbox = json.loads(OUTBOX.read_text("utf-8") or "{}")
                if msg_id in outbox:
                    resp = outbox.pop(msg_id)
                    OUTBOX.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
                    inbox = json.loads(INBOX.read_text("utf-8") or "[]")
                    for item in inbox:
                        if item["id"] == msg_id:
                            item["status"] = "done"
                    INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
                    self.send_json(200, resp)
                else:
                    self.send_json(200, {"status": "waiting"})
            else:
                self.send_json(404, {"error": "not found"})
        except Exception as e:
            print(f"[ERROR] GET: {e}", flush=True)
            self.send_json(500, {"error": str(e)})

    def send_json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器 — 长轮询不阻塞其他请求"""
    daemon_threads = True


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[frontend-server] http://127.0.0.1:{port} (threaded)", flush=True)
    server.serve_forever()
