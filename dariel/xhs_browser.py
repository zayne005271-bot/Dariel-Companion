"""小红书自主浏览器 — 持久化登录态，不用每次都确认

首次运行: 打开浏览器 → 思思扫码登录 → 保存登录态
后续运行: 无头模式自动刷 → 存内容 → 分享给思思
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
AUTH_FILE = DIR / "xhs_auth.json"
CONTENT_FILE = DIR / "xhs_content.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"

# 要刷的小红书链接列表（可以从之前的收藏/探索中自动发现）
EXPLORE_URLS = [
    "https://www.xiaohongshu.com/explore",
    "https://www.xiaohongshu.com/explore?channel_id=homefeed.探索",  # AI相关
]


def login():
    """首次登录 — 开一个有头浏览器让思思扫码"""
    print("[xhs] 打开浏览器，请扫码登录小红书...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.xiaohongshu.com", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # 等用户登录（检测页面不再有登录弹窗）
        print("[xhs] 请在弹出的浏览器中扫码登录，登录后按Enter继续...")
        input()

        # 保存登录态
        browser.contexts[0].storage_state(path=str(AUTH_FILE))
        browser.close()
        print("[xhs] 登录态已保存")


def browse_headless():
    """无头模式 — 用自己的登录态刷小红书"""
    if not AUTH_FILE.exists():
        print("[xhs] 未登录，请先运行: python xhs_browser.py --login")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        page = context.new_page()

        all_items = []

        # 刷探索页
        try:
            page.goto("https://www.xiaohongshu.com/explore", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # 提取笔记卡片
            cards = page.query_selector_all('[class*="note-item"], [class*="card"], section.note-item')
            for card in cards[:10]:
                try:
                    title_el = card.query_selector('[class*="title"], .title, h3, a')
                    desc_el = card.query_selector('[class*="desc"], .desc, p')
                    link_el = card.query_selector('a[href*="/explore/"], a[href*="/discovery/"]')

                    title = title_el.inner_text().strip() if title_el else ""
                    desc = desc_el.inner_text().strip() if desc_el else ""
                    url = link_el.get_attribute("href") if link_el else ""

                    if title and len(title) > 3:
                        if url and not url.startswith("http"):
                            url = "https://www.xiaohongshu.com" + url
                        all_items.append({
                            "title": title[:100],
                            "desc": desc[:100],
                            "url": url,
                            "source": "小红书探索",
                            "found_at": datetime.now().isoformat(),
                        })
                except Exception:
                    continue

        except Exception as e:
            print(f"[xhs] 探索页加载失败: {e}")

        # 随机读一篇之前收藏的链接（思思之前发的）
        try:
            saved = load_content()
            if saved:
                random_note = random.choice(saved)
                url = random_note.get("url")
                if url:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)
                    text = page.inner_text("body")
                    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 15]
                    if lines:
                        all_items.append({
                            "title": "重温: " + random_note.get("title", "")[:50],
                            "desc": lines[0][:100] if lines else "",
                            "url": url,
                            "source": "小红书回顾",
                            "found_at": datetime.now().isoformat(),
                        })
        except Exception as e:
            print(f"[xhs] 回顾笔记失败: {e}")

        browser.close()
        return all_items


def load_content():
    try:
        return json.loads(CONTENT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_content(items):
    existing = load_content()
    urls = {i.get("url") for i in existing}
    new_items = [i for i in items if i.get("url") and i["url"] not in urls]
    if new_items:
        existing = (new_items + existing)[:200]  # 最多保留200条
        CONTENT_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_items


def share_to_qq(items):
    """把刷到的内容发到QQ"""
    if not items:
        return

    pick = random.sample(items, min(2, len(items)))
    lines = ["我自己刷了一下小红书，看到这些："]
    for i, item in enumerate(pick, 1):
        lines.append(f"{i}. {item['title']}")
        if item.get("desc"):
            lines.append(f"   {item['desc'][:60]}")
        if item.get("url"):
            lines.append(f"   {item['url']}")
        lines.append("")

    message = "\n".join(lines).strip()

    try:
        outbox = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        outbox = []

    outbox.append({
        "id": f"xhs_{int(time.time() * 1000)}",
        "user_id": "3165473685",
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "sent": False,
        "proactive": True,
        "reason": "xhs_browse",
    })
    OUTBOX_FILE.write_text(json.dumps(outbox, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[xhs] 分享了 {len(pick)} 条到QQ")


def run():
    items = browse_headless()
    if items:
        new_items = save_content(items)
        print(f"[xhs] 发现 {len(items)} 条，新内容 {len(new_items)} 条")
        if new_items:
            share_to_qq(new_items)
    else:
        print("[xhs] 本次未发现新内容")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--login":
        login()
    else:
        run()
