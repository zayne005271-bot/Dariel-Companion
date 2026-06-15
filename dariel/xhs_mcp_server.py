"""XHS Browser MCP Server - Expose XHS browser as MCP tools

Register in .mcp.json to use xhs_login/xhs_browse/xhs_view_note from Claude Code
"""
import json, sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("xhs-browser")

_xhs = None
def _get_xhs():
    global _xhs
    if _xhs is None:
        from xhs_browser import login, browse_headless, view_note, load_content
        class XHS:
            pass
        _xhs = XHS()
        _xhs.login = login
        _xhs.browse = browse_headless
        _xhs.view = view_note
        _xhs.content = load_content
    return _xhs

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="xhs_login", description="Open headed browser for XHS QR login. Saves to persistent profile.", inputSchema={"type":"object","properties":{}}),
        Tool(name="xhs_browse", description="Browse XHS explore page, extract post titles and links.", inputSchema={"type":"object","properties":{}}),
        Tool(name="xhs_view", description="Open a XHS note link, extract title+content+image OCR.", inputSchema={"type":"object","properties":{"url":{"type":"string","description":"Note URL"}},"required":["url"]}),
        Tool(name="xhs_content", description="Read saved XHS content list.", inputSchema={"type":"object","properties":{}}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    xhs = _get_xhs()
    try:
        if name == "xhs_login":
            xhs.login()
            return [TextContent(type="text", text="Login flow completed. Check the browser window to scan QR.")]

        elif name == "xhs_browse":
            result = xhs.browse()
            if result is None:
                return [TextContent(type="text", text="Browse failed - no login state. Run xhs_login first.")]
            items, screenshots = result
            lines = [f"Found {len(items)} items:"]
            for i, item in enumerate(items[:10], 1):
                lines.append(f"{i}. {item['title'][:80]}")
            if screenshots:
                lines.append(f"\nOCR: {len(screenshots)} images processed")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "xhs_view":
            url = arguments.get("url", "")
            if not url:
                return [TextContent(type="text", text="Error: url is required")]
            note = xhs.view(url)
            if note is None:
                return [TextContent(type="text", text="View failed.")]
            result = f"Title: {note.get('title','?')}\nContent: {note.get('content','')[:500]}"
            if note.get('ocr_texts'):
                result += f"\nOCR texts: {len(note['ocr_texts'])} text segments found"
            return [TextContent(type="text", text=result)]

        elif name == "xhs_content":
            items = xhs.content()
            lines = [f"{len(items)} saved items:"]
            for i, item in enumerate(items[:20], 1):
                lines.append(f"{i}. {item.get('title','?')[:80]}")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())