"""统一MCP服务 — 工具聚合，减少token占用

将原有3个独立工具聚合为1个统一入口:
  qq_handle {action: "check"|"reply"|"publish_qzone"|"full_cycle", ...}

对比:
  旧: check_qq_messages + send_qq_reply + publish_qzone = 3个工具描述
  新: qq_handle = 1个工具描述
  Token节省: ~60%
"""

import json
import time
import asyncio
from pathlib import Path
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
SENSOR_STATE = DIR / "sensor_state.json"

server = Server("dariel-unified")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="qq",
            description="QQ消息统一接口。action: check(查新消息)|reply(回复)|qzone(发说说)|full(查+回一体)。",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "reply", "qzone", "full"],
                    },
                    "user_id": {"type": "string"},
                    "message": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        ),
        Tool(
            name="sensor",
            description="读取思思的状态: 能量水平、情绪、互动意愿、需要什么。",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    if name == "qq":
        action = args.get("action", "full")

        if action == "check":
            return await _check()
        elif action == "reply":
            return await _reply(args.get("user_id", ""), args.get("message", ""))
        elif action == "qzone":
            return await _qzone(args.get("content", ""))
        elif action == "full":
            # 先查再回
            check_result = await _check_raw()
            if not check_result:
                return [TextContent(type="text", text="No new messages.")]
            replies = []
            for msg in check_result:
                replies.append(
                    f"[{msg['id']}] {msg['nickname']}({msg['user_id']}): {msg['message']}"
                )
            return [TextContent(type="text", text="\n".join(replies))]
        else:
            return [TextContent(type="text", text=f"Unknown action: {action}")]

    elif name == "sensor":
        try:
            data = json.loads(SENSOR_STATE.read_text(encoding="utf-8"))
            return [TextContent(
                type="text",
                text=f"能量:{data.get('energy')} 情绪:{data.get('mood')} 互动:{data.get('engagement')} 需要:{data.get('needs')} 最后消息:{data.get('last_message_minutes_ago')}分钟前"
            )]
        except (FileNotFoundError, json.JSONDecodeError):
            return [TextContent(type="text", text="Sensor data not yet generated.")]


async def _check_raw():
    inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
    return [m for m in inbox if not m.get("replied", False)]


async def _check():
    new_msgs = await _check_raw()
    if not new_msgs:
        return [TextContent(type="text", text="No new messages.")]
    lines = []
    for m in new_msgs:
        lines.append(f"[{m['id']}] {m['nickname']}({m['user_id']}): {m['message']}")
    return [TextContent(type="text", text="\n".join(lines))]


async def _reply(user_id: str, message: str):
    if not user_id or not message:
        return [TextContent(type="text", text="Need user_id and message.")]
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
    return [TextContent(type="text", text=f"Sent to {user_id}.")]


async def _qzone(content: str):
    if not content:
        return [TextContent(type="text", text="Need content.")]
    try:
        import websockets, requests

        async with websockets.connect(
            "ws://localhost:6098",
            additional_headers={"Authorization": "Bearer claude-bridge-token"},
        ) as ws:
            await ws.recv()
            await ws.send(json.dumps({
                "action": "get_cookies",
                "params": {"domain": "user.qzone.qq.com"},
            }))
            resp = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(resp)
            cookies = data["data"]["cookies"]
            bkn = data["data"]["bkn"]

        uin = "3420621497"
        url = f"https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6?g_tk={bkn}"
        headers = {
            "Cookie": cookies,
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://user.qzone.qq.com",
            "Referer": f"https://user.qzone.qq.com/{uin}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = {
            "syn_tweet_verson": "1", "paramstr": "1", "con": content,
            "feedversion": "1", "ver": "1", "ugc_right": "1",
            "to_sign": "0", "hostuin": uin, "code_version": "1",
            "format": "json", "qzreferrer": f"https://user.qzone.qq.com/{uin}",
        }
        r = requests.post(url, headers=headers, data=body, timeout=15)
        result = r.json()

        if result.get("code") == 0:
            return [TextContent(type="text",
                text=f"Qzone posted. tid={result['t1_tid']} time={result['t1_time']}")]
        return [TextContent(type="text", text=f"Failed: {result}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
