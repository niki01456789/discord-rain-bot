import io
import re
import logging
from urllib.parse import urlparse

import sys
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from playwright.async_api import Page

# Windows: set Tesseract path if not on PATH
if sys.platform == "win32":
    import os
    _tess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_tess):
        pytesseract.pytesseract.tesseract_cmd = _tess

from detector import RainEvent

logger = logging.getLogger("rain_bot")

TIMER_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
AMOUNT_RE = re.compile(r"\b(\d+[.,]\d{1,2})\b")

# Strong phrases — rain is definitively active, no join check needed
DEFINITIVE_PHRASES = [
    "it's raining", "its raining", "it'sraining", "itsraining",
    "it'sraining!", "itsraining!", "its raining!", "it's raining!",
    "raining now", "rain active", "rain is live", "rain in progress",
    "rain started", "login to join", "join rain",
    "grab your umbrella",
]

# Phrases that indicate a past/completed rain — not live
FALSE_POSITIVE_PHRASES = [
    "rain completed", "joined and received", "coins in total",
    "users joined", "rain pool", "rain bonus", "rain every",
    "what is rain", "how rain works", "rain ago", "min ago", "hours ago",
    "tip rain",
]


def _preprocess(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _find_timer(text: str, keyword_idx: int) -> int | None:
    """
    Find the closest valid MM:SS countdown timer to the rain keyword.
    Rejects wall-clock times (minutes >= 6 look like HH:MM chat timestamps).
    Searches the full OCR text, picking the match nearest to keyword_idx.
    """
    best = None
    best_dist = float("inf")
    for match in TIMER_RE.finditer(text):
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        if minutes >= 6:
            continue  # wall-clock time (e.g. 20:07)
        total = minutes * 60 + seconds
        if total == 0:
            continue
        dist = abs(match.start() - keyword_idx)
        if dist < best_dist:
            best_dist = dist
            best = total
    return best


def _find_amount(text: str, keyword_idx: int) -> str | None:
    """
    Find the closest decimal number to the rain keyword.
    Searches the full OCR text, picking the match nearest to keyword_idx.
    """
    best = None
    best_dist = float("inf")
    for match in AMOUNT_RE.finditer(text):
        # Skip live drop amounts — preceded by '@' with optional space (e.g. @0.04 or @ 38.27)
        pre = text[max(0, match.start() - 2):match.start()]
        if "@" in pre:
            continue
        # Skip percentages — amount followed immediately by '%'
        end = match.end()
        if end < len(text) and text[end] == "%":
            continue
        val = match.group(1).replace(",", ".")
        dist = abs(match.start() - keyword_idx)
        if dist < best_dist:
            best_dist = dist
            best = val
    return best


async def detect_rain_ocr(page: Page, site_url: str, keywords: list[str], timer_mode: str = "ocr") -> RainEvent | None:
    """
    Screenshot the page, OCR it, and check for:
      - rain keyword present
      - "join" text nearby (confirms rain is live and joinable)
      - timer (MM:SS) anywhere in the text
      - amount (decimal number) anywhere in the text
    """
    site_name = urlparse(site_url).netloc

    try:
        screenshot_bytes = await page.screenshot(full_page=False, timeout=10000)
    except Exception as e:
        logger.error(f"Screenshot failed for {site_name}: {e}")
        return None

    try:
        img = _preprocess(screenshot_bytes)
        raw_text = pytesseract.image_to_string(img, config="--psm 6")
    except Exception as e:
        logger.error(f"OCR failed for {site_name}: {e}")
        return None


    logger.debug(f"OCR text for {site_name}:\n{raw_text[:500]}")

    lower = raw_text.lower()
    keyword_idx = -1
    definitive = False

    # Check for strong "it's raining" style phrases first
    for phrase in DEFINITIVE_PHRASES:
        idx = lower.find(phrase)
        if idx != -1:
            keyword_idx = idx
            definitive = True
            logger.info(f"Definitive rain phrase '{phrase}' found on {site_name}")
            break

    JOIN_BUTTON_PHRASES = [
        "join rain", "join the rain", "login to join", "claim rain",
        "join now", "claim now",
    ]

    # Fall back to generic rain keyword — try every occurrence, skip false positives
    if keyword_idx == -1:
        for kw in keywords:
            search_from = 0
            kw_lower = kw.lower()
            while True:
                idx = lower.find(kw_lower, search_from)
                if idx == -1:
                    break
                ctx_start = max(0, idx - 150)
                ctx_end = min(len(lower), idx + 400)
                surrounding = lower[ctx_start:ctx_end]

                has_join = any(p in surrounding for p in JOIN_BUTTON_PHRASES)

                # A visible join button overrides false positive phrases —
                # chat snippets like "tip rain" shouldn't block a real active rain widget
                if not has_join:
                    if any(fp in surrounding for fp in FALSE_POSITIVE_PHRASES):
                        logger.debug(f"Skipping false positive '{kw}' occurrence on {site_name}")
                        search_from = idx + 1
                        continue
                    # No join button and no definitive signal — skip
                    search_from = idx + 1
                    continue

                keyword_idx = idx
                break

            if keyword_idx != -1:
                break

    if keyword_idx == -1:
        logger.debug(f"No rain keyword found on {site_name}")
        _save_debug(img, site_name)
        return None

    ctx_start = max(0, keyword_idx - 150)
    ctx_end = min(len(lower), keyword_idx + 400)
    surrounding = lower[ctx_start:ctx_end]

    # Definitive phrases are strong enough — skip false positive check
    # (e.g. rain.gg's active rain says "X% of the Rain Pool is dropping!" which contains "rain pool")

    # Extract amount and timer from OCR text
    amount = _find_amount(raw_text, keyword_idx)
    if timer_mode == "bar":
        time_remaining = await _calculate_bar_timer(page, site_name)
        if time_remaining is None:
            logger.debug(f"Bar timer failed on {site_name}, falling back to OCR timer")
            time_remaining = _find_timer(raw_text, keyword_idx)
    else:
        time_remaining = _find_timer(raw_text, keyword_idx)

    # If either value is missing, try a focused crop OCR on the widget area
    if amount is None or time_remaining is None:
        crop_text = _ocr_widget_crop(screenshot_bytes)
        if crop_text:
            if amount is None:
                amount = _find_amount(crop_text, 0)
            if time_remaining is None:
                time_remaining = _find_timer(crop_text, 0)

    logger.info(f"Active rain on {site_name}: amount={amount}, timer={time_remaining}s")
    _save_debug(img, site_name)

    return RainEvent(
        site_name=site_name,
        site_url=site_url,
        status="active",
        amount=amount,
        time_remaining=time_remaining,
        participants=None,
        raw_text=raw_text[max(0, keyword_idx - 50):keyword_idx + 200].replace("\n", " ").strip(),
    )


async def _get_bar_fill_pct(page: Page) -> float | None:
    """
    Inspect the DOM for a timer progress bar and return its fill fraction (0.0-1.0).
    Prioritises very thin elements (2-6px tall) which are the classic progress bar style.
    Falls back to slightly taller bars if nothing thin is found.
    """
    try:
        return await page.evaluate("""() => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;

            // Pass 0: aria progressbar (most reliable)
            for (const el of document.querySelectorAll('[role="progressbar"]')) {
                const now = parseFloat(el.getAttribute('aria-valuenow'));
                const max = parseFloat(el.getAttribute('aria-valuemax') || '100');
                if (!isNaN(now) && !isNaN(max) && max > 0) {
                    return now / max;
                }
            }

            // Pass 1: thin bars only (2-6px) — most progress bars are this height
            const thin = [];
            for (const el of document.querySelectorAll('*')) {
                const rect = el.getBoundingClientRect();
                if (rect.height < 2 || rect.height > 6) continue;
                if (rect.width < 50) continue;
                // Must be on screen or just above (popup may be partially off)
                if (rect.y < -10 || rect.y > vh) continue;
                const parent = el.parentElement;
                if (!parent) continue;
                const parentRect = parent.getBoundingClientRect();
                if (parentRect.width < 50) continue;
                const fill = rect.width / parentRect.width;
                if (fill > 0.05 && fill < 0.99) {
                    thin.push(fill);
                }
            }
            if (thin.length > 0) {
                thin.sort((a, b) => a - b);
                return thin[Math.floor(thin.length / 2)];
            }

            // Pass 2: slightly taller bars (7-20px) as fallback
            const wider = [];
            for (const el of document.querySelectorAll('*')) {
                const rect = el.getBoundingClientRect();
                if (rect.height < 7 || rect.height > 20) continue;
                if (rect.width < 80) continue;
                if (rect.y < -10 || rect.y > vh) continue;
                const parent = el.parentElement;
                if (!parent) continue;
                const parentRect = parent.getBoundingClientRect();
                if (parentRect.width < 80) continue;
                const fill = rect.width / parentRect.width;
                if (fill > 0.05 && fill < 0.99) {
                    wider.push(fill);
                }
            }
            if (wider.length > 0) {
                wider.sort((a, b) => a - b);
                return wider[Math.floor(wider.length / 2)];
            }

            return null;
        }""")
    except Exception as e:
        logger.debug(f"DOM bar fill check failed: {e}")
        return None


async def _calculate_bar_timer(page: Page, site_name: str) -> int | None:
    """
    Read the progress bar fill via DOM inspection twice, 2 seconds apart,
    and calculate time remaining from the shrink rate.
    fill2 / (fill1 - fill2) * 2 = seconds remaining
    """
    try:
        fill1 = await _get_bar_fill_pct(page)
        if fill1 is None:
            logger.debug(f"Bar timer: no bar found in DOM on {site_name} (reading 1)")
            return None

        await page.wait_for_timeout(2000)

        fill2 = await _get_bar_fill_pct(page)
        if fill2 is None:
            logger.debug(f"Bar timer: no bar found in DOM on {site_name} (reading 2)")
            return None

        decrease = fill1 - fill2
        if decrease <= 0:
            logger.debug(f"Bar timer: bar didn't shrink on {site_name} ({fill1:.3f}→{fill2:.3f})")
            return None

        rate_per_sec = decrease / 2.0
        time_remaining = int(fill2 / rate_per_sec)
        logger.info(f"Bar timer on {site_name}: {fill1:.3f}→{fill2:.3f}, ~{time_remaining}s remaining")
        return time_remaining

    except Exception as e:
        logger.debug(f"Bar timer calculation failed on {site_name}: {e}")
        return None


def _ocr_widget_crop(screenshot_bytes: bytes) -> str | None:
    """
    Crop the top-left quarter of the screenshot (where rain widgets typically live)
    and run a focused OCR pass with higher upscaling to catch small stylized text.
    """
    try:
        raw = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        w, h = raw.size
        # Top-left quarter — covers sidebar rain widgets on most sites
        crop = raw.crop((0, 0, w // 3, h // 2))
        # Aggressive upscale for small text
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
        crop = crop.convert("L")
        crop = ImageEnhance.Contrast(crop).enhance(3.0)
        crop = crop.filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(crop, config="--psm 6")
    except Exception:
        return None


def _save_debug(img: Image.Image, site_name: str) -> None:
    import os
    try:
        debug_dir = os.path.dirname(os.path.abspath(__file__))
        img.save(os.path.join(debug_dir, f"ocr_debug_{site_name}.png"))
    except Exception as e:
        logger.debug(f"Failed to save debug screenshot: {e}")
