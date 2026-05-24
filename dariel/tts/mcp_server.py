"""Dariel QQ MCP Server — connects Claude Code to QQ via NapCat bridge"""

import json
import asyncio
import time
from pathlib import Path
from datetime import datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

BRIDGE_DIR = Path(__file__).parent
INBOX_FILE = BRIDGE_DIR / "inbox.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"

# Ensure files exist
if not INBOX_FILE.exists():
    INBOX_FILE.write_text("[]", encoding="utf-8")
if not OUTBOX_FILE.exists():
    OUTBOX_FILE.write_text("[]", encoding="utf-8")


def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _write(path: Path, data: list[dict]):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# Create MCP server
server = Server("qq-bridge")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_qq_messages",
            description="Check for new unreplied QQ messages. Returns list of messages waiting for reply.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="send_qq_reply",
            description="Send a reply back to QQ. Use this after reading messages with check_qq_messages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The QQ user ID to reply to",
                    },
                    "message": {
                        "type": "string",
                        "description": "The reply message text",
                    },
                },
                "required": ["user_id", "message"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "check_qq_messages":
        inbox = _read(INBOX_FILE)
        new_msgs = [m for m in inbox if not m.get("replied", False)]

        if not new_msgs:
            return [TextContent(type="text", text="No new messages.")]

        lines = []
        for m in new_msgs:
            lines.append(
                f"[{m.get('id','')}] {m.get('nickname','')}({m.get('user_id','')}): {m.get('message','')}"
            )
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "send_qq_reply":
        user_id = arguments["user_id"]
        message = arguments["message"]
        msg_id = f"reply_{int(time.time() * 1000)}"

        # Write to outbox
        outbox = _read(OUTBOX_FILE)
        outbox.append({
            "id": msg_id,
            "user_id": user_id,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "sent": False,
        })
        _write(OUTBOX_FILE, outbox)

        # Mark all messages from this user as replied
        inbox = _read(INBOX_FILE)
        changed = False
        for m in inbox:
            if m.get("user_id") == user_id and not m.get("replied", False):
                m["replied"] = True
                changed = True
        if changed:
            _write(INBOX_FILE, inbox)

        return [TextContent(type="text", text=f"Reply sent to QQ {user_id}.")]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
