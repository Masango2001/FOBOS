from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("", include("sales.urls")),
    path("", include("products.urls")),
    path("", include("ledger.urls")),
    path("", include("automation.urls")),
    path("", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns.extend(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))
