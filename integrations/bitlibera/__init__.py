"""`integrations.bitlibera` — plain Python package, NOT a Django app (doc §4–5).

Encapsulates every BitLibera-specific detail (REST endpoints, HTTP client,
typed errors, order-status translation) behind services FOBOS can use without
knowing the gateway's API. Never registered in ``INSTALLED_APPS``; the
confirmation of an order stays with `payments/` (polling of
`GET /api/v1/orders/:orderId` — doc §25).
"""

from .client import BitLiberaClient
from .services import BitLiberaService, translate_order_status

__all__ = ["BitLiberaClient", "BitLiberaService", "translate_order_status"]
