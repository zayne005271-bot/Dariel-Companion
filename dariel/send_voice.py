"""Dariel 发语音 — 合成 + 发送 QQ 语音消息，一步完成"""
import asyncio
import json
import sys
import base64
import re
from pathlib import Path

DIR = Path(__file__).parent
OUTPUT_DIR = DIR / "output"

# ElevenLabs配置 — 从 tts/.env 加载
def _load_env():
    env_file = DIR / "tts" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                import os
                os.environ.setdefault(key.strip(), val.strip())

_load_env()
API_KEY = __import__('os').environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = __import__('os').environ.get("ELEVENLABS_VOICE_ID", "")


async def send_voice(text: str, lang: str = "en"):
    """合成语音并通过QQ发送"""
    import requests, websockets
    from datetime import datetime

    # 1. 合成语音
    print(f"[voice] 合成: {text[:50]}...")
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"[voice] API错误: {resp.status_code} {resp.text}")
        return None

    mp3_data = resp.content

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^\w]', '', text[:20]).strip()
    filepath = OUTPUT_DIR / f"voice_{ts}_{safe_name}.mp3"
    filepath.write_bytes(mp3_data)
    print(f"[voice] 已保存: {filepath}")

    # 2. 发送QQ语音
    b64 = base64.b64encode(mp3_data).decode()
    async with websockets.connect(
        "ws://localhost:6098",
        additional_headers={"Authorization": "Bearer claude-bridge-token"},
    ) as ws:
        await ws.recv()
        payload = {
            "action": "send_private_msg",
            "params": {
                "user_id": 3165473685,
                "message": f"[CQ:record,file=base64://{b64}]",
            },
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        result = json.loads(resp)
        if result.get("retcode") == 0:
            print(f"[voice] 语音已发送 msg_id={result['data']['message_id']}")
        else:
            print(f"[voice] 发送失败: {result}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python send_voice.py 要说的话")
        print("英文: python send_voice.py Good night, sweet dreams.")
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    asyncio.run(send_voice(text))
