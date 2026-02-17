from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AnalyticsEvent, DocumentUpload, FaxJob, WebhookEvent
from app.services.storage_backend import StorageBackend


def run_retention_cleanup(
    *,
    session: Session,
    settings: Settings,
    storage_backend: StorageBackend,
) -> dict[str, int]:
    now = datetime.now(UTC)
    deleted_uploads = 0

    upload_cutoff = now - timedelta(hours=settings.retention_hours)
    delivered_stmt = (
        select(DocumentUpload)
        .join(FaxJob, FaxJob.document_upload_id == DocumentUpload.id)
        .where(FaxJob.status == "delivered")
        .where(FaxJob.completed_at.is_not(None))
        .where(FaxJob.completed_at < upload_cutoff)
        .where(DocumentUpload.deleted_at.is_(None))
    )

    for upload in session.execute(delivered_stmt).scalars().all():
        if storage_backend.delete(storage_key=upload.storage_key):
            upload.deleted_at = now
            upload.deleted_reason = "retention_policy"
            deleted_uploads += 1

    logs_cutoff = now - timedelta(days=settings.logs_retention_days)

    deleted_webhook_events = session.execute(
        delete(WebhookEvent).where(WebhookEvent.received_at < logs_cutoff)
    ).rowcount or 0

    deleted_analytics_events = session.execute(
        delete(AnalyticsEvent).where(AnalyticsEvent.created_at < logs_cutoff)
    ).rowcount or 0

    return {
        "deleted_uploads": deleted_uploads,
        "deleted_webhook_events": deleted_webhook_events,
        "deleted_analytics_events": deleted_analytics_events,
    }
