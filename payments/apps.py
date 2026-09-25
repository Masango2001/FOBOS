"""Payments app: Payment model, adapter interface (Tech Spec §5) and confirmation service.

Scope note (AGENTS.md): FOBOS does NOT own the real BitLibera/Blink adapters —
Backend Dev B does. We only build against the `PaymentRailAdapter` interface and
consume a confirmed `FinancialEvent`.
"""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self) -> None:
        from django.conf import settings

        if getattr(settings, "FOBOS_USE_DEMO_ADAPTERS", False):
            from .adapters import register_adapter, register_onramp_adapter
            from .demo import (
                DemoBitLiberaOnrampAdapter,
                DemoBlinkDirectAdapter,
                DemoBitLiberaOfframpAdapter,
            )

            register_adapter(DemoBitLiberaOfframpAdapter())
            register_adapter(DemoBlinkDirectAdapter())
            register_onramp_adapter(DemoBitLiberaOnrampAdapter())
        elif getattr(settings, "FOBOS_USE_LIVE_ADAPTERS", False):
            from .adapters import register_adapter, register_onramp_adapter
            from .live import BitLiberaOfframpAdapter, BitLiberaOnrampAdapter, BlinkDirectAdapter

            register_adapter(BitLiberaOfframpAdapter())
            register_adapter(BlinkDirectAdapter())
            register_onramp_adapter(BitLiberaOnrampAdapter())
