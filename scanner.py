import logging
import time

from playwright.async_api import async_playwright, Browser, Page, Playwright
from playwright_stealth import Stealth

logger = logging.getLogger("rain_bot")


class Scanner:
    """Manages a single headless Chromium browser.
    Each load_page call gets its own tab — safe to run concurrently."""

    def __init__(self, page_timeout: int = 30):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context = None
        self._page_timeout = page_timeout * 1000  # ms
        self._stealth = Stealth()

    async def _new_context(self):
        return await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._new_context()
        logger.info("Browser started (stealth mode)")

    async def reset_context(self):
        """Close the current browser context and open a fresh one.
        Call at the start of each scan cycle to avoid Cloudflare fingerprint detection."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = await self._new_context()
        logger.debug("Browser context reset")

    async def _new_page(self) -> Page:
        """Create a fresh page with stealth applied."""
        page = await self._context.new_page()
        await self._stealth.apply_stealth_async(page)
        return page

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped")

    async def load_page(self, url: str) -> tuple[Page | None, list[str]]:
        """
        Navigate to URL in a fresh tab, wait for content, capture WS messages.
        Each call is independent — safe to run concurrently for multiple sites.
        Returns (page, ws_messages) or (None, []) on failure.
        """
        ws_messages: list[str] = []

        start = time.time()
        page = None
        try:
            page = await self._new_page()

            def on_ws(ws):
                logger.debug(f"WebSocket opened: {ws.url}")
                ws.on("framereceived", lambda payload: ws_messages.append(str(payload)))

            page.on("websocket", on_ws)

            await page.goto(url, wait_until="domcontentloaded", timeout=self._page_timeout)
            await page.wait_for_timeout(4000)
            elapsed = time.time() - start
            logger.debug(f"Loaded {url} in {elapsed:.1f}s, captured {len(ws_messages)} WS messages")
            return page, ws_messages
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"Failed to load {url} after {elapsed:.1f}s: {e}")
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            return None, []
