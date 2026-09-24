"""Reusable OpenAPI-only schemas for common API error responses."""

from rest_framework import serializers


class ApiErrorSerializer(serializers.Serializer):
    """An explicit API error returned by one of the views."""

    code = serializers.CharField(required=False)
    detail = serializers.CharField()
