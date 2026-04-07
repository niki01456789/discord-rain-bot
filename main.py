import asyncio
import logging
import signal
import sys
import os

import yaml

from logger_setup import setup_logger
from scanner import Scanner
from ocr import detect_rain_ocr
from notifier import send_rain_alert, edit_rain_alert
from state import RainState


def load_config(path: str = "config.yaml") -> dict:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def cleanup_ocr_debug(base_dir: str) -> None:
    for f in os.listdir(base_dir):
        if f.startswith("ocr_debug_") and f.endswith(".png"):
            try:
                os.remove(os.path.join(base_dir, f))
            except Exception:
                pass


logger = logging.getLogger("rain_bot")


async def scan_site(scanner: Scanner, site: dict, default_ping: str) -> tuple[str, str, object, str]:
    """Scan a single site and return (notify_url, ping, event_or_none, webhook_url)."""
    scan_url = site.get("scan_url", site.get("url"))  # fallback to old "url" field
    notify_url = site.get("notify_url", scan_url)  # fallback to scan_url if not specified
    keywords = site.get("keywords", ["rain", "raining"])
    timer_mode = site.get("timer_mode", "ocr")
    webhook_url = site.get("webhook_url", "")
    ping = site.get("ping", default_ping)

    if not webhook_url:
        logger.warning(f"No webhook_url configured for {scan_url}, skipping")
        return notify_url, ping, None, webhook_url

    logger.debug(f"Scanning {scan_url}...")
    page, _ = await scanner.load_page(scan_url)
    if page is None:
        return notify_url, ping, None, webhook_url

    event = await detect_rain_ocr(page, notify_url, keywords, timer_mode)
    if event:
        logger.debug(f"Rain detected via OCR on {scan_url}")
    else:
        logger.debug(f"No rain on {scan_url}")

    try:
        await page.close()
    except Exception:
        pass

    return notify_url, ping, event, webhook_url


async def scan_cycle(scanner: Scanner, state: RainState, config: dict):
    """Run one full scan cycle across all configured sites, 2 at a time."""
    await scanner.reset_context()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cleanup_ocr_debug(base_dir)

    sites = config.get("sites", [])
    default_ping = config.get("discord", {}).get("ping", "")

    rain_seen_this_cycle: set[str] = set()

    # Process in pairs; last site runs alone if odd count
    for i in range(0, len(sites), 2):
        batch = sites[i:i + 2]
        results = await asyncio.gather(*[scan_site(scanner, s, default_ping) for s in batch])

        for notify_url, ping, event, webhook_url in results:
            if event:
                rain_seen_this_cycle.add(notify_url)
                if state.is_new_rain(notify_url):
                    logger.info(f"NEW rain on {event.site_name}: {event.status}, amount={event.amount}")
                    msg_id = send_rain_alert(webhook_url, event, ping)
                    state.mark_active(notify_url, amount=event.amount, message_id=msg_id,
                                      webhook_url=webhook_url)
                else:
                    msg_id = state.get_message_id(notify_url)
                    wh_url = state.get_webhook_url(notify_url)
                    if msg_id and wh_url and (event.amount or event.time_remaining):
                        # Use last known amount if this scan didn't get one
                        if not event.amount:
                            event.amount = state.get_amount(notify_url)
                        elif event.amount:
                            state.update_amount(notify_url, event.amount)
                        edit_rain_alert(wh_url, msg_id, event)
                        logger.debug(f"Updated rain on {event.site_name}: amount={event.amount}, timer={event.time_remaining}")

    # Clear state for sites where rain has ended
    previously_active = state.get_active_sites()
    ended = previously_active - rain_seen_this_cycle
    for url in ended:
        logger.info(f"Rain ended on {url}")
        state.mark_ended(url)


async def main():
    setup_logger()
    logger.info("Rain Bot starting...")

    config = load_config()
    scan_interval = config.get("scan_interval", 60)
    page_timeout = config.get("page_timeout", 30)

    # Validate config
    sites = config.get("sites", [])
    if not sites:
        logger.error("No sites configured in config.yaml")
        sys.exit(1)

    # Check that at least one site has a webhook
    sites_with_webhooks = [s for s in sites if s.get("webhook_url")]
    if not sites_with_webhooks:
        logger.error("No sites have webhook_url configured in config.yaml")
        sys.exit(1)

    logger.info(f"Monitoring {len(sites)} sites every {scan_interval}s")
    for site in sites:
        scan_url = site.get("scan_url", site.get("url", "unknown"))
        logger.info(f"  - {scan_url} (keywords: {site.get('keywords', ['rain', 'raining'])})")

    scanner = Scanner(page_timeout=page_timeout)
    state = RainState()

    # Graceful shutdown
    shutdown = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received...")
        shutdown.set()

    loop = asyncio.get_running_loop()
    # Only add signal handlers on non-Windows systems
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)
    else:
        # Windows workaround: use CTRL_C_EVENT
        def signal_handler(sig, frame):
            handle_signal()
        signal.signal(signal.SIGINT, signal_handler)

    try:
        await scanner.start()

        while not shutdown.is_set():
            logger.info("--- Starting scan cycle ---")
            await scan_cycle(scanner, state, config)
            logger.info(f"--- Cycle complete, sleeping {scan_interval}s ---")

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=scan_interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await scanner.stop()
        logger.info("Rain Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
