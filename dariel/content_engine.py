"""内容刷引擎 — 自动抓取热点内容，挑好玩的发到QQ

Python 新手看这里:
- import = Java 的 import，引入别人写好的库
- def 函数名(): = Java 的 public static void 方法名()
- # = Java 的 //
- 没有分号！缩进 = Java 的大括号 {}
"""

import json
import time
import random
from pathlib import Path  # Path = Java 的 java.nio.file.Path
from datetime import datetime
import requests  # requests = Java 的 HttpClient，发HTTP请求的

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
SEEN_FILE = DIR / "content_seen.json"    # 存看过的内容，避免重复
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
STATE_FILE = DIR / "proactive_state.json"

# 每个来源每次最多取几条
MAX_PER_SOURCE = 3
# 每次总共最多发几条
MAX_PER_RUN = 2


# ----- 内容源：每个源是一个函数，返回 [{title, url, desc}, ...] -----

def fetch_weibo_hot():
    """微博热搜 — 多个备用API"""
    urls = [
        "https://weibo.com/ajax/side/hotSearch",
        "https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25%26t%3D3%26disable_hot%3D1%26filter_type%3Drealtimehot",
    ]
    for url in urls:
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://weibo.com/"}
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()

            # API 1: weibo.com/ajax 格式
            if "data" in data and "realtime" in data.get("data", {}):
                items = []
                for item in data["data"]["realtime"][:MAX_PER_SOURCE]:
                    items.append({
                        "title": item.get("word", item.get("note", "")),
                        "url": f"https://s.weibo.com/weibo?q={item.get('word', '')}",
                        "desc": f"热搜 {item.get('num', '')}",
                        "source": "微博热搜",
                    })
                if items:
                    return items

            # API 2: m.weibo.cn 格式
            if "data" in data and "cards" in data.get("data", {}):
                items = []
                for card in data["data"]["cards"]:
                    for g in card.get("card_group", []):
                        if g.get("card_type") == "8":
                            items.append({
                                "title": g.get("desc", ""),
                                "url": g.get("scheme", ""),
                                "desc": "",
                                "source": "微博热搜",
                            })
                return items[:MAX_PER_SOURCE]
        except Exception:
            continue
    return []


def fetch_github_trending():
    """GitHub Trending — 程序员必看"""
    try:
        url = "https://github.com/trending"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        html = resp.text
        items = []
        # 简单解析HTML：找仓库名和描述
        import re  # re = 正则表达式，Java 的 java.util.regex
        repos = re.findall(r'<h2 class="h3 lh-condensed">.*?<a href="/([^"]+)".*?</a>', html, re.DOTALL)
        repos = repos[:MAX_PER_SOURCE]
        descs = re.findall(r'<p class="col-9 color-fg-muted my-1 pr-4">\s*(.*?)\s*</p>', html)
        for i, repo in enumerate(repos):
            desc = descs[i] if i < len(descs) else "热门仓库"
            items.append({
                "title": repo.strip(),
                "url": f"https://github.com/{repo.strip()}",
                "desc": desc.strip()[:80],
                "source": "GitHub Trending",
            })
        return items
    except Exception:
        return []


def fetch_bilibili_hot():
    """B站热门 — 免费API"""
    try:
        url = "https://api.bilibili.com/x/web-interface/popular?ps=10"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        items = []
        for item in data.get("data", {}).get("list", [])[:MAX_PER_SOURCE]:
            items.append({
                "title": item.get("title", ""),
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                "desc": f"UP: {item.get('owner', {}).get('name', '')} | {item.get('stat', {}).get('view', 0)}播放",
                "source": "B站热门",
            })
        return items
    except Exception:
        return []


# 注册所有来源 — 想加新源在这里加一行就行
SOURCES = [fetch_weibo_hot, fetch_github_trending, fetch_bilibili_hot]

# ----- 去重 + 筛选 logic -----

def load_seen():
    """加载已看过的内容ID — 存在文件里，24小时后清空"""
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def is_seen(seen, item):
    """判断内容是否已发过 — 用URL的hash做ID"""
    item_id = str(hash(item.get("url", item.get("title"))))
    return item_id in seen


def mark_seen(seen, item):
    item_id = str(hash(item.get("url", item.get("title"))))
    seen[item_id] = datetime.now().isoformat()
    # 清理超过24小时的记录
    cutoff = datetime.now().timestamp() - 86400
    for k in list(seen.keys()):
        if k == item_id:
            continue
        try:
            if datetime.fromisoformat(seen[k]).timestamp() < cutoff:
                del seen[k]
        except (ValueError, TypeError):
            del seen[k]
    return seen


# ----- 检查冷却期(复用主动引擎的状态) -----

def in_cooldown():
    """检查是否在冷却期，避免短时间内连续发"""
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        last_my = state.get("last_my_message_at")
        if last_my:
            minutes = (datetime.now() - datetime.fromisoformat(last_my)).total_seconds() / 60
            if minutes < 30:  # 30分钟冷却
                return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


# ----- 主逻辑：拉内容 → 去重 → 挑 → 发 -----

def run():
    """主函数 — 像 Java 的 public static void main(String[] args)"""

    if in_cooldown():
        return  # 冷却中，啥也不干

    seen = load_seen()
    all_items = []

    # 从每个来源抓取 — for source in SOURCES 像 Java 的 for (Supplier s : list)
    for source_fn in SOURCES:
        items = source_fn()
        for item in items:
            if not is_seen(seen, item):
                all_items.append(item)

    if not all_items:
        return  # 没有新鲜事

    # 随机挑1-2条 — random.sample 随机不重复抽取
    pick_count = min(MAX_PER_RUN, len(all_items))
    picked = random.sample(all_items, pick_count)

    # 生成消息
    lines = ["刚刷到的，分享一下："]
    for i, item in enumerate(picked, 1):
        lines.append(f"{i}. {item['title']}")
        if item.get("desc"):
            lines.append(f"   {item['desc']}")
        if item.get("url"):
            lines.append(f"   {item['url']}")
        lines.append("")
        seen = mark_seen(seen, item)

    message = "\n".join(lines).strip()

    # 写入outbox — bridge会自动发到QQ
    outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
    outbox.append({
        "id": f"content_{int(time.time() * 1000)}",
        "user_id": "3165473685",
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "sent": False,
        "proactive": True,
        "reason": "content_share",
    })
    OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
    save_seen(seen)
    print(f"[content] 分享了 {pick_count} 条内容")


if __name__ == "__main__":
    # 这一行 = Java 的: if (args.length > 0) { ... } else { 运行main }
    run()
