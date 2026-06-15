"""小红书自主浏览器 v2 — Playwright-Stealth + 持久化Profile

核心升级:
1. playwright-stealth 全面隐藏自动化特征
2. 持久化浏览器 profile (cookies/localStorage/cache 跨会话保留)
3. 真实 Chrome 指纹伪装（插件、字体、WebGL、canvas）
4. 登录态持久化到 profile，无需每次扫码

用法:
  python xhs_browser.py --login          # 首次登录(有头浏览器)
  python xhs_browser.py                  # 无头浏览探索页
  python xhs_browser.py --link <url>     # 打开具体笔记
  python xhs_browser.py --headed         # 有头模式(调试用)
"""

import json
import time
import random
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

DIR = Path(__file__).parent
BRIDGE_DIR = DIR / "tts"
PROFILE_DIR = DIR / "xhs_profile"          # 持久化浏览器profile（替代旧的AUTH_FILE）
AUTH_FILE = DIR / "xhs_auth.json"          # 保留兼容
CONTENT_FILE = DIR / "xhs_content.json"
OUTBOX_FILE = BRIDGE_DIR / "outbox.json"
SCREENSHOT_DIR = DIR / "xhs_screenshots"

# 真实 Chrome 125 UA
REAL_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 启动参数：关闭所有自动化检测标记
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-setuid-sandbox",
    "--disable-web-security",
    "--disable-features=VizDisplayCompositor",
    "--disable-background-networking",
    "--disable-default-apps",
    "--hide-scrollbars",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--window-size=1440,900",
    "--window-position=0,0",
]


def _create_persistent_context(playwright, headless=True):
    """创建带持久化 profile 的浏览器 context，统一入口

    核心反检测:
    - 持久化 user_data_dir: cookies/localStorage/cache 跨会话保留
    - launch_persistent_context: 使用真实浏览器 profile 目录
    - 全面的 chrome 指纹参数
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=STEALTH_ARGS,
        viewport={"width": 1440, "height": 900},
        user_agent=REAL_CHROME_UA,
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        permissions=["geolocation"],
        geolocation={"latitude": 30.5728, "longitude": 104.0668},  # 成都
        color_scheme="light",
        device_scale_factor=1,
        is_mobile=False,
        has_touch=False,
        java_script_enabled=True,
        bypass_csp=True,
        ignore_https_errors=True,
    )
    return context


def _apply_stealth(page):
    """对页面应用 playwright-stealth + 补充 init script

    两层防护:
    1. playwright-stealth 官方库 (覆盖 webdriver/plugins/chrome/webgl/fonts)
    2. 补充 init script (覆盖 mimeTypes/hardwareConcurrency/deviceMemory/connection)
    """
    try:
        from playwright_stealth import Stealth
        s = Stealth(
            navigator_languages=["zh-CN", "zh", "en-US", "en"],
            navigator_vendor="Google Inc.",
            navigator_platform="Win32",
            webgl_vendor="Google Inc. (NVIDIA)",
            hairline=True,
        )
        s.apply_stealth_sync(page)
        print("[xhs] playwright-stealth applied")
    except ImportError:
        print("[xhs] playwright-stealth not installed, using manual evasions only")

    # 补充 init script — 填补遗漏的检测点
    page.add_init_script("""
        // 1. webdriver (双保险)
        Object.defineProperty(navigator, 'webdriver', {get: () => false});

        // 2. plugins 完整伪造 (真实Chrome有5个插件)
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [
                    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
                    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
                    {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''},
                ];
                plugins.item = (i) => plugins[i] || null;
                plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
                plugins.refresh = () => {};
                Object.setProperty(plugins, 'length', plugins.length);
                return plugins;
            }
        });

        // 3. mimeTypes
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => {
                const mimeTypes = [
                    {type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format'},
                    {type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format'},
                ];
                mimeTypes.item = (i) => mimeTypes[i] || null;
                mimeTypes.namedItem = (name) => mimeTypes.find(m => m.type === name) || null;
                Object.setProperty(mimeTypes, 'length', mimeTypes.length);
                return mimeTypes;
            }
        });

        // 4. chrome 对象完整
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // 5. 通知权限查询 (不弹窗)
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (params) => (
            params.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                origQuery(params)
        );

        // 6. 硬件指纹
        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 16});
        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});

        // 7. 移除 PhantomJS 等检测痕迹
        delete window.callPhantom;
        delete window._phantom;
        delete window.__phantomas;

        // 8. 网络连接信息
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false })
        });
    """)


def login():
    """首次登录 — 有头浏览器，扫码后持久化到 profile"""
    print("[xhs] 打开有头浏览器，请扫码登录小红书...")
    print("[xhs] 登录成功后浏览器保持打开30秒确认，然后自动保存。")
    with sync_playwright() as p:
        context = _create_persistent_context(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        _apply_stealth(page)

        page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)

        # 尝试点击登录按钮（如果有弹窗）
        try:
            login_btn = page.query_selector('text=登录')
            if login_btn:
                login_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        print("[xhs] 请在浏览器中扫码登录...")
        page.wait_for_timeout(30000)

        # 检测登录状态
        logged_in = False
        try:
            user_el = page.query_selector('[class*="avatar"], .user-avatar, [class*="user"]')
            if user_el:
                logged_in = True
        except Exception:
            pass

        if logged_in:
            print("[xhs] 登录成功！profile 已保存到 dariel/xhs_profile/")
        else:
            print("[xhs] 未检测到登录，请确认扫码成功。可重新运行 --login。")

        page.wait_for_timeout(3000)
        context.close()


def browse_headless():
    """无头模式 — 用自己的登录态刷小红书 (v2: 持久化 profile)"""
    with sync_playwright() as p:
        context = _create_persistent_context(p, headless=True)
        page = context.pages[0] if context.pages else context.new_page()
        _apply_stealth(page)

        all_items = []

        try:
            page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=45000)

            # 模拟人类行为: 随机滚动几次
            for _ in range(random.randint(2, 4)):
                page.mouse.wheel(0, random.randint(300, 800))
                page.wait_for_timeout(random.randint(800, 1500))

            page.wait_for_timeout(2000)

            seen_urls = set()
            note_items = page.query_selector_all('.note-item')
            print(f"[xhs] 探索页找到 {len(note_items)} 个卡片")

            for item in note_items:
                try:
                    text = item.inner_text().strip()
                    if not text or len(text) < 4:
                        continue

                    link = item.query_selector('a[href*="/explore/"]')
                    if not link:
                        link = item.query_selector('a[href*="/search_result/"]')
                    if not link:
                        link = item.query_selector('a[href*="/discovery/"]')

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
            # 诊断信息
            try:
                body_text = page.inner_text('body')[:200]
                print(f"[xhs] 页面内容(前200字): {body_text}")
            except Exception:
                pass

        # 提取封面图并OCR (如果easyocr可用)
        screenshots = ocr_cover_images(page, note_items, all_items, max_notes=3)

        context.close()

        if screenshots:
            save_manifest(screenshots)

        return all_items, screenshots


def view_note(url):
    """打开具体笔记链接，提取标题+正文+图片OCR (v2: 持久化 profile)"""
    with sync_playwright() as p:
        context = _create_persistent_context(p, headless=True)
        page = context.pages[0] if context.pages else context.new_page()
        _apply_stealth(page)

        note = {"url": url, "source": "分享链接", "found_at": datetime.now().isoformat()}

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # 模拟人类: 等3秒+轻微滚动
            page.wait_for_timeout(random.randint(2500, 4000))
            page.mouse.wheel(0, random.randint(100, 300))
            page.wait_for_timeout(1000)

            # 提取标题 (多个选择器尝试)
            for sel in ['#detail-title', '.title', 'h1', '[class*="title"]', '#note-title', '.note-scroller h1']:
                try:
                    title_el = page.query_selector(sel)
                    if title_el:
                        note["title"] = title_el.inner_text().strip()[:200]
                        break
                except Exception:
                    continue
            if "title" not in note:
                note["title"] = page.title()[:120] or "无标题"

            # 提取正文
            for sel in ['#detail-desc', '.note-text', '[class*="desc"]', '.note-content', '[class*="content"]', '.note-scroller .content']:
                try:
                    desc_el = page.query_selector(sel)
                    if desc_el:
                        content = desc_el.inner_text().strip()
                        if content and len(content) > 10:
                            note["content"] = content[:2000]
                            break
                except Exception:
                    continue
            if "content" not in note:
                try:
                    body = page.inner_text('body')
                    lines = [l.strip() for l in body.split('\n') if len(l.strip()) > 15]
                    note["content"] = '\n'.join(lines[:20])[:2000]
                except Exception:
                    note["content"] = ""

        except Exception as e:
            print(f"[xhs] 笔记加载失败: {e}")
            note["title"] = "加载失败"
            note["content"] = str(e)[:500]
            context.close()
            return note

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

        context.close()

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


def run(no_push=False, headless=True):
    """v2 入口：浏览 + 保存 + 分享"""
    if headless:
        result = browse_headless()
    else:
        # 有头模式复用 browse_headless 逻辑但 headless=False
        with sync_playwright() as p:
            context = _create_persistent_context(p, headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            _apply_stealth(page)
            all_items = []
            try:
                page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=45000)
                for _ in range(random.randint(2, 4)):
                    page.mouse.wheel(0, random.randint(300, 800))
                    page.wait_for_timeout(random.randint(800, 1500))
                page.wait_for_timeout(2000)
                seen_urls = set()
                note_items = page.query_selector_all('.note-item')
                print(f"[xhs] 探索页(有头) 找到 {len(note_items)} 个卡片")
                for item in note_items:
                    try:
                        text = item.inner_text().strip()
                        if not text or len(text) < 4:
                            continue
                        link = item.query_selector('a[href*="/explore/"]')
                        if not link:
                            link = item.query_selector('a[href*="/search_result/"]')
                        if not link:
                            link = item.query_selector('a[href*="/discovery/"]')
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
                            "title": text[:120], "url": href,
                            "source": "小红书探索", "found_at": datetime.now().isoformat(),
                        })
                    except Exception:
                        continue
            except Exception as e:
                print(f"[xhs] 探索页加载失败: {e}")
            screenshots = ocr_cover_images(page, note_items, all_items, max_notes=3)
            context.close()
            result = all_items, screenshots

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
    headless = "--headed" not in sys.argv
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
                    print(f"[xhs] 正文:\n{note['content'][:500]}")
                if note.get("ocr_texts"):
                    for i, t in enumerate(note["ocr_texts"]):
                        print(f"[xhs] OCR[{i}]: {t[:200]}")
        else:
            print("[xhs] --link 需要URL参数")
    else:
        run(no_push=no_push, headless=headless)
