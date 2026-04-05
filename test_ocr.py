"""Quick OCR test — run against a single site and print results."""
import asyncio
import sys

from scanner import Scanner
from ocr import detect_rain_ocr
from logger_setup import setup_logger


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://howl.gg"
    keywords = ["rain", "raining"]

    logger = setup_logger()
    logger.info(f"Testing OCR on {url}")

    scanner = Scanner(page_timeout=30)
    await scanner.start()

    try:
        page, _ = await scanner.load_page(url)
        if page is None:
            print("ERROR: Failed to load page")
            return

        # Try to open the chat/rain sidebar if present
        try:
            chat_btn = await page.query_selector("[data-testid='chat-button'], .chat-toggle, [aria-label*='chat' i], [aria-label*='rain' i]")
            if chat_btn:
                await chat_btn.click()
                await page.wait_for_timeout(2000)
                print("Clicked chat button")
        except Exception as e:
            print(f"No chat button found: {e}")

        event = await detect_rain_ocr(page, url, keywords)

        if event:
            print(f"\n✓ RAIN DETECTED")
            print(f"  status:        {event.status}")
            print(f"  amount:        {event.amount}")
            print(f"  time_remaining:{event.time_remaining}s")
            print(f"  raw_text:      {event.raw_text}")
        else:
            print("\n✗ No rain detected")

        print(f"\nDebug screenshot saved to /tmp/ocr_debug_{url.split('//')[1].split('/')[0]}.png")
    finally:
        await scanner.stop()


asyncio.run(main())
