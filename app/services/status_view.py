from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FaxJob, WebhookEvent
from app.schemas import FaxJobStatusResponse, FaxTimelineEvent

TELNYX_EVENT_MAP: dict[str, tuple[str, str, int]] = {
    "fax.queued": ("fax_queued", "Queued by Telnyx", 45),
    "fax.media.processed": ("fax_media_processed", "Document processed", 68),
    "fax.sending.started": ("fax_sending_started", "Transmission started", 82),
    "fax.delivered": ("fax_delivered", "Delivered", 100),
    "fax.failed": ("fax_failed", "Transmission failed", 100),
    "fax.canceled": ("fax_canceled", "Canceled", 100),
    "fax.cancelled": ("fax_canceled", "Canceled", 100),
}

STATUS_DEFAULT_PROGRESS: dict[str, tuple[int, str, str]] = {
    "queued_for_send": (30, "Queued for send", "queued_for_send"),
    "retry_queued": (35, "Retry queued", "retry_queued"),
    "sending": (58, "Transmission in progress", "sending"),
    "delivered": (100, "Fax delivered successfully", "delivered"),
    "failed": (100, "Transmission failed", "failed"),
    "canceled": (100, "Fax canceled", "canceled"),
    "cancelled": (100, "Fax canceled", "canceled"),
}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_telnyx_payload(payload: dict) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        nested = data.get("payload")
        if isinstance(nested, dict):
            return nested

    root_payload = payload.get("payload") if isinstance(payload, dict) else None
    if isinstance(root_payload, dict):
        return root_payload

    return {}


def _extract_provider_job_id(payload: dict) -> str | None:
    telnyx_payload = _extract_telnyx_payload(payload)
    fax = telnyx_payload.get("fax")
    if isinstance(fax, dict) and fax.get("id"):
        return str(fax["id"])

    if telnyx_payload.get("fax_id"):
        return str(telnyx_payload["fax_id"])

    if telnyx_payload.get("id"):
        return str(telnyx_payload["id"])

    return None


def _telnyx_event_occurred_at(payload: dict, fallback: datetime) -> datetime:
    data = payload.get("data") if isinstance(payload, dict) else None
    occurred_at = data.get("occurred_at") if isinstance(data, dict) else None
    parsed = _parse_iso_datetime(occurred_at) if isinstance(occurred_at, str) else None
    return parsed or fallback


def _build_internal_timeline(fax_job: FaxJob) -> list[FaxTimelineEvent]:
    timeline = [
        FaxTimelineEvent(
            at=fax_job.created_at,
            stage="job_created",
            label="Request created",
            source="system",
            detail=f"Destination {fax_job.destination_fax}",
        )
    ]

    if fax_job.submitted_at:
        timeline.append(
            FaxTimelineEvent(
                at=fax_job.submitted_at,
                stage="submitted",
                label="Submitted to fax provider",
                source="system",
                detail=fax_job.provider_job_id,
            )
        )

    if fax_job.status in {"delivered", "failed", "canceled", "cancelled"} and fax_job.completed_at:
        final_label = {
            "delivered": "Completed: delivered",
            "failed": "Completed: failed",
            "canceled": "Completed: canceled",
            "cancelled": "Completed: canceled",
        }.get(fax_job.status, "Completed")
        timeline.append(
            FaxTimelineEvent(
                at=fax_job.completed_at,
                stage=f"final_{fax_job.status}",
                label=final_label,
                source="system",
                detail=fax_job.failure_reason,
            )
        )

    return timeline


def _build_telnyx_timeline(session: Session, fax_job: FaxJob) -> list[FaxTimelineEvent]:
    if not fax_job.provider_job_id:
        return []

    raw_events = (
        session.execute(
            select(WebhookEvent)
            .where(
                WebhookEvent.provider == "telnyx",
                WebhookEvent.payload_json.like(f"%{fax_job.provider_job_id}%"),
            )
            .order_by(WebhookEvent.received_at.asc())
            .limit(250)
        )
        .scalars()
        .all()
    )

    timeline: list[FaxTimelineEvent] = []
    for event in raw_events:
        try:
            payload = json.loads(event.payload_json)
        except Exception:
            continue

        event_provider_job_id = _extract_provider_job_id(payload)
        if event_provider_job_id != fax_job.provider_job_id:
            continue

        event_type = (event.event_type or "provider.update").strip().lower()
        stage, label, _ = TELNYX_EVENT_MAP.get(
            event_type,
            (f"provider_{event_type.replace('.', '_')}", event_type, 0),
        )

        telnyx_payload = _extract_telnyx_payload(payload)
        detail = telnyx_payload.get("failure_reason") or telnyx_payload.get("status")

        timeline.append(
            FaxTimelineEvent(
                at=_telnyx_event_occurred_at(payload, event.received_at),
                stage=stage,
                label=label,
                source="telnyx",
                detail=str(detail) if detail else None,
            )
        )

    return timeline


def _compute_progress(fax_job: FaxJob, timeline: list[FaxTimelineEvent]) -> tuple[int, str, str]:
    default_percent, default_label, default_stage = STATUS_DEFAULT_PROGRESS.get(
        fax_job.status,
        (30, "Preparing transmission", "processing"),
    )

    telnyx_events = [event for event in timeline if event.source == "telnyx"]
    if not telnyx_events:
        return default_percent, default_label, default_stage

    latest_telnyx = telnyx_events[-1]
    latest_stage_progress = 0

    for _, (stage, _, percent) in TELNYX_EVENT_MAP.items():
        if latest_telnyx.stage == stage:
            latest_stage_progress = percent
            break

    if fax_job.status == "sending":
        percent = max(default_percent, latest_stage_progress or default_percent)
        label = latest_telnyx.label if latest_stage_progress else default_label
        return percent, label, latest_telnyx.stage

    if fax_job.status in {"delivered", "failed", "canceled", "cancelled"}:
        return 100, latest_telnyx.label, latest_telnyx.stage

    return default_percent, default_label, default_stage


def _sort_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_fax_job_status_response(session: Session, fax_job: FaxJob) -> FaxJobStatusResponse:
    timeline = _build_internal_timeline(fax_job) + _build_telnyx_timeline(session, fax_job)
    timeline.sort(key=lambda event: (_sort_time(event.at), event.source, event.stage))

    progress_percent, progress_label, progress_stage = _compute_progress(fax_job, timeline)

    return FaxJobStatusResponse(
        id=fax_job.id,
        status=fax_job.status,
        provider_status=fax_job.provider_status,
        submitted_at=fax_job.submitted_at,
        completed_at=fax_job.completed_at,
        failure_reason=fax_job.failure_reason,
        destination_fax=fax_job.destination_fax,
        page_count=fax_job.document_upload.page_count,
        progress_percent=progress_percent,
        progress_label=progress_label,
        progress_stage=progress_stage,
        timeline=timeline,
    )
