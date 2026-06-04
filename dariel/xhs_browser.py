"""小红书自主浏览器 — 持久化登录态，不用每次都确认

首次运行: 打开浏览器 → 思思扫码登录 → 保存登录态
后续运行: 无头模式自动刷 → 存内容 → OCR图片 → 分享给思思
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
SCREENSHOT_DIR = DIR / "xhs_screenshots"

# 反检测：XHS会检查webdriver标记、headless特征等
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--window-size=1280,800",
]


def _create_stealth_context(playwright, headless=True):
    """创建带反检测的浏览器context，统一入口"""
    browser = playwright.chromium.launch(
        headless=headless,
        args=STEALTH_ARGS,
    )
    context = browser.new_context(
        storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None,
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    # 最关键：隐藏webdriver标记
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        window.chrome = {runtime: {}};
    """)
    page = context.new_page()
    return browser, context, page


def login():
    """首次登录 — 开一个有头浏览器让思思扫码"""
    print("[xhs] 打开浏览器，请扫码登录小红书...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.xiaohongshu.com", wait_until="networkidle")
        page.wait_for_timeout(2000)

        print("[xhs] 请在弹出的浏览器中扫码登录，登录后按Enter继续...")
        input()

        browser.contexts[0].storage_state(path=str(AUTH_FILE))
        browser.close()
        print("[xhs] 登录态已保存")


def browse_headless():
    """无头模式 — 用自己的登录态刷小红书"""
    if not AUTH_FILE.exists():
        print("[xhs] 未登录，请先运行: python xhs_browser.py --login")
        return None, None

    with sync_playwright() as p:
        browser, context, page = _create_stealth_context(p, headless=True)

        all_items = []

        # 刷探索页 — .note-item 是独立卡片
        try:
            page.goto("https://www.xiaohongshu.com/explore", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            seen_urls = set()
            note_items = page.query_selector_all('.note-item')
            for item in note_items:
                try:
                    text = item.inner_text().strip()
                    if not text or len(text) < 4:
                        continue

                    link = item.query_selector('a[href*="/explore/"]')
                    href = link.get_attribute("href") if link else ""
                    if not href:
                        continue

                    base_url = href.split("?")[0]
                    if base_url in seen_urls:
                        continue
                    seen_urls.add(base_url)

                    if not href.startswith("http"):
                        href = "https://www.xiaohongshu.com" + href

                    all_items.append({
                        "title": text[:120],
                        "url": href,
                        "source": "小红书探索",
                        "found_at": datetime.now().isoformat(),
                    })
                except Exception:
                    continue

        except Exception as e:
            print(f"[xhs] 探索页加载失败: {e}")

        # 提取封面图并OCR (如果easyocr可用)
        screenshots = ocr_cover_images(page, note_items, all_items, max_notes=3)

        browser.close()

        if screenshots:
            save_manifest(screenshots)

        return all_items, screenshots


def view_note(url):
    """打开具体笔记链接，提取标题+正文+图片OCR"""
    if not AUTH_FILE.exists():
        print("[xhs] 未登录，请先运行: python xhs_browser.py --login")
        return None

    with sync_playwright() as p:
        browser, context, page = _create_stealth_context(p, headless=True)

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[xhs] 笔记加载失败: {e}")
            browser.close()
            return None

        note = {"url": url, "source": "分享链接", "found_at": datetime.now().isoformat()}

        # 提取标题
        try:
            title_el = page.query_selector('#detail-title, .title, h1')
            if not title_el:
                title_el = page.query_selector('[class*="title"]')
            note["title"] = title_el.inner_text().strip()[:120] if title_el else "无标题"
        except Exception:
            note["title"] = "无标题"

        # 提取正文
        try:
            desc_el = page.query_selector('#detail-desc, .note-text, [class*="desc"]')
            if not desc_el:
                desc_el = page.query_selector('.content, [class*="content"]')
            note["content"] = desc_el.inner_text().strip()[:2000] if desc_el else ""
        except Exception:
            note["content"] = ""

        # 提取图片并OCR
        screenshots = []
        try:
            import easyocr
            reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
        except ImportError:
            reader = None

        if reader:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            try:
                imgs = page.query_selector_all('img[class*="note"], img[src*="sns"], .swiper-slide img, [class*="slide"] img')
                if not imgs:
                    imgs = page.query_selector_all('img')
            except Exception:
                imgs = []

            ocr_texts = []
            for i, img_el in enumerate(imgs[:5]):
                try:
                    src = img_el.get_attribute("src") or ""
                    if not src or "data:image" in src:
                        continue
                    filename = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}.png"
                    filepath = SCREENSHOT_DIR / filename
                    img_el.screenshot(path=str(filepath))

                    try:
                        ocr_result = reader.readtext(str(filepath), detail=0)
                        text = " ".join(ocr_result)[:500]
                        if text:
                            ocr_texts.append(text)
                    except Exception:
                        pass

                    screenshots.append({
                        "file": str(filepath),
                        "ocr_text": text if 'text' in dir() else "",
                    })
                except Exception:
                    continue

            if ocr_texts:
                note["ocr_texts"] = ocr_texts

        browser.close()

        if screenshots:
            save_manifest(screenshots)

        # 保存到content
        all_items = [note]
        save_content(all_items)

        return note


def ocr_cover_images(page, note_items, all_items, max_notes=3):
    """下载卡片封面图，尝试OCR识别图片中的文字"""
    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
    except ImportError:
        return []

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    # 重新获取note_items，避免stale element
    try:
        fresh_items = page.query_selector_all('.note-item')
    except Exception:
        fresh_items = note_items

    candidates = sorted(all_items, key=lambda x: len(x.get("title", "")), reverse=True)[:max_notes]

    for i, item in enumerate(candidates):
        try:
            # 在fresh items中找到匹配的
            target_el = None
            if i < len(fresh_items):
                target_el = fresh_items[i]

            if target_el:
                try:
                    target_el.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            filename = f"ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}.png"
            filepath = SCREENSHOT_DIR / filename

            # 截卡片封面图
            if target_el:
                img_el = target_el.query_selector('img')
                if img_el:
                    img_el.screenshot(path=str(filepath))
                else:
                    target_el.screenshot(path=str(filepath))
            else:
                page.screenshot(path=str(filepath), full_page=False)

            # OCR识别
            ocr_text = ""
            try:
                ocr_result = reader.readtext(str(filepath), detail=0)
                ocr_text = " ".join(ocr_result)[:300]
            except Exception:
                pass

            results.append({
                "file": str(filepath),
                "title": item.get("title", "")[:80],
                "url": item.get("url", ""),
                "ocr_text": ocr_text,
            })

        except Exception as e:
            print(f"[xhs] OCR失败: {e}")

    return results


def save_manifest(screenshots):
    manifest_file = SCREENSHOT_DIR / "manifest.json"
    manifest = []
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    manifest = (screenshots + manifest)[:20]
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


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
        existing = (new_items + existing)[:200]
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


def run(no_push=False):
    result = browse_headless()
    if result is None:
        return
    items, screenshots = result
    if items:
        new_items = save_content(items)
        print(f"[xhs] 发现 {len(items)} 条，新内容 {len(new_items)} 条")
        if new_items and not no_push:
            share_to_qq(new_items)
    else:
        print("[xhs] 本次未发现新内容")

    if screenshots:
        ocr_count = sum(1 for s in screenshots if s.get("ocr_text"))
        print(f"[xhs] OCR {len(screenshots)} 张封面，{ocr_count} 张有文字")
    return items, screenshots


if __name__ == "__main__":
    import sys
    no_push = "--no-push" in sys.argv
    if "--login" in sys.argv:
        login()
    elif "--link" in sys.argv:
        idx = sys.argv.index("--link")
        if idx + 1 < len(sys.argv):
            url = sys.argv[idx + 1]
            note = view_note(url)
            if note:
                print(f"[xhs] 标题: {note.get('title', '?')}")
                if note.get("content"):
                    print(f"[xhs] 正文:\n{note['content']}")
                if note.get("ocr_texts"):
                    for i, t in enumerate(note["ocr_texts"]):
                        print(f"[xhs] OCR[{i}]: {t}")
        else:
            print("[xhs] --link 需要URL参数")
    else:
        run(no_push=no_push)
