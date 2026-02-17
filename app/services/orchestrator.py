from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FaxJob
from app.services.emailer import send_email
from app.services.fax_provider import FaxProvider, FaxProviderError

logger = logging.getLogger(__name__)

FINAL_SUCCESS_STATUSES = {"delivered", "success"}
CANCELED_STATUSES = {"canceled", "cancelled", "cancel_requested"}
FINAL_FAILURE_STATUSES = {"failed", "error", "rejected"}
TERMINAL_JOB_STATUSES = {"delivered", "failed", "canceled"}


def dispatch_fax_job(
    *,
    session: Session,
    settings: Settings,
    fax_provider: FaxProvider,
    fax_job: FaxJob,
    media_url: str,
) -> FaxJob:
    if fax_job.status not in {"queued_for_send", "retry_queued"}:
        return fax_job

    fax_job.send_attempts += 1
    fax_job.status = "sending"
    fax_job.submitted_at = fax_job.submitted_at or datetime.now(UTC)

    try:
        result = fax_provider.send_fax(destination_fax=fax_job.destination_fax, media_url=media_url)
        fax_job.provider_job_id = result.provider_job_id
        fax_job.provider_status = result.provider_status

        if result.provider_status in FINAL_SUCCESS_STATUSES:
            fax_job.status = "delivered"
            fax_job.completed_at = datetime.now(UTC)
            if fax_job.notification_email:
                send_email(
                    settings,
                    to_email=fax_job.notification_email,
                    subject="Fax delivered",
                    body=f"Your fax to {fax_job.destination_fax} was delivered successfully.",
                )
        elif result.provider_status in CANCELED_STATUSES:
            fax_job.status = "canceled"
            fax_job.completed_at = datetime.now(UTC)
            fax_job.failure_reason = "Canceled by user"
        elif result.provider_status in FINAL_FAILURE_STATUSES:
            fax_job.status = "failed"
            fax_job.failure_reason = "Fax provider marked this fax as failed."

    except FaxProviderError as exc:
        logger.warning("fax_dispatch_failed job_id=%s reason=%s", fax_job.id, exc)
        fax_job.status = "failed"
        fax_job.failure_reason = str(exc)

    return fax_job


def apply_telnyx_status(fax_job: FaxJob, provider_status: str, failure_reason: str | None = None) -> FaxJob:
    normalized = provider_status.lower().strip()
    fax_job.provider_status = normalized

    if normalized in FINAL_SUCCESS_STATUSES:
        fax_job.status = "delivered"
        fax_job.completed_at = datetime.now(UTC)
        fax_job.failure_reason = None
    elif normalized in CANCELED_STATUSES:
        fax_job.status = "canceled"
        fax_job.completed_at = datetime.now(UTC)
        fax_job.failure_reason = "Canceled by user"
    elif normalized in FINAL_FAILURE_STATUSES:
        fax_job.status = "failed"
        fax_job.completed_at = datetime.now(UTC)
        fax_job.failure_reason = failure_reason or "Fax transmission failed"
    else:
        if fax_job.status not in TERMINAL_JOB_STATUSES:
            fax_job.status = "sending"

    return fax_job
