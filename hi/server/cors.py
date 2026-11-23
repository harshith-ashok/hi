"""Which browser origins may call the API.

Deliberately not `*`: CORS decides whether in-page JavaScript may read a response, so a wildcard would let
any site open in another tab read conversations and settings from this loopback server. Only tinyui's own
origins are allowed (plus any in HI_CORS_ORIGINS, which docker-compose sets from HI_WEB_PORT).
"""

from __future__ import annotations

import os

DEV_ORIGINS = ("http://localhost:5176", "http://127.0.0.1:5176")  # tinyui/vite.config.ts pins this port


def allowed_origins() -> list[str]:
    extra = [o.strip() for o in os.environ.get("HI_CORS_ORIGINS", "").split(",") if o.strip()]
    return sorted({*DEV_ORIGINS, *extra})
