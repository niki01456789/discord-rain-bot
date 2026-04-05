from dataclasses import dataclass


@dataclass
class RainEvent:
    site_name: str
    site_url: str
    status: str  # "active" or "upcoming"
    amount: str | None
    time_remaining: int | None  # seconds
    participants: int | None
    raw_text: str  # matched text for debugging
