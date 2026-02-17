from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class FaxSendResult:
    provider_job_id: str
    provider_status: str


class FaxProviderError(RuntimeError):
    pass


class FaxProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send_fax(self, *, destination_fax: str, media_url: str) -> FaxSendResult:
        if self.settings.is_live_telnyx:
            logger.info("fax_provider_mode=live_telnyx destination=%s", destination_fax)
            return self._send_via_telnyx(destination_fax=destination_fax, media_url=media_url)

        if self.settings.mock_providers:
            logger.info("fax_provider_mode=mock destination=%s", destination_fax)
            return FaxSendResult(
                provider_job_id=f"mock_fax_{uuid4().hex[:20]}",
                provider_status="delivered",
            )

        raise FaxProviderError(
            "Telnyx is not configured for live send. Set TELNYX_FAX_TELNYX_API_KEY, TELNYX_FAX_TELNYX_CONNECTION_ID, and TELNYX_FAX_TELNYX_FROM_NUMBER."
        )

    def cancel_fax(self, *, provider_job_id: str) -> str:
        if self.settings.is_live_telnyx:
            logger.info("fax_provider_cancel_mode=live_telnyx provider_job_id=%s", provider_job_id)
            return self._cancel_via_telnyx(provider_job_id=provider_job_id)

        if self.settings.mock_providers:
            logger.info("fax_provider_cancel_mode=mock provider_job_id=%s", provider_job_id)
            return "canceled"

        raise FaxProviderError(
            "Telnyx is not configured for live cancel. Set TELNYX_FAX_TELNYX_API_KEY, TELNYX_FAX_TELNYX_CONNECTION_ID, and TELNYX_FAX_TELNYX_FROM_NUMBER."
        )

    def _send_via_telnyx(self, *, destination_fax: str, media_url: str) -> FaxSendResult:
        if not media_url.startswith("https://"):
            raise FaxProviderError("Live Telnyx mode requires an HTTPS media URL")

        payload = {
            "connection_id": self.settings.telnyx_connection_id,
            "media_url": media_url,
            "from": self.settings.telnyx_from_number,
            "to": destination_fax,
            "quality": "high",
        }
        headers = {
            "Authorization": f"Bearer {self.settings.telnyx_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post("https://api.telnyx.com/v2/faxes", json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise FaxProviderError(f"Telnyx request failed: {exc}") from exc

        if response.status_code >= 300:
            raise FaxProviderError(f"Telnyx send failed: {response.status_code} {response.text[:200]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise FaxProviderError("Telnyx send failed: response was not valid JSON") from exc

        data = body.get("data", {})
        provider_job_id = data.get("id")
        if not provider_job_id:
            raise FaxProviderError("Telnyx response missing fax id")

        return FaxSendResult(provider_job_id=provider_job_id, provider_status=data.get("status", "queued"))

    def _cancel_via_telnyx(self, *, provider_job_id: str) -> str:
        if not provider_job_id:
            raise FaxProviderError("Missing provider fax id for cancel")

        headers = {
            "Authorization": f"Bearer {self.settings.telnyx_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    f"https://api.telnyx.com/v2/faxes/{provider_job_id}/actions/cancel",
                    headers=headers,
                )
        except httpx.RequestError as exc:
            raise FaxProviderError(f"Telnyx cancel request failed: {exc}") from exc

        if response.status_code >= 300:
            raise FaxProviderError(f"Telnyx cancel failed: {response.status_code} {response.text[:200]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise FaxProviderError("Telnyx cancel failed: response was not valid JSON") from exc

        data = body.get("data", {})
        result = str(data.get("result") or "").lower().strip()
        if result == "ok":
            return "cancel_requested"

        return result or "cancel_requested"
