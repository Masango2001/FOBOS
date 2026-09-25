"""Create and render FOBOS internal-use EAN-13 product barcodes.

Codes use the GS1 restricted-circulation 20 prefix and are unique within a
merchant catalog. Legacy ``F.`` barcodes remain decodable for existing items.
Manufacturer barcodes are stored as supplied and matched exactly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid as uuid_module
from decimal import Decimal
from typing import NamedTuple

BARCODE_PREFIX = "F."
MAX_NAME_CHARS = 24
INTERNAL_EAN_PREFIX = "20"


def calculate_ean13_check_digit(twelve_digits: str) -> str:
    """Return the GS1 Modulo 10 check digit for a 12-digit EAN body."""
    if len(twelve_digits) != 12 or not twelve_digits.isdigit():
        raise ValueError("A 12-digit sequence is required to calculate an EAN-13 check digit.")
    total = sum(
        int(digit) * (1 if index % 2 == 0 else 3)
        for index, digit in enumerate(twelve_digits)
    )
    return str((-total) % 10)


def build_internal_ean13(*, product_id, business_id) -> str:
    """Build a deterministic 13-digit internal code scoped to a business."""
    seed = f"{business_id}:{product_id}".encode("utf-8")
    item_number = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % 10_000_000_000
    body = f"{INTERNAL_EAN_PREFIX}{item_number:010d}"
    return f"{body}{calculate_ean13_check_digit(body)}"


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


def sync_barcode_image(product) -> None:
    """Persist the Code128 PNG on the media storage, keeping it in sync.

    - no barcode          → remove any stored image (no orphan files)
    - path already current → cheap no-op (the upload_to callable bakes the
      barcode-value digest into the path, so an unchanged value keeps the same
      name → the post_save guard is idempotent, no recursion)
    - barcode changed     → new name (new digest), the old PNG is deleted and
      the new one written (one file per code — no orphans ever)
    """
    from django.core.files.base import ContentFile

    target_name = f"barcodes/{product.id}.png"
    storage = product.barcode_image.field.storage
    if not product.barcode:
        if product.barcode_image:
            product.barcode_image.delete(save=False)
            product.save(update_fields=["barcode_image"])
        return
    if product.barcode_image.name == target_name and storage.exists(target_name):
        if storage.open(target_name).read() == render_barcode_png(product.barcode):
            return
        product.barcode_image.delete(save=False)
    png = render_barcode_png(product.barcode)
    product.barcode_image.save(target_name, ContentFile(png), save=False)
    product.save(update_fields=["barcode_image"])


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
