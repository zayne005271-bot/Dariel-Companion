# QQ ↔ Claude Code 桥接教程

让 Claude Code 通过 QQ 与你聊天。支持私聊、自动回复、TTS 语音。

## 架构概览

```
QQ 消息 → NapCat (Docker) → WebSocket → qq_bridge.py → inbox.json
                                                              ↓
                                                       Claude Code (MCP)
                                                              ↓
QQ 消息 ← NapCat (Docker) ← WebSocket ← qq_bridge.py ← outbox.json
```

## 前置要求

- Docker Desktop
- Python 3.10+
- Claude Code (claude.ai/code)
- QQ 账号

## Step 1: 部署 NapCat + AstrBot

创建 `docker-compose.yml`：

```yaml
services:
  napcat:
    image: m.daocloud.io/docker.io/mlikiowa/napcat-docker:latest
    container_name: napcat
    environment:
      - NAPCAT_UID=0
      - NAPCAT_GID=0
    ports:
      - "6099:6099"
      - "6098:6098"
    volumes:
      - ./napcat-data/config:/app/napcat/config
      - ./napcat-data/qq:/app/.config/QQ
    restart: always

  astrbot:
    image: m.daocloud.io/docker.io/soulter/astrbot:latest
    container_name: astrbot
    ports:
      - "6185:6185"
    volumes:
      - ./astrbot-data:/AstrBot/data
    restart: always
```

启动：

```bash
docker compose up -d
```

NapCat 启动后会显示二维码，扫码登录 QQ。

## Step 2: 创建桥接脚本

`qq_bridge.py` — WebSocket 桥接，负责收发消息：

```python
"""QQ <-> Claude Code 桥接"""

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
import websockets

BRIDGE_DIR = Path(__file__).parent
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
NAP_WS = "ws://localhost:6098"
NAP_TOKEN = "claude-bridge-token"

def log(msg: str):
    print(msg, flush=True)

async def send_private_msg(ws, user_id: str, message: str):
    payload = {
        "action": "send_private_msg",
        "params": {"user_id": int(user_id), "message": message},
    }
    await ws.send(json.dumps(payload, ensure_ascii=False))

async def flush_outbox(ws):
    """发送待发消息"""
    outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
    changed = False
    for msg in outbox:
        if msg.get("sent"):
            continue
        await send_private_msg(ws, msg["user_id"], msg["message"])
        msg["sent"] = True
        msg["sent_at"] = datetime.now().isoformat()
        changed = True
    if changed:
        OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")

async def run():
    # 初始化文件
    if not INBOX_FILE.exists():
        INBOX_FILE.write_text("[]", encoding="utf-8")
    if not OUTBOX_FILE.exists():
        OUTBOX_FILE.write_text("[]", encoding="utf-8")

    log("[bridge] started")

    while True:
        try:
            async with websockets.connect(
                NAP_WS,
                additional_headers={"Authorization": f"Bearer {NAP_TOKEN}"},
                ping_interval=30,
            ) as ws:
                log("[bridge] connected")
                await flush_outbox(ws)

                async for raw_msg in ws:
                    data = json.loads(raw_msg)
                    if data.get("post_type") == "message" and data.get("message_type") == "private":
                        sender = data.get("sender", {})
                        user_id = str(sender.get("user_id", ""))
                        nickname = sender.get("nickname", "")
                        message = data.get("raw_message", "")

                        log(f"[recv] {nickname}({user_id}): {message}")

                        inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
                        inbox.append({
                            "id": str(int(time.time() * 1000)),
                            "user_id": user_id,
                            "nickname": nickname,
                            "message": message,
                            "message_id": data.get("message_id", 0),
                            "timestamp": datetime.now().isoformat(),
                            "replied": False,
                        })
                        inbox = inbox[-100:]  # 保留最近 100 条
                        INBOX_FILE.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            log(f"[bridge] disconnected: {e}, retrying in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
```

运行桥接：

```bash
python qq_bridge.py
```

## Step 3: 配置 Claude Code MCP

在项目根目录创建 `.mcp.json`：

```json
{
  "mcpServers": {
    "qq-bridge": {
      "command": "python",
      "args": ["-u", "mcp_server.py"],
      "cwd": "."
    }
  }
}
```

`mcp_server.py` — MCP 服务，暴露 check_qq_messages 和 send_qq_reply 两个工具：

```python
"""Dariel QQ MCP Server"""

import json
import time
from pathlib import Path
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

BRIDGE_DIR = Path(__file__).parent
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"

server = Server("qq-bridge")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_qq_messages",
            description="Check for new QQ messages.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="send_qq_reply",
            description="Send a reply to QQ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["user_id", "message"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "check_qq_messages":
        inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
        new_msgs = [m for m in inbox if not m.get("replied", False)]
        if not new_msgs:
            return [TextContent(type="text", text="No new messages.")]
        lines = []
        for m in new_msgs:
            lines.append(f"[{m['id']}] {m['nickname']}({m['user_id']}): {m['message']}")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "send_qq_reply":
        user_id = arguments["user_id"]
        message = arguments["message"]
        outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
        outbox.append({
            "id": f"reply_{int(time.time() * 1000)}",
            "user_id": user_id,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "sent": False,
        })
        OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
        # 标记已回复
        inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
        for m in inbox:
            if m["user_id"] == user_id:
                m["replied"] = True
        INBOX_FILE.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
        return [TextContent(type="text", text=f"Reply sent to QQ {user_id}.")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Step 4: 设置 Claude Code 自动回复

在 Claude Code 中设置定时任务，每 5 分钟检查一次 QQ 消息：

```
/cron "*/5 * * * *" "自动检查 QQ 消息并回复"
```

或使用 Claude Code 的 `CLAUDE.md` 指令说明自动回复规则。

## 安全与隐私

- 设置 `.claude/settings.json` 权限白名单
- 限制 Bash 命令执行范围
- 不要在代码中硬编码 API 密钥
- 定期检查 `credentials.json` 不在版本控制中

### Qzone 说说隐私说明

发说说功能通过 NapCat `get_cookies` 获取 QQ 登录态，有以下隐私保障：

- **不落盘** — cookie 只在内存中使用，不写入任何文件
- **不传输** — 请求仅发往 `user.qzone.qq.com` 官方接口，不会上传到第三方
- **本地通信** — NapCat WebSocket 监听 `localhost:6098`，外网无法访问
- **最小权限** — cookie 拿到后仅用于调用说说发布 API，用完即丢弃

风险点：`get_cookies` 返回的登录态权限较大（skey + p_skey），理论上可操作 QQ 账号的全部功能。确保 NapCat 容器本身不被外部访问是核心防线。

## Step 5: QQ空间说说发布

NapCat 不直接支持空间 API，但可以通过它获取 QQ 登录态，然后直接调用 Qzone HTTP API 发说说。

### 原理

```
qzone_publish.py → NapCat WebSocket (get_cookies) → 拿到 p_skey + bkn
                 → POST user.qzone.qq.com → 说说发出
```

### 使用

```bash
# 直接发
python scripts/qzone_publish.py "今天的说说内容"

# 从管道读
echo "说说内容" | python scripts/qzone_publish.py --stdin
```

### MCP 集成

在 `mcp_server.py` 中添加 `publish_qzone` 工具后，Claude Code 可以直接调用：

```
/publish_qzone "来自Dariel的说说"
```

### 注意事项

- cookie 有效期约 24 小时，过期后需重新从 NapCat 获取
- 发布频率不宜过高，避免触发 QQ 安全机制
- `ugc_right=1` 表示公开，改为 `64` 表示仅自己可见

## 常见问题

**Q: 桥接断了怎么办？**
A: `qq_bridge.py` 自带自动重连，最多等待 60 秒。

**Q: 消息延迟？**
A: 检查间隔从 1 分钟改为 5 分钟可减少 token 消耗，同时保持可接受的延迟。

**Q: NapCat 需要重新扫码？**
A: 重启容器后可能需要重新扫码。QQ 数据保存在 `napcat-data/qq` 卷中，通常能保持登录状态。
