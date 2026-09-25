from django.db import connection
from django.http import JsonResponse


def health_check(request):
    connection.ensure_connection()
    return JsonResponse({"status": "ok"})
