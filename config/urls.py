from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from .views import health_check

urlpatterns: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health-check"),
    path("auth/", include("accounts.urls")),
    path("", include("sales.urls")),
    path("", include("products.urls")),
    path("", include("ledger.urls")),
    path("", include("automation.urls")),
    path("", include("payments.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    urlpatterns.extend(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))
else:
    # Product Code128 PNGs live on Render's persistent media disk.
    urlpatterns.append(
        path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT})
    )
