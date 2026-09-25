"""Integrations — plain Python packages, NOT a Django app (architecture note).

Each subpackage (`blink/`, `bitlibera/`) is the **remote-service client contract
layer** (Tech Spec §5): an abstract client + typed DTOs whose endpoint/mapping
implementations belong to Backend Dev B. FOBOS only ships interface + registry
skeletons + demo fixtures here; the real network calls are B's.

Why a plain package and not a Django app? These are third-party service
clients, not part of the FOBOS data model — they must never appear in
`settings.INSTALLED_APPS`, never get admin, migrations, signals or URLs. They
live in `integrations/` and expose `PaymentRailAdapter`/`OnrampAdapter`
implementations that `payments.adapters.register_adapter` consumes (§3 step 1).

Django apps in this repo share the `accounts/payments/subscriptions/sales/...`
namespace; anything under `integrations/` is explicitly NOT part of it.
"""

from __future__ import annotations
