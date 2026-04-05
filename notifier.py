import logging
import time

import requests

from detector import RainEvent

logger = logging.getLogger("rain_bot")

# Discord embed colors
COLOR_ACTIVE = 0x2ECC71  # green
COLOR_UPCOMING = 0xF1C40F  # yellow


def _build_embed(event: RainEvent) -> dict:
    """Build the Discord embed dict for a rain event."""
    fields = []

    if event.amount:
        fields.append({"name": "Amount", "value": event.amount, "inline": True})

    if event.status == "active" and event.time_remaining is not None:
        unix_end = int(time.time()) + event.time_remaining
        fields.append({
            "name": "Ends in",
            "value": f"<t:{unix_end}:R>",
            "inline": True,
        })

    status_text = "IT'S RAINING!" if event.status == "active" else "Rain Pool Active"
    color = COLOR_ACTIVE if event.status == "active" else COLOR_UPCOMING

    return {
        "title": f"{status_text} - {event.site_name}",
        "url": event.site_url,
        "color": color,
        "fields": fields,
        "footer": {"text": "Rain Bot"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def send_rain_alert(webhook_url: str, event: RainEvent, ping: str = "") -> str | None:
    """Send a new Discord embed. Returns the message ID if successful."""
    embed = _build_embed(event)
    payload: dict = {"embeds": [embed]}

    if ping:
        payload["content"] = ping

    try:
        resp = requests.post(f"{webhook_url}?wait=true", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        msg_id = data.get("id")
        logger.info(f"Alert sent for {event.site_name} (msg_id={msg_id})")
        return msg_id
    except Exception as e:
        logger.error(f"Failed to send Discord alert for {event.site_name}: {e}")
        return None


def edit_rain_alert(webhook_url: str, message_id: str, event: RainEvent) -> bool:
    """Edit an existing Discord message with updated rain data."""
    embed = _build_embed(event)
    payload = {"embeds": [embed]}

    try:
        resp = requests.patch(
            f"{webhook_url}/messages/{message_id}",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        logger.debug(f"Updated alert for {event.site_name} (msg_id={message_id})")
        return True
    except Exception as e:
        logger.error(f"Failed to edit Discord alert for {event.site_name}: {e}")
        return False
