"""`integrations.blink` — plain Python package, NOT a Django app (doc §4–5).

Encapsulates every Blink-specific detail (GraphQL documents, HTTP client,
WebSocket subscriptions, typed errors) behind services FOBOS can use without
knowing the provider's API. Never registered in ``INSTALLED_APPS``, never used
by ``config/urls.py``; the HTTP webhook belongs to ``payments/webhooks.py``
(doc §27–31).
"""

from .client import BlinkClient
from .services import BlinkInvoice, BlinkService, translate_invoice_status
from .subscriptions import (
    GRAPHQL_TRANSPORT_SUBPROTOCOL,
    BLINK_WSS_DEFAULT_URL,
    SUBSCRIPTION_INVOICE_STATUS,
    iter_statuses,
    on_status_change,
)

__all__ = [
    "BlinkClient",
    "BlinkInvoice",
    "BlinkService",
    "translate_invoice_status",
    "GRAPHQL_TRANSPORT_SUBPROTOCOL",
    "BLINK_WSS_DEFAULT_URL",
    "SUBSCRIPTION_INVOICE_STATUS",
    "iter_statuses",
    "on_status_change",
]
