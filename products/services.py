"""FOBOS-generated product barcodes (Tech Spec §8 step 3 / owner-facing).

When a product is created without a manufacturer barcode, we encode its
identity into a scannable code: `F.` + base64url(name | price | product_id).
Scanning it returns the product without relying on a lookup table for the
encoded fields — the DB lookup is done on the authoritative product id.

Manufacturer barcodes (numeric, e.g. EAN) are kept as-is and matched exactly.
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_module
from decimal import Decimal
from typing import NamedTuple

BARCODE_PREFIX = "F."
MAX_NAME_CHARS = 24


class BarcodePayload(NamedTuple):
    name: str
    price: str
    product_id: str


def build_product_barcode(*, name: str, price: Decimal, product_id) -> str:
    """Encode name | price | product id into a compact, scannable FOBOS barcode."""
    payload = json.dumps(
        {
            "n": name[:MAX_NAME_CHARS],
            "p": str(price),
            "i": str(product_id),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{BARCODE_PREFIX}{encoded}"


def render_barcode_png(barcode: str) -> bytes:
    """Render a scannable Code128 PNG image of a barcode value.

    Uses python-barcode + Pillow (ImageWriter). Code128 supports the full ASCII
    range, so both FOBOS-generated codes (alphanumeric) and manufacturer codes
    (e.g. numeric EAN stored as-is) can be drawn.
    """
    from barcode import Code128
    from barcode.writer import ImageWriter

    from io import BytesIO

    img = Code128(barcode, writer=ImageWriter())
    buf = BytesIO()
    img.write(buf, options={"module_width": 0.2, "module_height": 12, "write_text": True})
    return buf.getvalue()


def parse_product_barcode(barcode: str) -> BarcodePayload | None:
    """Decode a FOBOS barcode into its payload; None for manufacturer codes."""
    if not barcode.startswith(BARCODE_PREFIX):
        return None
    body = barcode[len(BARCODE_PREFIX) :]
    try:
        padded = body + "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        product_id = str(data["i"])
        uuid_module.UUID(product_id)
        return BarcodePayload(
            name=str(data.get("n", "")), price=str(data.get("p", "")), product_id=product_id
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
