"""Register the configured Blink QR, BitLibera OTP, and local demo adapters."""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self) -> None:
        from django.conf import settings

        if getattr(settings, "FOBOS_USE_DEMO_ADAPTERS", False):
            from .adapters import register_adapter, register_onramp_adapter
            from .demo import DemoBitLiberaOnrampAdapter, DemoBlinkDirectAdapter

            register_adapter(DemoBlinkDirectAdapter())
            register_onramp_adapter(DemoBitLiberaOnrampAdapter())
        elif getattr(settings, "FOBOS_USE_LIVE_ADAPTERS", False):
            from .adapters import register_adapter, register_onramp_adapter
            from .live import BitLiberaOnrampAdapter, BlinkDirectAdapter

            register_adapter(BlinkDirectAdapter())
            register_onramp_adapter(BitLiberaOnrampAdapter())
