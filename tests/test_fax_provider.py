from pathlib import Path

import pytest

from app.config import Settings
from app.services.fax_provider import FaxProvider, FaxProviderError


def test_fax_provider_errors_when_live_expected_but_telnyx_not_configured(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        mock_providers=False,
        telnyx_api_key=None,
        telnyx_connection_id=None,
        telnyx_from_number=None,
    )

    provider = FaxProvider(settings)

    with pytest.raises(FaxProviderError, match="Telnyx is not configured"):
        provider.send_fax(destination_fax="+14155550123", media_url="https://example.com/file.pdf")


def test_fax_provider_cancel_errors_when_live_expected_but_telnyx_not_configured(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        mock_providers=False,
        telnyx_api_key=None,
        telnyx_connection_id=None,
        telnyx_from_number=None,
    )

    provider = FaxProvider(settings)

    with pytest.raises(FaxProviderError, match="Telnyx is not configured"):
        provider.cancel_fax(provider_job_id="fax_123")
