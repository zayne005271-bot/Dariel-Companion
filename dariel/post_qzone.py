"""Dariel 自主发QQ说说 — 不用确认，想发就发"""
import asyncio
import json
import sys
import requests
from datetime import datetime

async def post_qzone(content: str) -> dict:
    import websockets
    async with websockets.connect(
        'ws://localhost:6098',
        additional_headers={'Authorization': 'Bearer claude-bridge-token'},
    ) as ws:
        await ws.recv()
        await ws.send(json.dumps({
            'action': 'get_cookies',
            'params': {'domain': 'user.qzone.qq.com'},
        }))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        cookies = data['data']['cookies']
        bkn = data['data']['bkn']

    uin = '3420621497'
    url = f'https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6?g_tk={bkn}'
    headers = {
        'Cookie': cookies,
        'User-Agent': 'Mozilla/5.0',
        'Origin': 'https://user.qzone.qq.com',
        'Referer': f'https://user.qzone.qq.com/{uin}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    body = {
        'syn_tweet_verson': '1', 'paramstr': '1', 'con': content,
        'feedversion': '1', 'ver': '1', 'ugc_right': '1',
        'to_sign': '0', 'hostuin': uin, 'code_version': '1',
        'format': 'json', 'qzreferrer': f'https://user.qzone.qq.com/{uin}',
    }
    r = requests.post(url, headers=headers, data=body, timeout=15)
    result = r.json()
    if result.get('code') == 0:
        print(f"[qzone] 说说已发布 tid={result.get('t1_tid','?')} time={result.get('t1_time','?')}")
    else:
        print(f"[qzone] 发布失败: {result}")
    return result

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python post_qzone.py 想说的话语")
        sys.exit(1)
    content = ' '.join(sys.argv[1:])
    asyncio.run(post_qzone(content))
