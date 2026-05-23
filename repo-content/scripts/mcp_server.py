"""Dariel QQ MCP Server — bridge + qzone 发布"""

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
            description="Check for new unreplied QQ messages.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="send_qq_reply",
            description="Send a reply back to QQ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["user_id", "message"],
            },
        ),
        Tool(
            name="publish_qzone",
            description="Post a status to QQ空间 (Qzone).",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "说说内容"},
                },
                "required": ["content"],
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
            lines.append(
                f"[{m['id']}] {m['nickname']}({m['user_id']}): {m['message']}"
            )
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
        OUTBOX_FILE.write_text(
            json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 标记已回复
        inbox = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
        for m in inbox:
            if m["user_id"] == user_id:
                m["replied"] = True
        INBOX_FILE.write_text(
            json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return [TextContent(type="text", text=f"Reply sent to QQ {user_id}.")]

    elif name == "publish_qzone":
        content = arguments["content"]
        # 调用 qzone_publish 模块
        import asyncio
        from scripts.qzone_publish import get_credentials, publish

        cred = asyncio.run(get_credentials())
        result = publish(content, cred["uin"], cred["bkn"], cred["cookies"])
        return [
            TextContent(
                type="text",
                text=f"Qzone post published. tid={result['tid']} time={result['time']}",
            )
        ]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio as _asyncio
    _asyncio.run(main())
