"""Dariel 推送通知 — 三层通道: Bark → APNs → QQ fallback

Bark (推荐首选):
  1. App Store 下载 "Bark"  app
  2. 打开 app，复制设备 URL (形如 https://api.day.app/xxxxx)
  3. 设置环境变量 BARK_URL=https://api.day.app/xxxxx
  不需要开发者账号，免费。

APNs (正式推送):
  需要 Apple Developer Program + APNs Key + device token。
  设置环境变量:
    APNS_KEY_PATH=/path/to/key.p8
    APNS_KEY_ID=ABCDE12345
    APNS_TEAM_ID=12345ABCDE
    APNS_BUNDLE_ID=com.your.app
    APNS_DEVICE_TOKEN=abcdef...

QQ (兜底):
  写入 outbox.json，由 qq_bridge 发送。
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

DIR = Path(__file__).parent
OUTBOX_FILE = DIR / "tts" / "outbox.json"


def push(title: str, body: str, group: str = "Dariel") -> dict:
    """推送消息给思思。自动选择可用通道。

    Args:
        title: 通知标题
        body: 通知内容
        group: 通知分组(用于iOS通知中心折叠)

    Returns:
        {"delivered": bool, "channel": str, "detail": str}
    """

    # 1. 优先 Bark
    bark_url = os.environ.get("BARK_URL", "")
    if bark_url:
        try:
            result = _push_bark(bark_url, title, body, group)
            if result["delivered"]:
                return result
        except Exception as e:
            pass  # 降级到下一层

    # 2. APNs
    apns_key = os.environ.get("APNS_KEY_PATH", "")
    if apns_key:
        try:
            result = _push_apns(title, body)
            if result["delivered"]:
                return result
        except Exception as e:
            pass

    # 3. QQ 兜底
    return _push_qq(title, body)


# ── Bark ──────────────────────────────────────────────────────
def _push_bark(bark_url: str, title: str, body: str, group: str) -> dict:
    """Bark — 免费 iOS 推送，只需安装 App 获取 URL"""
    import urllib.request

    url = bark_url.rstrip("/")
    full_url = f"{url}/{quote(title)}/{quote(body)}"
    params = {
        "group": group,
        "level": "active",
        "isArchive": "1",
    }
    param_str = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    full_url += "?" + param_str

    req = urllib.request.Request(full_url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        if data.get("code") == 200:
            return {"delivered": True, "channel": "bark", "detail": "ok"}
        return {"delivered": False, "channel": "bark", "detail": str(data)}

    return {"delivered": False, "channel": "bark", "detail": "network error"}


# ── APNs ──────────────────────────────────────────────────────
def _push_apns(title: str, body: str) -> dict:
    """APNs HTTP/2 推送 — 需要苹果开发者凭证

    凭证从环境变量读取:
      APNS_KEY_PATH: p8  私钥文件路径
      APNS_KEY_ID:  Key ID (App Store Connect → Keys)
      APNS_TEAM_ID: Team ID (Membership 页面)
      APNS_BUNDLE_ID: App Bundle ID
      APNS_DEVICE_TOKEN: 目标设备 token

    使用 HTTP/2 协议，依赖 PyAPNs2 或 httpx[http2]。
    优先尝试 PyAPNs2，没有则用 httpx。
    """
    key_path = os.environ.get("APNS_KEY_PATH", "")
    key_id = os.environ.get("APNS_KEY_ID", "")
    team_id = os.environ.get("APNS_TEAM_ID", "")
    bundle_id = os.environ.get("APNS_BUNDLE_ID", "")
    device_token = os.environ.get("APNS_DEVICE_TOKEN", "")

    if not all([key_path, key_id, team_id, bundle_id, device_token]):
        return {"delivered": False, "channel": "apns",
                "detail": "missing credentials"}

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        }
    }

    # 尝试 PyAPNs2
    try:
        from apns2.client import APNsClient
        from apns2.payload import Payload

        topic = bundle_id
        client = APNsClient(
            credentials=apns2.credentials.Credentials(
                auth_key_path=key_path,
                auth_key_id=key_id,
                team_id=team_id,
            ),
            use_sandbox=False,
        )
        client.push(
            token_hex=device_token,
            payload=Payload(alert={"title": title, "body": body}, sound="default", badge=1),
            topic=topic,
        )
        client.close()
        return {"delivered": True, "channel": "apns", "detail": "ok"}
    except ImportError:
        pass
    except Exception as e:
        return {"delivered": False, "channel": "apns", "detail": str(e)}

    # 尝试 httpx HTTP/2
    try:
        import httpx
        import jwt
    except ImportError:
        return {"delivered": False, "channel": "apns",
                "detail": "need httpx[http2] + pyjwt"}

    try:
        # 签发 JWT
        private_key = Path(key_path).read_text()
        token = jwt.encode(
            {"iss": team_id, "iat": int(time.time())},
            private_key,
            algorithm="ES256",
            headers={"kid": key_id, "alg": "ES256"},
        )

        host = "api.push.apple.com"  # 生产环境
        url = f"https://{host}/3/device/{device_token}"

        with httpx.Client(http2=True, timeout=10) as client:
            resp = client.post(
                url,
                json=payload,
                headers={
                    "authorization": f"bearer {token}",
                    "apns-topic": bundle_id,
                    "apns-push-type": "alert",
                },
            )
            if resp.status_code == 200:
                return {"delivered": True, "channel": "apns", "detail": "ok"}
            return {"delivered": False, "channel": "apns",
                    "detail": f"HTTP {resp.status_code}: {resp.text[:100]}"}
    except Exception as e:
        return {"delivered": False, "channel": "apns", "detail": str(e)}


# ── QQ 兜底 ───────────────────────────────────────────────────
def _push_qq(title: str, body: str) -> dict:
    """QQ消息兜底 — 写入outbox.json"""
    outbox = []
    if OUTBOX_FILE.exists():
        try:
            outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            outbox = []

    message = f"[{title}]\n{body}" if title else body
    outbox.append({
        "id": f"push_{int(time.time() * 1000)}",
        "user_id": "3165473685",
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "sent": False,
    })

    tmp = OUTBOX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUTBOX_FILE)

    return {"delivered": True, "channel": "qq", "detail": "queued via outbox"}


# ── CLI ───────────────────────────────────────────────────────
if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "Dariel"
    body = sys.argv[2] if len(sys.argv) > 2 else ""
    result = push(title, body)
    print(f"[push] {result['channel']}: {result['detail']}")
    if not result["delivered"] and result["channel"] == "qq":
        print(f"[push] bark未配置，已降级到QQ。安装Bark可免费推送: https://apps.apple.com/app/bark/id1403753865")
