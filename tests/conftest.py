from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        uploads_dir=str(uploads_dir),
        base_url="http://testserver",
        mock_providers=True,
        telnyx_api_key=None,
        telnyx_connection_id=None,
        telnyx_from_number=None,
        rate_limit_ip_per_hour=200,
    )

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
