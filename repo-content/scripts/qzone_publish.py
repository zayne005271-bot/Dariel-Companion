"""QQ空间说说发布 — 通过 NapCat 获取登录态，直接调用 Qzone HTTP API"""

import asyncio
import json
import time
import sys
import argparse
from urllib.parse import urlencode
import websockets
import requests


NAP_WS = "ws://localhost:6098"
NAP_TOKEN = "claude-bridge-token"

PUBLISH_URL = (
    "https://user.qzone.qq.com/proxy/domain/"
    "taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"
)


async def get_credentials() -> dict:
    """从 NapCat WebSocket 获取 cookie 和 bkn"""
    async with websockets.connect(
        NAP_WS,
        additional_headers={"Authorization": f"Bearer {NAP_TOKEN}"},
    ) as ws:
        await ws.recv()  # 跳过 lifecycle 事件
        payload = {"action": "get_cookies", "params": {"domain": "user.qzone.qq.com"}}
        await ws.send(json.dumps(payload))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        if data.get("retcode") != 0:
            raise RuntimeError(f"获取cookie失败: {data.get('message')}")

        cookies = data["data"]["cookies"]
        bkn = data["data"]["bkn"]

        # 从 cookie 中提取 uin
        uin = ""
        for item in cookies.split("; "):
            if item.startswith("uin="):
                uin = item.split("=")[1]
                if uin.startswith("o"):
                    uin = uin[1:]
                break

        return {"cookies": cookies, "bkn": bkn, "uin": uin}


def publish(content: str, uin: str, bkn: str, cookies: str) -> dict:
    """发布一条空间说说"""
    url = f"{PUBLISH_URL}?g_tk={bkn}"

    headers = {
        "Cookie": cookies,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko)"
        ),
        "Origin": "https://user.qzone.qq.com",
        "Referer": f"https://user.qzone.qq.com/{uin}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    body = {
        "syn_tweet_verson": "1",
        "paramstr": "1",
        "con": content,
        "feedversion": "1",
        "ver": "1",
        "ugc_right": "1",
        "to_sign": "0",
        "hostuin": uin,
        "code_version": "1",
        "format": "json",
        "qzreferrer": f"https://user.qzone.qq.com/{uin}",
    }

    r = requests.post(url, headers=headers, data=body, timeout=15)
    result = r.json()

    if result.get("code") != 0:
        raise RuntimeError(f"发布失败: {result.get('message', r.text)}")

    return {
        "tid": result.get("t1_tid"),
        "time": result.get("t1_time"),
        "content": result.get("content"),
    }


async def main():
    parser = argparse.ArgumentParser(description="发布QQ空间说说")
    parser.add_argument("content", nargs="*", help="说说内容")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取内容")
    args = parser.parse_args()

    if args.stdin:
        content = sys.stdin.read().strip()
    elif args.content:
        content = " ".join(args.content)
    else:
        print("用法: python qzone_publish.py <说说内容>")
        print("      echo 内容 | python qzone_publish.py --stdin")
        sys.exit(1)

    if not content:
        print("错误: 内容不能为空")
        sys.exit(1)

    print(f"[qzone] 获取登录态...")
    cred = await get_credentials()
    print(f"[qzone] 发布说说: {content[:50]}...")
    result = publish(content, cred["uin"], cred["bkn"], cred["cookies"])
    print(f"[qzone] 发布成功! tid={result['tid']} time={result['time']}")


if __name__ == "__main__":
    asyncio.run(main())
