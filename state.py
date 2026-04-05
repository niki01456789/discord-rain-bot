import time


class RainState:
    """Tracks active rain events per site to avoid duplicate alerts."""

    def __init__(self):
        # {site_url: {"detected_at": float, "amount": str|None, "message_id": str|None, "webhook_url": str|None}}
        self._active: dict[str, dict] = {}

    def is_new_rain(self, site_url: str) -> bool:
        return site_url not in self._active

    def mark_active(self, site_url: str, amount: str | None = None,
                    message_id: str | None = None, webhook_url: str | None = None):
        self._active[site_url] = {
            "detected_at": time.time(),
            "amount": amount,
            "message_id": message_id,
            "webhook_url": webhook_url,
        }

    def get_message_id(self, site_url: str) -> str | None:
        entry = self._active.get(site_url)
        return entry["message_id"] if entry else None

    def get_webhook_url(self, site_url: str) -> str | None:
        entry = self._active.get(site_url)
        return entry["webhook_url"] if entry else None

    def get_amount(self, site_url: str) -> str | None:
        entry = self._active.get(site_url)
        return entry["amount"] if entry else None

    def update_amount(self, site_url: str, amount: str) -> None:
        if site_url in self._active and amount:
            self._active[site_url]["amount"] = amount

    def mark_ended(self, site_url: str):
        self._active.pop(site_url, None)

    def get_active_sites(self) -> set[str]:
        return set(self._active.keys())
