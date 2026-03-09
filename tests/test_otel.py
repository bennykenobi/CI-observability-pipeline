"""Tests for OTEL endpoint parsing and optional audience configuration."""

from shared.config import Settings
from shared.otel import _derive_audience, _is_local_endpoint


def test_derive_audience_from_otlp_endpoint() -> None:
    assert (
        _derive_audience("https://collector.example.com/v1/traces")
        == "https://collector.example.com"
    )


def test_local_endpoint_detection() -> None:
    assert _is_local_endpoint("http://localhost:4318/v1/traces") is True
    assert _is_local_endpoint("http://127.0.0.1:4318/v1/traces") is True
    assert _is_local_endpoint("https://collector.example.com/v1/traces") is False


def test_settings_accept_optional_otlp_audience() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        webhook_secret="secret",
        webhook_auth_token="token",
        github_app_id="123",
        github_app_private_key="key",
        otel_exporter_otlp_endpoint="https://collector.example.com/v1/traces",
        otel_exporter_otlp_audience="https://collector.example.com",
    )
    assert settings.otel_exporter_otlp_audience == "https://collector.example.com"
