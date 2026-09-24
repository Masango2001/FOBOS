from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("", include("sales.urls")),
    path("", include("products.urls")),
    path("", include("ledger.urls")),
    path("", include("automation.urls")),
    path("", include("payments.urls")),
]
