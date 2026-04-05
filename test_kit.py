"""
Rain Bot Test Kit
Usage:
  python test_kit.py ocr <url>      – OCR screenshot + raw text + detection result
  python test_kit.py bar <url>      – watch bar fill % live every 2s
  python test_kit.py detect <url>   – full detection pipeline (no Discord send)
  python test_kit.py dom <url>      – dump all bar-like DOM elements
  python test_kit.py popup <url>    – dump rain popup text + aria progressbar attributes
"""

import asyncio
import sys
from urllib.parse import urlparse

from scanner import Scanner
from ocr import detect_rain_ocr, _preprocess, _find_amount, _find_timer, _get_bar_fill_pct
import pytesseract


def site_config(url: str) -> dict:
    """Return config defaults for a URL, matching config.yaml where relevant."""
    configs = {
        "rain.gg": {"keywords": ["rain", "raining"], "timer_mode": "bar"},
    }
    host = urlparse(url).netloc
    return configs.get(host, {"keywords": ["rain", "raining"], "timer_mode": "ocr"})


async def make_page(url: str):
    scanner = Scanner(page_timeout=30)
    await scanner.start()
    await scanner.reset_context()
    print(f"Loading {url}...")
    page, _ = await scanner.load_page(url)
    return scanner, page


# ── OCR ──────────────────────────────────────────────────────────────────────

async def cmd_ocr(url: str):
    scanner, page = await make_page(url)
    if page is None:
        print("Failed to load page")
        await scanner.stop()
        return

    screenshot = await page.screenshot(full_page=False)
    img = _preprocess(screenshot)
    raw_text = pytesseract.image_to_string(img, config="--psm 6")

    print("\n── RAW OCR TEXT ─────────────────────────────────────────────")
    print(raw_text[:2000])

    cfg = site_config(url)
    lower = raw_text.lower()

    from ocr import DEFINITIVE_PHRASES, FALSE_POSITIVE_PHRASES
    print("\n── DEFINITIVE PHRASES FOUND ─────────────────────────────────")
    for p in DEFINITIVE_PHRASES:
        if p in lower:
            print(f"  ✓ '{p}'")

    print("\n── FALSE POSITIVE PHRASES FOUND ─────────────────────────────")
    for p in FALSE_POSITIVE_PHRASES:
        if p in lower:
            print(f"  ✗ '{p}'")

    # Find best keyword position
    keyword_idx = -1
    for p in DEFINITIVE_PHRASES:
        idx = lower.find(p)
        if idx != -1:
            keyword_idx = idx
            break
    if keyword_idx == -1:
        for kw in cfg["keywords"]:
            idx = lower.find(kw)
            if idx != -1:
                keyword_idx = idx
                break

    print(f"\n── EXTRACTED VALUES (keyword_idx={keyword_idx}) ─────────────")
    amount = _find_amount(raw_text, keyword_idx) if keyword_idx != -1 else None
    timer = _find_timer(raw_text, keyword_idx) if keyword_idx != -1 else None
    print(f"  Amount : {amount}")
    print(f"  Timer  : {timer}s ({timer // 60:02d}:{timer % 60:02d})" if timer else f"  Timer  : None")

    await page.close()
    await scanner.stop()


# ── BAR ───────────────────────────────────────────────────────────────────────

async def cmd_bar(url: str):
    scanner, page = await make_page(url)
    if page is None:
        print("Failed to load page")
        await scanner.stop()
        return

    print("\nWatching bar fill every 2s — Ctrl+C to stop\n")
    readings = []
    try:
        while True:
            fill = await _get_bar_fill_pct(page)
            readings.append(fill)
            if fill is None:
                print("  fill: None (no bar found)")
            else:
                bar = "█" * int(fill * 40) + "░" * (40 - int(fill * 40))
                print(f"  fill: {fill:.4f}  [{bar}]")

            if len(readings) >= 2:
                prev = readings[-2]
                curr = readings[-1]
                if prev and curr:
                    decrease = prev - curr
                    if decrease > 0:
                        rate = decrease / 2.0
                        remaining = int(curr / rate)
                        print(f"           ↓ {decrease:.4f} per 2s → ~{remaining}s remaining ({remaining // 60:02d}:{remaining % 60:02d})")
                    else:
                        print(f"           no shrink detected")

            await page.wait_for_timeout(2000)
    except KeyboardInterrupt:
        pass

    await page.close()
    await scanner.stop()


# ── DETECT ────────────────────────────────────────────────────────────────────

async def cmd_detect(url: str):
    scanner, page = await make_page(url)
    if page is None:
        print("Failed to load page")
        await scanner.stop()
        return

    cfg = site_config(url)
    print(f"Running detection (timer_mode={cfg['timer_mode']})...")
    event = await detect_rain_ocr(page, url, cfg["keywords"], cfg["timer_mode"])

    print("\n── DETECTION RESULT ─────────────────────────────────────────")
    if event is None:
        print("  No rain detected")
    else:
        print(f"  Status       : {event.status}")
        print(f"  Site         : {event.site_name}")
        print(f"  Amount       : {event.amount}")
        timer = event.time_remaining
        print(f"  Time remain  : {timer}s ({timer // 60:02d}:{timer % 60:02d})" if timer else f"  Time remain  : None")
        print(f"  Raw text     : {event.raw_text[:120]}")
        print("\n  ── Discord embed preview ──")
        print(f"  Title  : IT'S RAINING! - {event.site_name}")
        if event.amount:
            print(f"  Amount : {event.amount}")
        if event.time_remaining:
            print(f"  Ends in: <t:{int(__import__('time').time()) + event.time_remaining}:R>  (~{timer // 60:02d}:{timer % 60:02d})")

    await page.close()
    await scanner.stop()


# ── DOM ───────────────────────────────────────────────────────────────────────

async def cmd_dom(url: str):
    scanner, page = await make_page(url)
    if page is None:
        print("Failed to load page")
        await scanner.stop()
        return

    print("\n── BAR-LIKE DOM ELEMENTS ────────────────────────────────────")
    result = await page.evaluate("""() => {
        const found = [];
        for (const el of document.querySelectorAll('*')) {
            const rect = el.getBoundingClientRect();
            if (rect.width < 30 || rect.height < 2 || rect.height > 40) continue;
            const parent = el.parentElement;
            if (!parent) continue;
            const parentRect = parent.getBoundingClientRect();
            if (parentRect.width < 50) continue;
            const fill = rect.width / parentRect.width;
            if (fill > 0.05 && fill < 0.99) {
                found.push({
                    tag: el.tagName,
                    cls: el.className.toString().slice(0, 80),
                    id: el.id || '',
                    fill: parseFloat(fill.toFixed(4)),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y)
                });
            }
        }
        return found;
    }""")

    if not result:
        print("  No bar-like elements found")
    else:
        print(f"  {'TAG':<8} {'FILL':>6}  {'W':>5}x{'H':<4} {'X':>5},{'Y':<5}  CLASS / ID")
        print(f"  {'─'*8} {'─'*6}  {'─'*5} {'─'*4} {'─'*5} {'─'*5}  {'─'*40}")
        for r in result:
            label = r['cls'] or r['id'] or '(none)'
            print(f"  {r['tag']:<8} {r['fill']:>6.3f}  {r['w']:>5}x{r['h']:<4} {r['x']:>5},{r['y']:<5}  {label}")

    await page.close()
    await scanner.stop()


# ── POPUP ─────────────────────────────────────────────────────────────────────

async def cmd_popup(url: str):
    """Dump the rain popup element's inner text + aria attributes + child elements."""
    scanner, page = await make_page(url)
    if page is None:
        print("Failed to load page")
        await scanner.stop()
        return

    print("\n── ARIA PROGRESSBARS ────────────────────────────────────────")
    result = await page.evaluate("""() => {
        const bars = [];
        for (const el of document.querySelectorAll('[role="progressbar"]')) {
            bars.push({
                tag: el.tagName,
                cls: el.className.toString().slice(0, 80),
                now: el.getAttribute('aria-valuenow'),
                max: el.getAttribute('aria-valuemax'),
                min: el.getAttribute('aria-valuemin'),
            });
        }
        return bars;
    }""")
    if not result:
        print("  None found")
    else:
        for r in result:
            print(f"  {r['tag']} cls={r['cls']} now={r['now']} max={r['max']} min={r['min']}")

    print("\n── POPUP CSS BACKGROUND-SIZE (x>1500, y 50-400) ────────────")
    result2 = await page.evaluate("""() => {
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            const rect = el.getBoundingClientRect();
            if (rect.x < 1500 || rect.y < 50 || rect.y > 400) continue;
            const style = window.getComputedStyle(el);
            const bgSize = style.backgroundSize;
            if (!bgSize || bgSize === 'auto' || bgSize === 'auto auto' || bgSize === '0px 0px') continue;
            out.push({
                tag: el.tagName,
                cls: el.className.toString().slice(0, 60),
                bgSize,
                w: Math.round(rect.width),
                h: Math.round(rect.height),
                x: Math.round(rect.x),
                y: Math.round(rect.y),
            });
        }
        return out.slice(0, 20);
    }""")
    if not result2:
        print("  None found")
    else:
        for r in result2:
            print(f"  {r['tag']} {r['w']}x{r['h']} @{r['x']},{r['y']} bgSize={r['bgSize']!r} cls={r['cls']}")

    print("\n── POPUP TEXT (x>1500, y 50-400) ────────────────────────────")
    result3 = await page.evaluate("""() => {
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            const rect = el.getBoundingClientRect();
            if (rect.x < 1500 || rect.y < 50 || rect.y > 400) continue;
            const text = (el.innerText || el.textContent || '').trim();
            if (text.length < 3 || text.length > 200) continue;
            out.push({ tag: el.tagName, cls: el.className.toString().slice(0, 60), text: text.slice(0, 100) });
        }
        return out.slice(0, 30);
    }""")
    for r in result3:
        print(f"  {r['tag']} [{r['cls']}] → {r['text']!r}")

    await page.close()
    await scanner.stop()


# ── MAIN ──────────────────────────────────────────────────────────────────────

COMMANDS = {"ocr": cmd_ocr, "bar": cmd_bar, "detect": cmd_detect, "dom": cmd_dom, "popup": cmd_popup}

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    url = sys.argv[2]
    if not url.startswith("http"):
        url = "https://" + url

    asyncio.run(COMMANDS[cmd](url))
