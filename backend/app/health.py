"""Minimal health helpers used by the initial CI scaffold."""


def health_status() -> dict[str, str]:
    """Return a stable health payload for smoke tests."""
    return {"status": "ok"}
