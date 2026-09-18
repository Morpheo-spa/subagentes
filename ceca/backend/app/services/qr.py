"""Public URLs and the QR codes that carry them.

The QR encodes the short public URL and nothing else: never document data,
never a signed storage URL.
"""

from __future__ import annotations

from io import BytesIO

import segno

from app.config import get_settings

#: Error correction level. "m" keeps a 50x30 mm thermal label scannable.
ERROR_CORRECTION = "m"
QUIET_ZONE_MODULES = 4


def public_url(token: str) -> str:
    """The URL a driver opens from the label."""
    return f"{get_settings().public_base_url}/v/{token}"


def qr_png(url: str, *, scale: int = 6) -> bytes:
    buffer = BytesIO()
    segno.make(url, error=ERROR_CORRECTION).save(
        buffer, kind="png", scale=scale, border=QUIET_ZONE_MODULES
    )
    return buffer.getvalue()


def qr_svg(url: str) -> str:
    buffer = BytesIO()
    segno.make(url, error=ERROR_CORRECTION).save(
        buffer, kind="svg", border=QUIET_ZONE_MODULES, xmldecl=False, svgclass=None
    )
    return buffer.getvalue().decode("utf-8")
